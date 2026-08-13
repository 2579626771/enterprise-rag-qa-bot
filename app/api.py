from fastapi import FastAPI,HTTPException,UploadFile,File,Form,Depends,Query,BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pathlib import Path
from typing import Optional
from pydantic import BaseModel
from app.services.rag_service import answer_from_knowledge_base
from app.services.document_service import (
    list_text_files,
    create_document_from_file,
    kb_documents_dir,
    SUPPORTED_EXTENSIONS,
)
from app.services import knowledge_base_service
from app.services import metadata_service
from app.services import user_service
from app.services import kb_service
from app.services import quota_service
from app.services import auth_service
from app.services.auth_service import TokenError
from app.services.kb_service import QuotaExceededError
from app.config import RAG_TOP_K
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
    kb_id: int


class IngestRequest(BaseModel):
    file_path: str
    kb_id: int


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    password: str
    display_name: str = ""


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str = "user"
    display_name: str = ""


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


# ===== 认证与用户管理接口 =====
@app.post("/auth/login")
def login(request: LoginRequest):
    """账密登录：成功返回 JWT 令牌与用户信息。登录后确保用户至少有一个默认知识库。"""
    user = user_service.verify_password(request.username, request.password)
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


def _ingest_in_background(
    file_path: str,
    kb_id: int,
    filename: str,
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
    background.add_task(_ingest_in_background, str(file_path), kb_id, file.filename)

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


@app.post("/rag/ask")
def ask_rag(request: RagAskRequest, current_user: dict = Depends(get_current_user)):
    """在指定知识库范围内问答。"""
    require_kb_access(request.kb_id, current_user)
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    result = answer_from_knowledge_base(
        question=request.question,
        top_k=RAG_TOP_K,
        kb_id=request.kb_id,
    )
    return {
        "question": request.question,
        "answer": result["answer"],
        "sources": result["sources"],
    }
