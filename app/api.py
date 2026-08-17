from fastapi import FastAPI,HTTPException,UploadFile,File,Form,Depends,Query,BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pathlib import Path
from typing import Optional
import uuid
from pydantic import BaseModel, Field
from app.services.rag_service import answer_from_knowledge_base
from app.services.document_service import (
    list_text_files,
    create_document_from_file,
    kb_documents_dir,
    SUPPORTED_EXTENSIONS,
)
from app.services import knowledge_base_service
from app.services import metadata_service
from app.services import session_service
from app.services import topic_service
from app.services import user_service
from app.services import kb_service
from app.services import quota_service
from app.services import feedback_service
from app.services import notification_service
from app.services import model_usage_service
from app.services import auth_service
from app.services import retrieval_config_service
from app.services.auth_service import TokenError
from app.services.kb_service import QuotaExceededError
from app.config import (
    FEEDBACK_ATTACHMENT_DIR,
    FEEDBACK_ATTACHMENT_MAX_COUNT,
    FEEDBACK_ATTACHMENT_MAX_MB,
    RAG_TOP_K,
)
app = FastAPI()

# 允许前端（Vite 开发服务器）跨域访问。
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup():
    """服务启动：确保至少有一个管理员账号（首次启动时按配置预置）。"""
    user_service.ensure_default_admin()


# ===== 认证依赖 =====
_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict:
    """解析并校验登录令牌，返回当前用户；无令牌/无效/过期均 401。"""
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=401, detail="未登录或缺少令牌")
    try:
        payload = auth_service.decode_token(credentials.credentials)
    except TokenError as exc:
        raise HTTPException(status_code=401, detail=str(exc))

    user = user_service.get_by_username(payload.get("sub", ""))
    if user is None:
        raise HTTPException(status_code=401, detail="用户不存在或已被删除")
    return user


def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    """要求当前用户为管理员，否则 403。"""
    if current_user.get("role") != user_service.ROLE_ADMIN:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return current_user


def require_kb_access(kb_id: int, current_user: dict) -> dict:
    """校验当前用户对某知识库的访问权：属主或管理员放行，否则 403/404。返回该知识库。"""
    kb = kb_service.get(kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail="知识库不存在")
    is_admin = current_user.get("role") == user_service.ROLE_ADMIN
    if not is_admin and kb["owner_id"] != current_user.get("id"):
        raise HTTPException(status_code=403, detail="无权访问该知识库")
    return kb


# ===== 请求/响应模型 =====
class RagAskRequest(BaseModel):
    question: str
    # kb_id 为 None 表示「全部知识库」——普通用户=自己拥有的所有库，管理员=全系统。
    # 传具体 id 则只在该单库问答（原有行为）。
    kb_id: int | None = None


class IngestRequest(BaseModel):
    file_path: str
    kb_id: int


class LoginRequest(BaseModel):
    username: str
    password: str


class RecoveryItem(BaseModel):
    question: str
    answer: str


class RegisterRequest(BaseModel):
    username: str
    password: str
    display_name: str = ""
    recovery_items: list[RecoveryItem] = []


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str = "user"
    display_name: str = ""


class UpdateMeRequest(BaseModel):
    display_name: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class ResetPasswordRequest(BaseModel):
    new_password: str
    force_change: bool = True


class RecoveryQuestionsRequest(BaseModel):
    username: str


class RecoveryResetPasswordRequest(BaseModel):
    username: str
    answers: list[str]
    new_password: str


class SetRecoveryQuestionsRequest(BaseModel):
    recovery_items: list[RecoveryItem]


class CreateKbRequest(BaseModel):
    name: str
    description: str = ""


class UpdateKbRequest(BaseModel):
    name: str
    description: str = ""


class UpdateQuotaRequest(BaseModel):
    quota: int


class QuotaRequestCreate(BaseModel):
    amount: int
    reason: str = ""


class CreateSessionRequest(BaseModel):
    title: str = "未命名会话"


class UpdateSessionRequest(BaseModel):
    # 二选一：改名传 title；切换收藏传 toggle_favorite=true
    title: Optional[str] = None
    toggle_favorite: bool = False


class AppendMessageRequest(BaseModel):
    role: str
    content: str
    sources: list = []
    # 研判结果（assistant 消息可带）：{answerable, reason, confidence}。存库以便刷新会话后仍能显示徽标。
    verdict: dict | None = None


class RetrievalConfigBody(BaseModel):
    # 检索配置字段（三级 scope 共用）。范围校验避免存入非法值。
    top_k: int = Field(ge=1, le=20)
    max_distance: float = Field(ge=0.0, le=1.0)
    judge_enabled: bool = False
    answer_prompt: str = ""
    # 仅 tenant 级有意义：多/全库查询用哪份配置（'system'/'tenant'）。其它级忽略。
    multi_scope: str | None = None


class CreateTopicRequest(BaseModel):
    kb_id: int
    name: str


class UpdateTopicRequest(BaseModel):
    name: str


class CreateFeedbackRequest(BaseModel):
    title: str
    content: str = ""


class AdminFeedbackUpdateRequest(BaseModel):
    status: str
    reply: str = ""


class CreateNotificationRequest(BaseModel):
    title: str
    content: str = ""
    send_to_all: bool = True
    user_ids: list[int] = []


class ModelUsageQuery(BaseModel):
    days: int = Field(default=7, ge=1, le=90)
    user_id: int | None = None
    model_type: str | None = None


# ===== 认证与用户管理接口 =====
@app.post("/auth/login")
def login(request: LoginRequest):
    """账密登录：成功返回 JWT 令牌与用户信息。登录后确保用户至少有一个默认知识库。"""
    try:
        user = user_service.authenticate(request.username, request.password)
    except user_service.AccountLocked as exc:
        raise HTTPException(status_code=423, detail=str(exc))
    if user is None:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    # 保证用户一进来就有库可用（幂等）。
    try:
        kb_service.ensure_default_kb(user["id"])
    except Exception:
        pass
    token = auth_service.create_access_token(user)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": user,
    }


@app.post("/auth/register")
def register(request: RegisterRequest):
    """自助注册（公开，无需登录）：只能注册普通用户。
    成功后自动建默认知识库并返回登录令牌（前端可直接进入工作台）。"""
    try:
        user = user_service.register_user(
            username=request.username,
            password=request.password,
            display_name=request.display_name,
            recovery_items=[item.model_dump() for item in request.recovery_items],
        )
    except ValueError as exc:
        # 校验失败或用户名已存在
        raise HTTPException(status_code=400, detail=str(exc))
    try:
        kb_service.ensure_default_kb(user["id"])
    except Exception:
        pass
    token = auth_service.create_access_token(user)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": user,
    }


@app.get("/auth/me")
def read_me(current_user: dict = Depends(get_current_user)):
    return current_user


@app.patch("/auth/me")
def update_me(request: UpdateMeRequest, current_user: dict = Depends(get_current_user)):
    """当前用户修改个人资料（目前支持显示名）。"""
    try:
        return user_service.update_profile(current_user["id"], request.display_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/auth/password/change")
def change_password(request: ChangePasswordRequest, current_user: dict = Depends(get_current_user)):
    """当前用户修改自己的密码。"""
    try:
        return user_service.change_password(
            current_user["id"],
            request.old_password,
            request.new_password,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.put("/auth/recovery/questions")
def set_recovery_questions(request: SetRecoveryQuestionsRequest, current_user: dict = Depends(get_current_user)):
    """当前用户设置/更新找回密码问题。"""
    try:
        return user_service.set_recovery_questions(
            current_user["id"],
            [item.model_dump() for item in request.recovery_items],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/auth/recovery/questions")
def recovery_questions(request: RecoveryQuestionsRequest):
    """忘记密码第一步：按用户名读取找回问题。"""
    try:
        return {"questions": user_service.get_recovery_questions(request.username)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/auth/recovery/reset-password")
def recovery_reset_password(request: RecoveryResetPasswordRequest):
    """忘记密码第二步：回答问题后自助重置密码。"""
    try:
        user = user_service.reset_password_by_recovery(
            request.username,
            request.answers,
            request.new_password,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"reset": True, "user": user}


@app.get("/users")
def list_users(_: dict = Depends(require_admin)):
    return {"users": user_service.list_all()}


@app.post("/users")
def create_user(request: CreateUserRequest, _: dict = Depends(require_admin)):
    """新建用户（仅管理员）。同时为新用户创建一个默认知识库。"""
    try:
        user = user_service.create_user(
            username=request.username,
            password=request.password,
            role=request.role,
            display_name=request.display_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    try:
        kb_service.ensure_default_kb(user["id"])
    except Exception:
        pass
    return user


@app.post("/users/{user_id}/password-reset")
def reset_user_password(user_id: int, request: ResetPasswordRequest, current_user: dict = Depends(require_admin)):
    """管理员重置其他用户密码；重置后默认要求用户下次登录先改密。"""
    if current_user.get("id") == user_id:
        raise HTTPException(status_code=400, detail="请在个人中心修改自己的密码")
    if user_service.get_by_id(user_id) is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    try:
        return user_service.reset_password(
            user_id,
            request.new_password,
            force_password_change=request.force_change,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.delete("/users/{user_id}")
def delete_user(user_id: int, current_user: dict = Depends(require_admin)):
    """删除用户（仅管理员）。不允许删除自己，也不允许删掉最后一个管理员。"""
    if current_user.get("id") == user_id:
        raise HTTPException(status_code=400, detail="不能删除当前登录的自己")
    target = user_service.get_by_id(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if target.get("role") == user_service.ROLE_ADMIN and user_service.count(user_service.ROLE_ADMIN) <= 1:
        raise HTTPException(status_code=400, detail="不能删除最后一个管理员")
    # 级联删除该用户的所有知识库（文件目录 + 向量 + 元数据）。
    for kb in kb_service.list_by_owner(user_id):
        _purge_kb(kb["id"])
    user_service.delete(user_id)
    return {"id": user_id, "deleted": True}


@app.patch("/users/{user_id}/quota")
def update_user_quota(user_id: int, request: UpdateQuotaRequest, _: dict = Depends(require_admin)):
    """调整某用户的知识库配额上限（仅管理员）。
    新配额不得低于该用户当前已用的知识库数量，否则 400。"""
    target = user_service.get_by_id(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    used = kb_service.count_by_owner(user_id)
    if request.quota < used:
        raise HTTPException(
            status_code=400,
            detail=f"配额不能低于该用户已用的知识库数（当前已用 {used}）",
        )
    try:
        new_quota = user_service.set_quota(user_id, request.quota)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"id": user_id, "kb_quota": new_quota, "used": used}


# ===== 知识库管理 =====
def _purge_kb(kb_id: int) -> None:
    """彻底清除一个知识库：向量片段、元数据、物理文件目录、知识库记录本身。"""
    import shutil
    try:
        knowledge_base_service.delete_kb(kb_id)
    except Exception:
        pass
    try:
        metadata_service.delete_by_kb(kb_id)
    except Exception:
        pass
    try:
        directory = kb_documents_dir(kb_id)
        shutil.rmtree(directory, ignore_errors=True)
    except Exception:
        pass
    kb_service.delete(kb_id)


@app.get("/kbs")
def list_kbs(all: bool = Query(False), current_user: dict = Depends(get_current_user)):
    """知识库列表：默认返回自己的；管理员传 ?all=true 返回全部。"""
    is_admin = current_user.get("role") == user_service.ROLE_ADMIN
    if all and is_admin:
        kbs = kb_service.list_all()
    else:
        kbs = kb_service.list_by_owner(current_user["id"])
    return {
        "kbs": kbs,
        "quota": current_user.get("kb_quota", 0),
        "used": kb_service.count_by_owner(current_user["id"]),
    }


@app.post("/kbs")
def create_kb(request: CreateKbRequest, current_user: dict = Depends(get_current_user)):
    """新建知识库（受配额限制；管理员配额很大等同不限）。"""
    try:
        kb = kb_service.create_kb(
            owner_id=current_user["id"],
            name=request.name,
            description=request.description,
        )
    except QuotaExceededError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return kb


@app.put("/kbs/{kb_id}")
def update_kb(kb_id: int, request: UpdateKbRequest, current_user: dict = Depends(get_current_user)):
    """更新知识库名称/描述（属主或管理员）。"""
    require_kb_access(kb_id, current_user)
    try:
        kb = kb_service.update_kb(kb_id, request.name, request.description)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if kb is None:
        raise HTTPException(status_code=404, detail="知识库不存在")
    return kb


@app.delete("/kbs/{kb_id}")
def delete_kb(kb_id: int, current_user: dict = Depends(get_current_user)):
    """删除知识库（属主或管理员）。连带清除其文件、向量、元数据。"""
    require_kb_access(kb_id, current_user)
    _purge_kb(kb_id)
    return {"id": kb_id, "deleted": True}


# ===== 配额申请 =====
@app.post("/kb-requests")
def submit_quota_request(request: QuotaRequestCreate, current_user: dict = Depends(get_current_user)):
    """提交额外知识库配额申请。"""
    try:
        req = quota_service.create_request(current_user["id"], request.amount, request.reason)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return req


@app.get("/kb-requests/mine")
def my_quota_requests(current_user: dict = Depends(get_current_user)):
    """我的申请记录。"""
    return {"requests": quota_service.list_by_user(current_user["id"])}


@app.get("/kb-requests/pending")
def pending_quota_requests(_: dict = Depends(require_admin)):
    """待审批申请列表（仅管理员）。"""
    return {"requests": quota_service.list_pending()}


@app.post("/kb-requests/{request_id}/approve")
def approve_quota_request(request_id: int, current_user: dict = Depends(require_admin)):
    """通过申请（仅管理员）：申请人配额相应增加。"""
    try:
        return quota_service.approve(request_id, current_user["id"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/kb-requests/{request_id}/reject")
def reject_quota_request(request_id: int, current_user: dict = Depends(require_admin)):
    """驳回申请（仅管理员）。"""
    try:
        return quota_service.reject(request_id, current_user["id"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ===== 问题反馈 =====
_ALLOWED_FEEDBACK_IMAGE_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
_ALLOWED_FEEDBACK_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def _feedback_attachment_dir(ticket_id: int) -> Path:
    root = Path(FEEDBACK_ATTACHMENT_DIR)
    path = root / str(ticket_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _ensure_feedback_access(ticket_id: int, current_user: dict) -> dict:
    ticket = feedback_service.get(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="反馈不存在")
    is_admin = current_user.get("role") == user_service.ROLE_ADMIN
    if not is_admin and ticket["user_id"] != current_user.get("id"):
        raise HTTPException(status_code=404, detail="反馈不存在或无权访问")
    return ticket


@app.post("/feedback")
def create_feedback(request: CreateFeedbackRequest, current_user: dict = Depends(get_current_user)):
    """当前用户提交问题反馈。"""
    try:
        return feedback_service.create_ticket(current_user["id"], request.title, request.content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/feedback/mine")
def my_feedback(current_user: dict = Depends(get_current_user)):
    """当前用户查看自己的反馈历史。"""
    return {"tickets": feedback_service.list_by_user(current_user["id"])}


@app.post("/feedback/{ticket_id}/close")
def close_feedback(ticket_id: int, current_user: dict = Depends(get_current_user)):
    """反馈所属用户确认关闭。非本人反馈按不存在处理。"""
    ticket = feedback_service.close_ticket(ticket_id, current_user["id"])
    if ticket is None:
        raise HTTPException(status_code=404, detail="反馈不存在或无权访问")
    return ticket


@app.post("/feedback/{ticket_id}/attachments")
def upload_feedback_attachments(
    ticket_id: int,
    files: list[UploadFile] = File(...),
    current_user: dict = Depends(get_current_user),
):
    """给自己的反馈上传截图附件。管理员不代传用户反馈截图。"""
    ticket = _ensure_feedback_access(ticket_id, current_user)
    if ticket["user_id"] != current_user.get("id"):
        raise HTTPException(status_code=403, detail="只能给自己的反馈上传截图")
    if not files:
        raise HTTPException(status_code=400, detail="请选择截图文件")
    current_count = len(ticket.get("attachments") or [])
    if current_count + len(files) > FEEDBACK_ATTACHMENT_MAX_COUNT:
        raise HTTPException(status_code=400, detail=f"每条反馈最多上传 {FEEDBACK_ATTACHMENT_MAX_COUNT} 张截图")

    saved = []
    max_bytes = FEEDBACK_ATTACHMENT_MAX_MB * 1024 * 1024
    for file in files:
        original_name = Path(file.filename or "screenshot").name
        suffix = Path(original_name).suffix.lower()
        content_type = (file.content_type or "").lower()
        if suffix not in _ALLOWED_FEEDBACK_IMAGE_EXTS or content_type not in _ALLOWED_FEEDBACK_IMAGE_TYPES:
            raise HTTPException(status_code=400, detail="仅支持 png/jpg/jpeg/webp/gif 截图")
        content = file.file.read()
        if len(content) > max_bytes:
            raise HTTPException(status_code=400, detail=f"单张截图不能超过 {FEEDBACK_ATTACHMENT_MAX_MB} MB")
        stored_name = f"{uuid.uuid4().hex}{_ALLOWED_FEEDBACK_IMAGE_TYPES[content_type]}"
        path = _feedback_attachment_dir(ticket_id) / stored_name
        path.write_bytes(content)
        try:
            saved.append(
                feedback_service.add_attachment(
                    ticket_id=ticket_id,
                    original_name=original_name,
                    stored_name=stored_name,
                    content_type=content_type,
                    size=len(content),
                )
            )
        except ValueError as exc:
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass
            raise HTTPException(status_code=400, detail=str(exc))
    return {"attachments": saved}


@app.get("/feedback/{ticket_id}/attachments/{attachment_id}")
def download_feedback_attachment(
    ticket_id: int,
    attachment_id: int,
    current_user: dict = Depends(get_current_user),
):
    """鉴权下载反馈截图：普通用户只能看自己的反馈，管理员可看全部。"""
    _ensure_feedback_access(ticket_id, current_user)
    attachment = feedback_service.get_attachment_record(attachment_id)
    if attachment is None or attachment.get("ticket_id") != ticket_id:
        raise HTTPException(status_code=404, detail="截图不存在")
    path = Path(FEEDBACK_ATTACHMENT_DIR) / str(ticket_id) / attachment.get("stored_name", "")
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="截图文件不存在")
    return FileResponse(
        path,
        media_type=attachment.get("content_type") or "application/octet-stream",
        filename=attachment.get("original_name") or path.name,
    )


@app.get("/feedback/admin")
def admin_feedback(status: str = Query("all"), _: dict = Depends(require_admin)):
    """管理员查看全部反馈，可按状态筛选。"""
    try:
        return {"tickets": feedback_service.list_all(status)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.patch("/feedback/admin/{ticket_id}")
def update_feedback_by_admin(
    ticket_id: int,
    request: AdminFeedbackUpdateRequest,
    current_user: dict = Depends(require_admin),
):
    """管理员更新反馈处理状态与回复。"""
    try:
        return feedback_service.admin_update(
            ticket_id,
            request.status,
            request.reply,
            current_user["id"],
        )
    except ValueError as exc:
        detail = str(exc)
        if "不存在" in detail:
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)


# ===== 通知与消息中心 =====
@app.get("/notifications/mine")
def my_notifications(
    include_closed: bool = Query(False),
    current_user: dict = Depends(get_current_user),
):
    """当前用户的通知列表。默认不包含已关闭通知。"""
    return {"notifications": notification_service.list_for_user(current_user["id"], include_closed)}


@app.get("/notifications/unread-count")
def unread_notification_count(current_user: dict = Depends(get_current_user)):
    """当前用户未读通知数量。"""
    return {"count": notification_service.count_unread(current_user["id"])}


@app.post("/notifications/{notification_id}/read")
def mark_notification_read(notification_id: int, current_user: dict = Depends(get_current_user)):
    """当前用户确认已读某条通知。"""
    notification = notification_service.mark_read(notification_id, current_user["id"])
    if notification is None:
        raise HTTPException(status_code=404, detail="通知不存在或无权访问")
    return notification


@app.post("/notifications/{notification_id}/close")
def close_notification(notification_id: int, current_user: dict = Depends(get_current_user)):
    """当前用户关闭某条通知。"""
    notification = notification_service.close(notification_id, current_user["id"])
    if notification is None:
        raise HTTPException(status_code=404, detail="通知不存在或无权访问")
    return notification


@app.post("/notifications/admin")
def create_notification(request: CreateNotificationRequest, current_user: dict = Depends(require_admin)):
    """管理员下发通知：可发给全部用户或指定用户。"""
    if request.send_to_all:
        target_type = notification_service.TARGET_ALL
        user_ids = [u["id"] for u in user_service.list_all()]
    else:
        target_type = notification_service.TARGET_USERS
        existing = {u["id"] for u in user_service.list_all()}
        user_ids = [uid for uid in request.user_ids if uid in existing]
    try:
        return notification_service.create_notification(
            created_by=current_user["id"],
            title=request.title,
            content=request.content,
            target_user_ids=user_ids,
            target_type=target_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/notifications/admin")
def admin_notifications(_: dict = Depends(require_admin)):
    """管理员查看通知下发历史与收件统计。"""
    return {"notifications": notification_service.list_admin()}


# ===== 模型用量监控（仅管理员）=====
def _user_lookup() -> dict[int, dict]:
    return {u["id"]: u for u in user_service.list_all()}


def _attach_user(row: dict, users: dict[int, dict]) -> dict:
    item = dict(row)
    user = users.get(item.get("user_id"))
    item["username"] = user.get("username") if user else ""
    item["display_name"] = user.get("display_name") if user else ""
    return item


def _validate_model_type(model_type: str | None) -> str | None:
    if not model_type:
        return None
    value = model_type.strip()
    if value not in model_usage_service.VALID_MODEL_TYPES:
        raise HTTPException(status_code=400, detail="未知模型类型")
    return value


@app.get("/admin/model-usage/summary")
def model_usage_summary(
    days: int = Query(7, ge=1, le=90),
    user_id: int | None = Query(None),
    model_type: str | None = Query(None),
    _: dict = Depends(require_admin),
):
    """管理员查看模型调用聚合统计：token、调用次数、延迟、失败率。"""
    summary = model_usage_service.summarize(
        days=days,
        user_id=user_id,
        model_type=_validate_model_type(model_type),
    )
    users = _user_lookup()
    summary["by_user"] = [_attach_user(row, users) for row in summary.get("by_user", [])]
    summary["alerts"] = [_attach_user(row, users) for row in model_usage_service.list_alerts(days=min(days, 1))]
    return summary


@app.get("/admin/model-usage/records")
def model_usage_records(
    days: int = Query(7, ge=1, le=90),
    user_id: int | None = Query(None),
    model_type: str | None = Query(None),
    success: bool | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    _: dict = Depends(require_admin),
):
    """管理员查看最近模型调用明细。"""
    users = _user_lookup()
    records = model_usage_service.list_records(
        days=days,
        user_id=user_id,
        model_type=_validate_model_type(model_type),
        success=success,
        limit=limit,
    )
    return {"records": [_attach_user(row, users) for row in records]}


@app.get("/admin/model-usage/alerts")
def model_usage_alerts(
    days: int = Query(1, ge=1, le=30),
    _: dict = Depends(require_admin),
):
    """管理员查看模型调用异常告警。"""
    users = _user_lookup()
    return {"alerts": [_attach_user(row, users) for row in model_usage_service.list_alerts(days=days)]}


# ===== 业务接口（均带 kb 维度 + 归属校验）=====
@app.get("/")
def read_root():
    return {"message": "Enterprise RAG API is running"}


@app.get("/documents")
def list_documents(kb_id: int = Query(...), current_user: dict = Depends(get_current_user)):
    """指定知识库的文档列表：以该库目录下的真实文件为准，挂上 MySQL 元数据。"""
    require_kb_access(kb_id, current_user)
    directory = kb_documents_dir(kb_id)
    file_paths = list_text_files(str(directory))
    meta_map = metadata_service.list_all(kb_id)

    documents = []
    for path in file_paths:
        filename = Path(path).name
        meta = meta_map.get(filename)
        documents.append(
            {
                "filename": filename,
                "topic": meta["topic"] if meta else "未分类",
                "description": meta["description"] if meta else "",
                "status": meta["status"] if meta else "就绪",
                "chunk_count": meta["chunk_count"] if meta else 0,
                "error": meta["error"] if meta else "",
                "uploaded_at": meta["uploaded_at"] if meta else "—",
            }
        )
    return {"documents": documents}


@app.get("/stats")
def get_stats(kb_id: int = Query(...), current_user: dict = Depends(get_current_user)):
    """指定知识库的概览统计。"""
    require_kb_access(kb_id, current_user)
    return knowledge_base_service.stats(kb_id)


@app.post("/maintenance/reconcile")
def reconcile_knowledge_base(kb_id: int = Query(...), current_user: dict = Depends(get_current_user)):
    """数据对账：清理指定知识库里"文件已删除但向量仍残留"的僵尸片段。"""
    require_kb_access(kb_id, current_user)
    directory = kb_documents_dir(kb_id)
    return knowledge_base_service.reconcile(kb_id, str(directory))


@app.post("/maintenance/reload")
def reload_knowledge_base(kb_id: int = Query(...), current_user: dict = Depends(get_current_user)):
    """重载向量库：丢弃缓存并重连，加载磁盘最新数据。返回当前知识库的片段数。"""
    require_kb_access(kb_id, current_user)
    return knowledge_base_service.reload_collection(kb_id)


@app.post("/maintenance/rechunk-docx")
def rechunk_docx(kb_id: int = Query(...), current_user: dict = Depends(get_current_user)):
    """统一存量 DOCX 切分：按当前解析/段落切分策略重建该库下所有 Word 文档。"""
    require_kb_access(kb_id, current_user)
    directory = kb_documents_dir(kb_id)
    with model_usage_service.usage_context(
        user_id=current_user.get("id"),
        kb_id=kb_id,
        request_id=uuid.uuid4().hex,
        operation="rechunk_docx",
    ):
        return knowledge_base_service.rechunk_docx_documents(kb_id, str(directory))


def _ingest_in_background(
    file_path: str,
    kb_id: int,
    filename: str,
    user_id: int | None = None,
) -> None:
    """后台执行「解析 + 向量化 + 写入向量库」，并把结果回写到元数据状态。

    这是解决大文件上传 60 秒超时的核心：耗时的向量化不再阻塞上传请求，
    上传接口存完盘即返回，这里在响应之后的后台线程里慢慢跑。

    结果通过 metadata_service 的 status 字段对外暴露，前端轮询文档列表即可感知：
      - 处理中：入库进行中（上传接口已预置）
      - 就绪  ：入库成功，附 chunk_count
      - 失败  ：解析/向量化异常或内容为空，附 error 原因；磁盘文件保留，便于排查/重传
    """
    try:
        with model_usage_service.usage_context(
            user_id=user_id,
            kb_id=kb_id,
            request_id=uuid.uuid4().hex,
            operation="document_ingest",
        ):
            document = create_document_from_file(document_id=0, file_path=file_path)
            ingest_result = knowledge_base_service.ingest_document(document, kb_id=kb_id)
    except Exception as exc:
        # 保留文件（不 unlink），仅把失败原因写进元数据，前端可见、可手动删除重传。
        try:
            metadata_service.upsert(
                kb_id=kb_id, filename=filename, status="失败",
                error=f"文档解析失败，未入库：{exc}",
            )
        except Exception:
            pass
        return

    if ingest_result["chunk_count"] == 0:
        try:
            metadata_service.upsert(
                kb_id=kb_id, filename=filename, status="失败",
                error="文档内容为空或无法提取有效文本，未入库",
            )
        except Exception:
            pass
        return

    try:
        metadata_service.upsert(
            kb_id=kb_id, filename=filename, status="就绪",
            chunk_count=ingest_result["chunk_count"], error="",
        )
    except Exception:
        pass


@app.post("/documents/upload")
def upload_document(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    kb_id: int = Form(...),
    topic: str = Form("未分类"),
    description: str = Form(""),
    current_user: dict = Depends(get_current_user),
):
    """上传文档到指定知识库。

    存盘后立即返回（秒级），把耗时的解析 / 向量化 / 入库交给后台任务执行，
    避免大文件因同步等待整条流水线而触发前端 HTTP 超时。
    前端通过轮询 GET /documents 的 status 感知「处理中 → 就绪/失败」。
    """
    require_kb_access(kb_id, current_user)

    suffix = Path(file.filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
        )
    documents_dir = kb_documents_dir(kb_id)
    file_path = documents_dir / file.filename
    content = file.file.read()
    file_path.write_bytes(content)

    # 先把元数据置为「处理中」，让列表立刻能看到这条记录及其状态。
    try:
        metadata_service.upsert(
            kb_id=kb_id,
            filename=file.filename,
            topic=topic,
            description=description,
            status="处理中",
            chunk_count=0,
            error="",
        )
    except Exception:
        pass

    # 注册后台入库任务：在本响应返回后同进程执行，不阻塞上传请求。
    background.add_task(_ingest_in_background, str(file_path), kb_id, file.filename, current_user.get("id"))

    return {
        "filename": file.filename,
        "file_path": str(file_path),
        "status": "处理中",
    }


@app.post("/documents/ingest")
def ingest_document(request: IngestRequest, current_user: dict = Depends(get_current_user)):
    """把一个已存在的文件入库到指定知识库（不上传，只入库）。"""
    require_kb_access(request.kb_id, current_user)
    if not request.file_path.strip():
        raise HTTPException(status_code=400, detail="File path cannot be empty")
    if not Path(request.file_path).exists():
        raise HTTPException(status_code=404, detail="File not found")

    with model_usage_service.usage_context(
        user_id=current_user.get("id"),
        kb_id=request.kb_id,
        request_id=uuid.uuid4().hex,
        operation="document_ingest",
    ):
        document = create_document_from_file(document_id=0, file_path=request.file_path)
        result = knowledge_base_service.ingest_document(document, kb_id=request.kb_id)
    try:
        metadata_service.upsert(
            kb_id=request.kb_id,
            filename=result["filename"],
            status="就绪",
            chunk_count=result["chunk_count"],
        )
    except Exception:
        pass
    return {"filename": result["filename"], "chunk_count": result["chunk_count"]}


@app.delete("/documents/{filename}")
def delete_document(filename: str, kb_id: int = Query(...), current_user: dict = Depends(get_current_user)):
    """从指定知识库删除某个文档（文件 + 向量 + 元数据）。"""
    require_kb_access(kb_id, current_user)
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
        )
    file_path = kb_documents_dir(kb_id) / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    file_path.unlink()

    knowledge_base_service.delete_document(filename, kb_id=kb_id)
    try:
        metadata_service.delete(kb_id, filename)
    except Exception:
        pass

    return {"filename": filename, "deleted": True}


# ===== 文档主题分类（按知识库隔离：属主或管理员可增删改查）=====
@app.get("/topics")
def list_topics(kb_id: int = Query(...), current_user: dict = Depends(get_current_user)):
    """列出某知识库的主题分类（属主或管理员）。"""
    require_kb_access(kb_id, current_user)
    return {"topics": topic_service.list_topics(kb_id)}


@app.post("/topics")
def create_topic(request: CreateTopicRequest, current_user: dict = Depends(get_current_user)):
    """在某知识库下新增分类（属主或管理员；名称唯一、幂等）。"""
    require_kb_access(request.kb_id, current_user)
    try:
        return topic_service.add_topic(request.kb_id, request.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.patch("/topics/{topic_id}")
def update_topic(
    topic_id: int,
    request: UpdateTopicRequest,
    current_user: dict = Depends(get_current_user),
):
    """重命名分类（属主或管理员），并联动更新本库下用旧分类名的文档。"""
    topic = topic_service.get(topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="分类不存在")
    require_kb_access(topic["kb_id"], current_user)
    try:
        result = topic_service.rename_topic(topic_id, request.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if result is None:
        raise HTTPException(status_code=404, detail="分类不存在")
    # 联动：把本库下用旧分类名的文档 topic 同步改成新名。
    try:
        metadata_service.rename_topic_in_kb(
            result["kb_id"], result["old_name"], result["new_name"]
        )
    except Exception:
        pass
    return {"id": topic_id, "kb_id": result["kb_id"], "name": result["new_name"]}


@app.delete("/topics/{topic_id}")
def delete_topic(topic_id: int, current_user: dict = Depends(get_current_user)):
    """删除分类（属主或管理员）。已上传文档保留其原分类名字符串。"""
    topic = topic_service.get(topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="分类不存在")
    require_kb_access(topic["kb_id"], current_user)
    topic_service.delete_topic(topic_id)
    return {"id": topic_id, "deleted": True}


# ===== 聊天会话（按用户归属，服务端持久化）=====
@app.get("/sessions")
def list_sessions(current_user: dict = Depends(get_current_user)):
    """当前用户的全部会话（最近更新在前）。"""
    return {"sessions": session_service.list_sessions(current_user["id"])}


@app.post("/sessions")
def create_session(request: CreateSessionRequest, current_user: dict = Depends(get_current_user)):
    """为当前用户新建一个会话。"""
    return session_service.create_session(current_user["id"], request.title)


@app.patch("/sessions/{session_id}")
def update_session(
    session_id: int,
    request: UpdateSessionRequest,
    current_user: dict = Depends(get_current_user),
):
    """更新会话：改名（传 title）或切换收藏（toggle_favorite=true）。非本人会话 404。"""
    if request.toggle_favorite:
        result = session_service.toggle_favorite(session_id, current_user["id"])
    elif request.title is not None:
        result = session_service.rename_session(session_id, current_user["id"], request.title)
    else:
        raise HTTPException(status_code=400, detail="无更新内容：请提供 title 或 toggle_favorite")
    if result is None:
        raise HTTPException(status_code=404, detail="会话不存在或无权访问")
    return result


@app.delete("/sessions/{session_id}")
def delete_session(session_id: int, current_user: dict = Depends(get_current_user)):
    """删除会话及其消息。非本人会话 404。"""
    ok = session_service.delete_session(session_id, current_user["id"])
    if not ok:
        raise HTTPException(status_code=404, detail="会话不存在或无权访问")
    return {"id": session_id, "deleted": True}


@app.get("/sessions/{session_id}/messages")
def list_session_messages(session_id: int, current_user: dict = Depends(get_current_user)):
    """会话内的消息列表（时间正序）。非本人会话 404。"""
    messages = session_service.list_messages(session_id, current_user["id"])
    if messages is None:
        raise HTTPException(status_code=404, detail="会话不存在或无权访问")
    return {"messages": messages}


@app.post("/sessions/{session_id}/messages")
def append_session_message(
    session_id: int,
    request: AppendMessageRequest,
    current_user: dict = Depends(get_current_user),
):
    """向会话追加一条消息（user 或 assistant）。非本人会话 404。"""
    result = session_service.append_message(
        session_id=session_id,
        user_id=current_user["id"],
        role=request.role,
        content=request.content,
        sources=request.sources,
        verdict=request.verdict,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="会话不存在或无权访问")
    return result


@app.post("/rag/ask")
def ask_rag(request: RagAskRequest, current_user: dict = Depends(get_current_user)):
    """知识库问答。

    kb_id 指定单库：校验访问权后只在该库检索（原有行为）。
    kb_id 为 None（「全部知识库」）：按角色限定检索范围，严守多租户隔离——
    - 普通用户：只在「自己拥有的所有库」范围内检索，绝不会召回他人的库；
    - 管理员：真全库跨库检索。
    """
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    owner_id = current_user.get("id")
    # 解析该次问答实际生效的检索参数（三级配置：kb→tenant→system→硬默认）。
    # 显式传给 answer_from_knowledge_base，绕过 config.RAG_* 的 import-time 常量快照——
    # 这是「在线改配置能生效」的关键（rag_service 若只读模块常量，改库不会生效）。
    cfg = retrieval_config_service.resolve_effective(owner_id=owner_id, kb_id=request.kb_id)

    request_id = uuid.uuid4().hex
    with model_usage_service.usage_context(
        user_id=owner_id,
        kb_id=request.kb_id,
        request_id=request_id,
        operation="rag_ask",
    ):
        if request.kb_id is not None:
            # 单库：沿用原有归属校验 + 单库检索。
            require_kb_access(request.kb_id, current_user)
            result = answer_from_knowledge_base(
                question=request.question,
                top_k=cfg["top_k"],
                max_distance=cfg["max_distance"],
                judge_enabled=cfg["judge_enabled"],
                answer_prompt=cfg["answer_prompt"],
                kb_id=request.kb_id,
            )
        else:
            # 全部：按角色限定范围。
            is_admin = current_user.get("role") == user_service.ROLE_ADMIN
            if is_admin:
                # 管理员真全库（kb_id/kb_ids 都不传 → 不过滤）。
                result = answer_from_knowledge_base(
                    question=request.question,
                    top_k=cfg["top_k"],
                    max_distance=cfg["max_distance"],
                    judge_enabled=cfg["judge_enabled"],
                    answer_prompt=cfg["answer_prompt"],
                )
            else:
                # 普通用户：把范围限定到自己拥有的所有库 —— 天然隔离，不泄露他人数据。
                my_kbs = kb_service.list_by_owner(owner_id)
                my_ids = [kb["id"] for kb in my_kbs]
                result = answer_from_knowledge_base(
                    question=request.question,
                    top_k=cfg["top_k"],
                    max_distance=cfg["max_distance"],
                    judge_enabled=cfg["judge_enabled"],
                    answer_prompt=cfg["answer_prompt"],
                    kb_ids=my_ids,
                )

    return {
        "question": request.question,
        "answer": result["answer"],
        "sources": result["sources"],
        # 研判结果（防幻觉）：answerable=false 表示拒答，reason 说明原因，confidence 可信度。
        # 供前端展示拒答/低可信徽标。研判关闭时上层也会给出默认值（answerable=true）。
        "answerable": result.get("answerable", True),
        "reason": result.get("reason", ""),
        "confidence": result.get("confidence", "high"),
    }


# ===== 检索配置 =====
# 三级检索参数（系统/租户/知识库）在线读写。见 retrieval_config_service。
def _authorize_config(scope: str, kb_id: int | None, current_user: dict) -> int | None:
    """按 scope 做鉴权，返回该配置行归属的 owner_id（system→None）。

    - system：仅管理员可读写（配置页也只对管理员显示该分区）。
    - tenant：当前用户本人。
    - kb    ：走 require_kb_access（属主或管理员），并返回该库属主 id 存入配置行。
    """
    if scope == retrieval_config_service.SCOPE_SYSTEM:
        if current_user.get("role") != user_service.ROLE_ADMIN:
            raise HTTPException(status_code=403, detail="需要管理员权限")
        return None
    if scope == retrieval_config_service.SCOPE_TENANT:
        return current_user.get("id")
    if scope == retrieval_config_service.SCOPE_KB:
        if kb_id is None:
            raise HTTPException(status_code=400, detail="kb scope 需要 kb_id")
        kb = require_kb_access(kb_id, current_user)  # 隔离红线：非属主/非管理员 403
        return kb["owner_id"]
    raise HTTPException(status_code=400, detail=f"未知 scope：{scope}")


@app.get("/config/retrieval")
def get_retrieval_config(
    scope: str = Query("system"),
    kb_id: int | None = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """读取某级检索配置（含继承/兜底值 + inherited 标记，供前端展示当前生效值）。"""
    owner_id = _authorize_config(scope, kb_id, current_user)
    return retrieval_config_service.get_view(scope, owner_id, kb_id)


@app.put("/config/retrieval")
def put_retrieval_config(
    body: RetrievalConfigBody,
    scope: str = Query("system"),
    kb_id: int | None = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """写入/更新某级检索配置。鉴权同读；系统级仅管理员、kb 级走隔离校验。"""
    owner_id = _authorize_config(scope, kb_id, current_user)
    try:
        if scope == retrieval_config_service.SCOPE_SYSTEM:
            row = retrieval_config_service.set_system(
                body.top_k, body.max_distance, body.judge_enabled, body.answer_prompt
            )
        elif scope == retrieval_config_service.SCOPE_TENANT:
            row = retrieval_config_service.set_tenant(
                owner_id, body.top_k, body.max_distance,
                body.judge_enabled, body.answer_prompt, body.multi_scope,
            )
        else:  # kb
            row = retrieval_config_service.set_kb(
                kb_id, owner_id, body.top_k, body.max_distance,
                body.judge_enabled, body.answer_prompt,
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    from app.services.retrieval_config_service import _public
    return _public(row, inherited=False)


@app.delete("/config/retrieval")
def delete_retrieval_config(
    scope: str = Query("kb"),
    kb_id: int | None = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """清除某知识库的独立配置，回落继承（仅支持 kb scope）。"""
    if scope != retrieval_config_service.SCOPE_KB:
        raise HTTPException(status_code=400, detail="仅支持清除 kb 级配置")
    _authorize_config(scope, kb_id, current_user)
    retrieval_config_service.clear_kb(kb_id)
    return retrieval_config_service.get_view(scope, None, kb_id)
