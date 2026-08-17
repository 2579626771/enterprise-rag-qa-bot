# Enterprise RAG · 企业知识库问答系统

一个从 0 用 Python + Vue 构建的**多租户全栈 RAG（检索增强生成）**知识库系统：上传文档 → 自动切分向量化入库 → 知识库内语义检索 → 大模型基于检索结果作答，并标注来源片段，做到「可追溯、有依据」。

在基础问答之上，系统还提供 **JWT 登录认证、用户管理、多知识库隔离、知识库配额申请与审批、服务端会话历史、管理员控制台**，并针对企业最痛的两点做了强化：**答案层「研判」防幻觉**（作答前先让 LLM 判断「资料是否真能回答」，不能答则明确拒答）与 **三级检索配置**（系统 / 租户 / 知识库参数在线可调）。是一套贴近企业实际的知识库平台。

后端 FastAPI + ChromaDB + MySQL，接入阿里云百炼 Embedding 与 DeepSeek 回答模型，检索增强层由 LangChain 承接；前端 Vue 3 + Vite + TypeScript + Element Plus 工作台界面。

---

## 功能特性

**认证与用户**
- 账密登录（JWT 令牌）、自助注册；令牌失效自动跳回登录页
- 自助找回密码：注册时设置 3 个找回问题，忘记密码时必须输入登录用户名（不允许显示名）并回答问题后重置密码
- 个人中心：查看账号信息、修改显示名、修改自己的密码、维护找回密码问题；管理员重置临时密码后会引导用户先改密
- 用户管理（仅管理员）：新建 / 删除用户、调整知识库配额、重置其他用户密码
- 登录失败保护：连续输错达到阈值后短时锁定账号；管理员重置密码会清除锁定
- 首次启动自动预置管理员账号（默认 `admin` / `admin123`，可在 `.env` 配置）

**多知识库（多租户隔离）**
- 每个用户拥有独立的多个知识库，文档 / 向量 / 元数据按 `kb_id` 严格隔离
- 配额限制：普通用户默认可建 3 个库，超出需向管理员申请
- 配额申请与审批工作流：用户提交申请 → 管理员通过 / 驳回 → 自动增额

**问题反馈**
- 用户侧问题反馈：提交标题、问题描述和多张截图附件，查看自己的反馈历史、处理状态和管理员回复
- 管理员侧反馈处理：查看全部反馈与用户截图，按状态筛选，回复解决方法并流转处理中 / 已解决 / 已关闭
- 闭环状态：待处理 → 处理中 → 已回复 → 用户确认关闭

**通知与消息中心**
- 管理员通知下发：可向全部用户或指定用户发送系统通知，并查看收件数、未读/已读/关闭统计
- 用户消息中心：顶部「通知」显示未读数量，未读通知中央弹窗提醒，用户可确认已读或关闭通知

**模型监控**
- 管理员侧模型监控：记录向量模型、问答大模型、答案研判、查询改写、rerank 的调用次数、token 消耗、平均/P95/最大延迟和失败率
- 用户归因：问答、文档入库、维护重切分等链路通过上下文记录 `user_id` / `kb_id` / `request_id`，可按用户查看消耗排行和调用明细
- 异常告警：按失败率、平均延迟、用户 token 消耗阈值实时生成告警；监控记录失败只写日志，不影响主流程

**问答**
- 知识库内语义检索问答，回答标注来源片段（文件名 + 第几段，可展开查看原文）
- 回答支持前端打字机式渐进输出，完整回答仍会持久化到会话历史
- 相似度距离阈值过滤，避免对无关问题硬凑答案
- **答案层「研判」防幻觉**：作答前先让 LLM 判断「资料是否真能回答该问题」，不能答则明确拒答，治「主题相关但库里没答案」导致的幻觉；拒答 / 低可信在前端有徽标提示，且随会话持久化。评测实证幻觉风险 91.7%→8.3%、正例零误伤。可用 `JUDGE_ENABLED` 一键降级。
- **知识库范围选择器**：问答页可选「全部 / 指定库」。普通用户「全部」= 只查自己所有库（严格隔离，绝不跨租户），管理员「全部」= 真全库。
- **会话管理**：历史会话、新建、收藏、重命名、删除——**服务端 MySQL 持久化**，换浏览器 / 设备后历史仍在，且按用户隔离

**检索配置（三级在线可调）**
- 系统默认 / 租户默认 / 按知识库三级配置：`top_k`、距离阈值、研判开关、作答提示词等在线可调，存 MySQL，**改后即生效，无需改 `.env` 重启**
- 多 / 全库查询用哪份配置由租户偏好决定；三级解析 `kb → tenant → system → 硬默认`

**检索质量增强（评测驱动、默认保守、可一键切换）**
- **LangChain 适配层**：阿里云 Embedding 包成 LangChain `Embeddings`、Chroma 召回接 `langchain_chroma`，作为增强层地基，距离语义零漂移、指标与原生一致
- **邻近上下文扩展**：`RETRIEVAL_CONTEXT_WINDOW=1` 只扩展最终来源内容、不改 distance/阈值语义；已验证修复 #8/#55 这类答案跨相邻 chunk 的问题（Hit@5 94.7%→100%）
- **Rerank 重排/融合**（阿里云 gte-rerank-v2）：支持 `sort/window/weighted`；旧 pure rerank 伤召回，`weighted` 不再伤 Hit@5 且 MRR 0.776→0.794，默认仍保守关闭
- **多查询改写**（DeepSeek）：把原问题改写成 N 条语义等价查询，多路召回合并去重；评测正向（MRR 0.776→0.807、Hit@5 零误伤），因慢（多一次 LLM 调用）默认关、可手动开
- **BM25+jieba 混合检索**：向量 + 关键词召回用 RRF 融合；本库评测单开伤召回（Hit@5 92.1%），代码保留、默认不开
- **阶段 6 模式开关**：`RETRIEVAL_MODE=auto|vector|multi_query|rerank|rerank_fusion|hybrid|hybrid_rerank_fusion`，`vector` 是最稳降级
- 所有增强项均：失败自动降级、不中断检索、**不扩大检索范围（隔离红线不受影响）**

**资料档案库**
- 文档列表（统计卡 + 表格 + 分类筛选 + 搜索 + 分页）
- 上传弹窗：拖拽上传、知识主题分类、文档描述
- **多格式解析入库**：TXT / Markdown / PDF / Word(DOCX)
- 上传进度：真实传输百分比 → 处理中 → 成功片段数 / 失败原因（大文件异步入库，不阻塞上传）
- **主题分类**：**按知识库隔离**——每个知识库有自己独立的一组分类，新建知识库时自动种入 8 个默认分类；知识库属主（或管理员）可在「资料档案库」页对本库分类做增删改查（含默认分类）。重命名分类会联动更新本库下使用该分类的文档。

**运行概览**
- ECharts 图表：各文档片段占比、片段分布、片段数排名（数据来自真实 `/stats`）

**运维**
- 数据对账：清理「文件已删除但向量仍残留」的僵尸片段
- 重载知识库：外部改动数据后，无需重启后端即可加载最新数据

---

## 技术栈

| 层 | 技术 |
|----|------|
| 后端 | Python 3.12、FastAPI、Uvicorn |
| 向量库 | ChromaDB（持久化，余弦相似度） |
| 元数据库 | MySQL（PyMySQL 驱动；用户 / 知识库 / 配额 / 文档元数据 / 会话历史 / 主题分类 / 反馈 / 通知 / 模型用量） |
| 认证 | JWT（PyJWT）、bcrypt 密码哈希 |
| Embedding | 阿里云百炼 |
| 回答模型 | DeepSeek |
| 研判 / 改写 | DeepSeek（研判经 LangChain `ChatOpenAI`，防幻觉） |
| 检索增强 | LangChain（`langchain_chroma` 召回适配）、阿里云 gte-rerank-v2（重排）、BM25 + jieba（混合检索） |
| 文档解析 | pypdf（PDF）、python-docx（Word） |
| 前端 | Vue 3、Vite、TypeScript、axios、ECharts、Element Plus、Font Awesome；Vitest + Vue Test Utils |

> 内网友好：MySQL / 认证依赖均为纯 Python，无需编译；`pip-system-certs` 解决公司安全网关的 HTTPS 证书校验问题。

---

## 目录结构

```
enterprise-rag-qa-bot-main/
├── app/                      # 后端
│   ├── api.py                # FastAPI 路由（认证/用户/知识库/配额/文档/问答/会话/主题/检索配置/运维）
│   ├── config.py             # 读取 .env 配置
│   ├── services/
│   │   ├── document_service.py         # 文档解析、切分（多格式 + 长度控制）
│   │   ├── embedding_service.py        # 向量化（阿里云）
│   │   ├── knowledge_base_service.py   # 向量库读写、检索、对账、重载（按 kb_id 隔离；接多查询/rerank/hybrid/context）
│   │   ├── vector_store_service.py     # 底层向量存取工具
│   │   ├── langchain_adapters.py       # LangChain 适配层（Aliyun Embeddings + langchain_chroma 召回）
│   │   ├── rag_service.py              # 知识库问答编排（检索 + 阈值过滤 + 研判 + 生成）
│   │   ├── answer_service.py           # 调 DeepSeek 生成回答（支持自定义作答提示词）
│   │   ├── judge_service.py            # 答案层「研判」防幻觉（LangChain ChatOpenAI + DeepSeek）
│   │   ├── rerank_service.py           # rerank 重排/融合（阿里云 gte-rerank-v2，默认关）
│   │   ├── query_rewrite_service.py    # 多查询改写（DeepSeek，默认关）
│   │   ├── hybrid_search_service.py    # BM25+jieba 混合检索 + RRF 融合（默认关）
│   │   ├── retrieval_config_service.py # 三级检索配置（系统/租户/知识库，存 MySQL）
│   │   ├── auth_service.py             # JWT 签发 / 校验
│   │   ├── user_service.py             # 用户 CRUD、密码校验、默认管理员
│   │   ├── kb_service.py               # 知识库 CRUD、配额限制
│   │   ├── quota_service.py            # 配额申请与审批
│   │   ├── feedback_service.py         # 问题反馈与管理员处理闭环
│   │   ├── notification_service.py     # 管理员通知下发与用户消息中心
│   │   ├── model_usage_service.py      # 模型调用用量监控（token/延迟/失败率/告警）
│   │   ├── metadata_service.py         # 文档元数据（MySQL，双仓库+自动降级）
│   │   ├── session_service.py          # 会话历史（MySQL，按用户归属，含研判 verdict）
│   │   └── topic_service.py            # 主题分类（MySQL，按知识库隔离，属主可增删改查）
│   └── schemas/              # 数据模型
├── frontend/                 # 前端（Vue 3 + Vite）
│   ├── src/
│   │   ├── views/            # Login/Register/Chat/Archive/Overview/Account/Guide/Review + Admin* 等
│   │   ├── components/       # UploadModal / UploadProgressModal / ConfigForm
│   │   ├── composables/      # useAuth / useKnowledgeBase / useSessions / useTopics / useUploadTasks
│   │   ├── layouts/          # AppLayout
│   │   ├── router/           # 路由 + 登录守卫
│   │   └── api/client.ts     # 后端接口封装
│   └── package.json
├── data/
│   ├── documents/            # 上传的文档（按 用户/知识库 分目录）
│   └── chroma/               # 向量库持久化
├── eval/                     # 检索/研判评测集与 before/after 结果（真实数据本地保存，仓库仅放脱敏示例）
├── scripts/                  # 数据迁移 + 评测/诊断脚本（eval_retrieval / eval_answer / diagnose_retrieval_case）
├── tests/                    # 后端测试（unittest，280 个）
├── requirements.txt
├── 启动后端.bat              # 一键启动后端
└── .env.example
```

---

## 快速开始

### 一、后端

**1. 激活虚拟环境**（PowerShell）
```powershell
.\.venv\Scripts\Activate.ps1
```

**2. 安装依赖**
```powershell
python -m pip install -r requirements.txt
```

**3. 配置环境变量**：复制 `.env.example` 为 `.env`，填入真实 API Key 与 MySQL 连接信息。

> - 真实 Key 只写在 `.env`，切勿写入代码或提交仓库。
> - **MySQL**：库本身需先存在（`utf8mb4`），后端启动时自动建表（用户/知识库/配额、`documents` / `chat_sessions` / `chat_messages` / `topic_categories` / `retrieval_configs` / `feedback_tickets` / `feedback_attachments` / `notifications` / `notification_recipients` / `model_usage_records` 等）。设 `MYSQL_ENABLED=false` 可关闭 MySQL，后端自动降级为内存存储（仅不落盘，问答 / 上传主流程不受影响）。
> - **问题反馈截图**：`FEEDBACK_ATTACHMENT_DIR` 存放用户上传的反馈截图，生产部署需纳入持久化卷；`FEEDBACK_ATTACHMENT_MAX_COUNT` / `FEEDBACK_ATTACHMENT_MAX_MB` 控制每条反馈截图张数与单张大小。
> - **默认管理员**：首次启动、用户表为空时自动创建 `DEFAULT_ADMIN_USERNAME` / `DEFAULT_ADMIN_PASSWORD`（默认 `admin` / `admin123`，请在生产环境修改）。
> - **登录失败保护**：`LOGIN_MAX_FAILED_ATTEMPTS` / `LOGIN_LOCK_MINUTES` 控制连续输错后的短时锁定策略。
> - **模型监控告警**：`MODEL_USAGE_ALERT_*` 控制失败率、延迟、token 消耗告警阈值；调用记录存 MySQL，失败自动降级不影响主流程。
> - **JWT_SECRET**：生产环境务必改成足够随机的长字符串。
> - **答案层研判**：`JUDGE_ENABLED=true` 开启防幻觉研判（默认关，关闭时行为与引入前一致）。
> - **检索增强开关**：`RERANK_ENABLED`（rerank 重排，默认关）、`MULTI_QUERY_ENABLED`（多查询改写，默认关）——均评测驱动、失败降级、不扩检索范围。
> - **检索模式**：`RETRIEVAL_MODE=auto|vector|multi_query|rerank|rerank_fusion|hybrid|hybrid_rerank_fusion`；`vector` 是最稳降级。`RETRIEVAL_CONTEXT_WINDOW=1` 可带入相邻 chunk，已验证可修复 #8/#55 这类跨片段答案。
> - **⚠️ 内网代理**：若在公司代理环境，启动后端前需设 `NO_PROXY`（或直接用内置该设置的 `启动后端.bat`），否则对阿里云 / DeepSeek 的请求会被代理拦截导致问答失败。

**4. 启动后端**
```powershell
python -m uvicorn app.api:app --reload
```
或直接双击项目根目录的 **`启动后端.bat`**。

服务地址 `http://127.0.0.1:8000`，交互式接口文档 `http://127.0.0.1:8000/docs`。

### 二、前端

```powershell
cd frontend
npm install
npm run dev
```
或双击 `frontend/启动前端.bat`。浏览器打开 `http://localhost:5173`，用默认管理员账号登录。

> 前端通过 Vite 代理把 `/api` 转发到后端 8000 端口，无需额外配置跨域。

---

## API 端点

> 除 `/`、`/auth/login`、`/auth/register`、`/auth/recovery/questions`、`/auth/recovery/reset-password` 外，所有端点均需在请求头带 `Authorization: Bearer <token>`。标注「仅管理员」的端点需管理员角色。

**认证与用户**

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/auth/login` | 账密登录，返回 JWT 令牌与用户信息 |
| POST | `/auth/register` | 自助注册（仅普通用户），成功即自动登录 |
| GET | `/auth/me` | 获取当前登录用户 |
| PATCH | `/auth/me` | 当前用户修改显示名等个人资料 |
| POST | `/auth/password/change` | 当前用户修改自己的密码 |
| PUT | `/auth/recovery/questions` | 当前用户设置 / 覆盖 3 个找回密码问题 |
| POST | `/auth/recovery/questions` | 忘记密码第一步：按登录用户名读取找回问题 |
| POST | `/auth/recovery/reset-password` | 忘记密码第二步：答对问题后重置密码 |
| GET | `/users` | 用户列表（仅管理员） |
| POST | `/users` | 新建用户（仅管理员） |
| POST | `/users/{user_id}/password-reset` | 管理员重置其他用户密码并可要求下次登录改密（仅管理员） |
| DELETE | `/users/{user_id}` | 删除用户（仅管理员） |
| PATCH | `/users/{user_id}/quota` | 调整用户知识库配额（仅管理员） |

**知识库与配额**

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/kbs` | 知识库列表（管理员 `?all=true` 看全部） |
| POST | `/kbs` | 新建知识库（受配额限制） |
| PUT | `/kbs/{kb_id}` | 更新知识库名称 / 描述 |
| DELETE | `/kbs/{kb_id}` | 删除知识库（连带文件 / 向量 / 元数据） |
| POST | `/kb-requests` | 提交配额申请 |
| GET | `/kb-requests/mine` | 我的申请记录 |
| GET | `/kb-requests/pending` | 待审批申请（仅管理员） |
| POST | `/kb-requests/{id}/approve` | 通过申请（仅管理员） |
| POST | `/kb-requests/{id}/reject` | 驳回申请（仅管理员） |

**问题反馈**

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/feedback` | 提交问题反馈 |
| POST | `/feedback/{id}/attachments` | 给自己的反馈上传截图附件 |
| GET | `/feedback/{id}/attachments/{attachment_id}` | 鉴权查看反馈截图（本人或管理员） |
| GET | `/feedback/mine` | 我的反馈历史 |
| POST | `/feedback/{id}/close` | 用户确认关闭自己的反馈 |
| GET | `/feedback/admin?status=` | 管理员查看全部反馈，可按状态筛选 |
| PATCH | `/feedback/admin/{id}` | 管理员更新反馈状态与回复 |

**通知与消息中心**

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/notifications/mine` | 当前用户通知列表 |
| GET | `/notifications/unread-count` | 当前用户未读通知数量 |
| POST | `/notifications/{id}/read` | 当前用户确认通知已读 |
| POST | `/notifications/{id}/close` | 当前用户关闭通知 |
| POST | `/notifications/admin` | 管理员下发通知（全部或指定用户） |
| GET | `/notifications/admin` | 管理员查看通知下发历史与统计 |

**模型监控**

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/admin/model-usage/summary` | 模型调用聚合统计（token、调用数、延迟、失败率、告警；仅管理员） |
| GET | `/admin/model-usage/records` | 最近模型调用明细，可按时间/用户/模型类型/成功失败筛选（仅管理员） |
| GET | `/admin/model-usage/alerts` | 模型异常告警（失败率、平均延迟、用户 token 消耗；仅管理员） |

**文档与问答**

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 健康检查 |
| GET | `/documents?kb_id=` | 文档列表（含 txt/md/pdf/docx 及元数据） |
| GET | `/stats?kb_id=` | 知识库统计（文档数、片段数、每文档片段数） |
| POST | `/documents/upload` | 上传文档（异步入库，秒级返回，前端轮询状态） |
| POST | `/documents/ingest` | 将已存在的文件入库 |
| DELETE | `/documents/{filename}?kb_id=` | 删除文档及其向量片段 |
| POST | `/rag/ask` | 知识库内问答，返回 answer + sources（+ 研判 verdict）；`kb_id` 可选，缺省按范围偏好检索 |
| POST | `/maintenance/reconcile?kb_id=` | 数据对账，清理僵尸片段 |
| POST | `/maintenance/reload?kb_id=` | 重载向量库，加载最新数据 |
| POST | `/maintenance/rechunk-docx?kb_id=` | 统一存量 DOCX 切分，按当前解析/段落切分策略重建该库 Word 文档向量 |

**会话历史（按用户归属）**

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/sessions` | 当前用户的会话列表 |
| POST | `/sessions` | 新建会话 |
| PATCH | `/sessions/{id}` | 改名（`title`）或切换收藏（`toggle_favorite`） |
| DELETE | `/sessions/{id}` | 删除会话及其消息 |
| GET | `/sessions/{id}/messages` | 会话内的消息列表 |
| POST | `/sessions/{id}/messages` | 向会话追加一条消息 |

**主题分类（按知识库隔离）**

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/topics?kb_id=` | 某知识库的分类列表（属主或管理员） |
| POST | `/topics` `{kb_id, name}` | 新增分类（属主或管理员，名称唯一、幂等） |
| PATCH | `/topics/{id}` `{name}` | 重命名分类，并联动更新本库下用旧分类名的文档 |
| DELETE | `/topics/{id}` | 删除分类（属主或管理员） |

**检索配置（三级在线可调）**

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/config/retrieval?scope=&kb_id=` | 读取某层级配置（system 层仅管理员，kb 层走知识库访问隔离） |
| PUT | `/config/retrieval` | 写入 / 更新某层级配置（top_k、距离阈值、研判开关、作答提示词等），存 MySQL 即时生效 |
| DELETE | `/config/retrieval?scope=&kb_id=` | 删除某层级配置，回落上一级（kb→tenant→system→硬默认） |

### 问答接口示例

请求 `POST /rag/ask`：
```json
{ "question": "怎么读取文档内容？", "kb_id": 1 }
```
返回：
```json
{
  "question": "怎么读取文档内容？",
  "answer": "……",
  "sources": [
    { "filename": "xxx.txt", "chunk_index": 2, "content": "……" }
  ],
  "answerable": true,
  "reason": "资料中包含读取文档的相关说明。",
  "confidence": "high"
}
```

> `answerable` / `reason` / `confidence` 为答案层「研判」结果：判定资料是否真能回答该问题，`answerable=false` 表示拒答（前端展示拒答 / 低可信徽标）。研判关闭时上层给出默认放行值（`answerable=true`、`confidence=high`）。

---

## 检索与切分机制

**切分**（`document_service.split_document_by_paragraphs`）
- 按段落切分，并做两级控制：
  - 过短的标题 / 目录碎片 → 合并到相邻正文（min 60 字）
  - 过长的段落（如 PDF 整页）→ 二次切分（按换行 / 句末标点 / 长度，max 250 字）
- 目的：既不产生无意义碎片，也不让大块文本稀释语义，保证检索精度。

**检索**（`knowledge_base_service.search` + `rag_service`）
- 按 `kb_id` 限定检索范围（多知识库隔离）；召回经 LangChain `langchain_chroma`，距离语义与原生 Chroma 一致
- （可选）**多查询改写**：把原问题改写成 N 条语义等价查询多路召回，按 `(kb_id, filename, chunk_index)` 去重保留最小距离——所有查询共用同一 `where=kb_id` 过滤，只扩召回入口、不扩范围
- （可选）**BM25+jieba 混合检索**：只在已授权范围内读取片段，与向量召回用 RRF 融合；本轮评测单独开启会伤召回，默认不开
- 多召回候选 → 过滤过短碎片 →（可选）**rerank 重排/融合**（`sort`/`window`/`weighted`，保留每条原距离）→ 取 top_k（不足则补齐保底）
- （可选）**邻近上下文扩展**：`RETRIEVAL_CONTEXT_WINDOW=1` 只扩展最终 source 的上下文，不改变原始 distance；用于处理答案被切到相邻 chunk 的情况
- 距离超过 `RAG_MAX_DISTANCE` 的片段视为不相关而丢弃
- 命中片段拼成资料，交由 DeepSeek 依据资料作答；（可选）作答前先经**答案层「研判」**判断资料是否真能回答，不能答则拒答

> `top_k`、距离阈值、研判开关、作答提示词等参数支持**三级在线配置**（系统 / 租户 / 知识库），存 MySQL，改后即时生效。检索增强支持 `RETRIEVAL_MODE` 显式切换；默认 `auto` 保持旧行为，由 `MULTI_QUERY_ENABLED` / `RERANK_ENABLED` 控制。
>
> 本轮评测结论：`RETRIEVAL_CONTEXT_WINDOW=1` 修复 #8/#55，Hit@5 **94.7%→100%**；`rerank_fusion(weighted)` MRR **0.776→0.794** 且不再伤 Hit@5；`hybrid` 单独开启 Hit@5 **92.1%**，暂不建议默认开启。

---

## 答案层「研判」防幻觉

企业知识库最痛的不是「召回不到」，而是「主题相关但库里没答案时，模型硬编一个」。本项目的解法放在**答案层**而非检索层——评测证明相似度距离阈值无法区分「能答 / 不能答」（两者区间重叠），只能靠 LLM 做语义研判：

- 作答前一次 LLM 调用同时完成「研判 + 作答」，返回 `{answerable, reason, answer, confidence}`
- `answerable=false` → 明确拒答，前端展示拒答 / 低可信徽标，并随会话持久化（`chat_messages` 存 verdict）
- 研判失败自动降级为放行（`answerable=true` + `confidence=low`），绝不因研判异常中断问答
- `JUDGE_ENABLED` 一键开关，关闭时行为与引入前完全一致，可平滑降级
- **评测实证**（`eval/qa_set.json`，62 题含 21 hard-negative）：幻觉风险 **91.7%→8.3%**，正例召回保持 **94.7% 零误伤**

---

## 数据持久化与降级

用户/知识库/配额、文档元数据、会话历史、主题分类、检索配置、问题反馈、通知和模型用量记录均落 MySQL，统一采用**双仓库 + 懒连接 + 自动降级 + 自动建表**的范式（见 `*_service.py`）：连不上 MySQL 时自动切换到内存实现，问答 / 上传主流程不受影响，仅数据不落盘。这使得本地开发无需 MySQL 也能跑通，生产接上 MySQL 即持久化。

---

## 测试

```powershell
# 后端
.venv/Scripts/python.exe -m unittest discover -s tests

# 前端
cd frontend
npm test
npm run build
```
当前后端 **280 个测试**，覆盖各 service、API 端点、认证、多知识库隔离、会话归属隔离、主题分类按库隔离与联动、答案层研判、三级检索配置解析、rerank / 多查询改写、DOCX 重切分、模型用量监控（含开启增强/维护项下的隔离红线回归）等。普通测试使用 fake provider 与内存仓库，不会调用真实阿里云 / DeepSeek API，也不依赖真实 MySQL。

前端已接入 Vitest + Vue Test Utils，首批覆盖登录态持久化、路由鉴权/强制改密守卫、问题反馈截图校验与提交流程。

> **检索 / 研判质量评测**（区别于单元测试，会真调 API）：`python -m scripts.eval_retrieval`（检索层，Hit@k / MRR）与 `python -m scripts.eval_answer`（研判层，幻觉风险 / 拒答率），基于 `eval/qa_set.json`。任何检索 / 研判改动都先跑 before/after，数字说话再决定去留。

---

## 常见问题

**Q：在外部脚本重新入库后，问答检索不到新数据？**
后端进程启动时会缓存向量库连接。外部改动数据后，点前端「重载知识库」按钮（或 `POST /maintenance/reload`），或重启后端即可。

**Q：删除文档后，片段数 / 图表仍显示它？**
可能是直接在文件夹删了文件、没走前端删除按钮，导致向量残留。点「数据对账」清理即可。

**Q：老的 DOCX 文档切分不统一，如何重建？**
进入该知识库的文档工作区，点击「统一 DOCX 切分」；或调用 `POST /maintenance/rechunk-docx?kb_id=<知识库ID>`。系统会按当前 DOCX 解析与段落切分策略替换该库下 Word 文档的旧向量片段，普通用户只能处理自己的知识库。

**Q：上传大文件（如大 PDF）很慢？**
上传接口存盘即返回，解析 / 向量化在后台异步进行，前端轮询状态。Embedding 采用分批批量调用（默认每批 10 条）并用线程池并发发送各批次（并发度 `EMBEDDING_CONCURRENCY`，默认 5）提速。超大文档仍需一定时间，属正常现象。

**Q：没有 MySQL 能跑吗？**
能。设 `MYSQL_ENABLED=false` 或数据库不可用时，元数据 / 会话 / 主题 / 检索配置自动走内存实现，功能可用但重启后不保留。

**Q：为什么模型有时直接说「资料里没有」而不硬答？**
这是**答案层研判**在起作用（`JUDGE_ENABLED=true`）：作答前先判断资料是否真能回答，不能答则明确拒答，避免主题相关却无答案时编造。属预期行为，可在检索配置页或 `.env` 关闭 `JUDGE_ENABLED` 降级为总是作答。

**Q：rerank / 多查询改写 / hybrid 要不要开？**
这些增强都应**评测驱动**：旧 pure rerank 对本库整体伤召回（Hit@5 94.7%→89.5%），不建议直接开；`rerank_fusion(weighted)` 不再伤 Hit@5 且 MRR 0.776→0.794，可在评测后尝试；多查询改写评测正向（MRR 0.776→0.807、零误伤）但多一次 LLM 调用较慢，适合「质量优先胜过延迟」的场景；hybrid 单开 Hit@5 92.1%，暂不建议默认开启。跨 chunk 证据场景优先试 `RETRIEVAL_CONTEXT_WINDOW=1`。改这类参数后请用 `scripts/eval_*.py` 跑 before/after 再决定。

---

