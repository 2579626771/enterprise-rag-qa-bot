# Enterprise RAG · 企业知识库问答系统

一个从 0 用 Python + Vue 构建的**多租户全栈 RAG（检索增强生成）**知识库系统：上传文档 → 自动切分向量化入库 → 知识库内语义检索 → 大模型基于检索结果作答，并标注来源片段，做到「可追溯、有依据」。

在基础问答之上，系统还提供 **JWT 登录认证、用户管理、多知识库隔离、知识库配额申请与审批、服务端会话历史、管理员控制台**，是一套贴近企业实际的知识库平台。

后端 FastAPI + ChromaDB + MySQL，接入阿里云百炼 Embedding 与 DeepSeek 回答模型；前端 Vue 3 + Vite + TypeScript + Element Plus 工作台界面。

---

## 功能特性

**认证与用户**
- 账密登录（JWT 令牌）、自助注册；令牌失效自动跳回登录页
- 用户管理（仅管理员）：新建 / 删除用户、调整知识库配额
- 首次启动自动预置管理员账号（默认 `admin` / `admin123`，可在 `.env` 配置）

**多知识库（多租户隔离）**
- 每个用户拥有独立的多个知识库，文档 / 向量 / 元数据按 `kb_id` 严格隔离
- 配额限制：普通用户默认可建 3 个库，超出需向管理员申请
- 配额申请与审批工作流：用户提交申请 → 管理员通过 / 驳回 → 自动增额

**问答**
- 知识库内语义检索问答，回答标注来源片段（文件名 + 第几段，可展开查看原文）
- 相似度距离阈值过滤，避免对无关问题硬凑答案
- **会话管理**：历史会话、新建、收藏、重命名、删除——**服务端 MySQL 持久化**，换浏览器 / 设备后历史仍在，且按用户隔离

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
| 元数据库 | MySQL（PyMySQL 驱动；文档元数据 / 会话历史 / 主题分类） |
| 认证 | JWT（PyJWT）、bcrypt 密码哈希 |
| Embedding | 阿里云百炼 |
| 回答模型 | DeepSeek |
| 文档解析 | pypdf（PDF）、python-docx（Word） |
| 前端 | Vue 3、Vite、TypeScript、axios、ECharts、Element Plus、Font Awesome |

> 内网友好：MySQL / 认证依赖均为纯 Python，无需编译；`pip-system-certs` 解决公司安全网关的 HTTPS 证书校验问题。

---

## 目录结构

```
enterprise-rag-qa-bot-main/
├── app/                      # 后端
│   ├── api.py                # FastAPI 路由（35 个端点：认证/用户/知识库/配额/文档/问答/会话/主题/运维）
│   ├── config.py             # 读取 .env 配置
│   ├── services/
│   │   ├── document_service.py         # 文档解析、切分（多格式 + 长度控制）
│   │   ├── embedding_service.py        # 向量化（阿里云）
│   │   ├── knowledge_base_service.py   # 向量库读写、检索、对账、重载（按 kb_id 隔离）
│   │   ├── vector_store_service.py     # 底层向量存取工具
│   │   ├── rag_service.py              # 知识库问答编排（检索 + 阈值过滤 + 生成）
│   │   ├── answer_service.py           # 调 DeepSeek 生成回答
│   │   ├── auth_service.py             # JWT 签发 / 校验
│   │   ├── user_service.py             # 用户 CRUD、密码校验、默认管理员
│   │   ├── kb_service.py               # 知识库 CRUD、配额限制
│   │   ├── quota_service.py            # 配额申请与审批
│   │   ├── metadata_service.py         # 文档元数据（MySQL，双仓库+自动降级）
│   │   ├── session_service.py          # 会话历史（MySQL，按用户归属）
│   │   └── topic_service.py            # 主题分类（MySQL，按知识库隔离，属主可增删改查）
│   └── schemas/              # 数据模型
├── frontend/                 # 前端（Vue 3 + Vite）
│   ├── src/
│   │   ├── views/            # Login/Register/Chat/Archive/Overview/Account/Guide/Review + Admin* 等 13 个
│   │   ├── components/       # UploadModal / UploadProgressModal
│   │   ├── composables/      # useAuth / useKnowledgeBase / useSessions / useTopics / useUploadTasks
│   │   ├── layouts/          # AppLayout
│   │   ├── router/           # 路由 + 登录守卫
│   │   └── api/client.ts     # 后端接口封装
│   └── package.json
├── data/
│   ├── documents/            # 上传的文档（按 用户/知识库 分目录）
│   └── chroma/               # 向量库持久化
├── scripts/                  # 数据迁移脚本（目录结构 / 多知识库）
├── tests/                    # 后端测试（unittest，159 个）
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
> - **MySQL**：库本身需先存在（`utf8mb4`），后端启动时自动建表（`documents` / `chat_sessions` / `chat_messages` / `topic_categories`）。设 `MYSQL_ENABLED=false` 可关闭 MySQL，后端自动降级为内存存储（仅不落盘，问答 / 上传主流程不受影响）。
> - **默认管理员**：首次启动、用户表为空时自动创建 `DEFAULT_ADMIN_USERNAME` / `DEFAULT_ADMIN_PASSWORD`（默认 `admin` / `admin123`，请在生产环境修改）。
> - **JWT_SECRET**：生产环境务必改成足够随机的长字符串。

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

> 除 `/`、`/auth/login`、`/auth/register` 外，所有端点均需在请求头带 `Authorization: Bearer <token>`。标注「仅管理员」的端点需管理员角色。

**认证与用户**

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/auth/login` | 账密登录，返回 JWT 令牌与用户信息 |
| POST | `/auth/register` | 自助注册（仅普通用户），成功即自动登录 |
| GET | `/auth/me` | 获取当前登录用户 |
| GET | `/users` | 用户列表（仅管理员） |
| POST | `/users` | 新建用户（仅管理员） |
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

**文档与问答**

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 健康检查 |
| GET | `/documents?kb_id=` | 文档列表（含 txt/md/pdf/docx 及元数据） |
| GET | `/stats?kb_id=` | 知识库统计（文档数、片段数、每文档片段数） |
| POST | `/documents/upload` | 上传文档（异步入库，秒级返回，前端轮询状态） |
| POST | `/documents/ingest` | 将已存在的文件入库 |
| DELETE | `/documents/{filename}?kb_id=` | 删除文档及其向量片段 |
| POST | `/rag/ask` | 知识库内问答，返回 answer + sources |
| POST | `/maintenance/reconcile?kb_id=` | 数据对账，清理僵尸片段 |
| POST | `/maintenance/reload?kb_id=` | 重载向量库，加载最新数据 |

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
  ]
}
```

---

## 检索与切分机制

**切分**（`document_service.split_document_by_paragraphs`）
- 按段落切分，并做两级控制：
  - 过短的标题 / 目录碎片 → 合并到相邻正文（min 60 字）
  - 过长的段落（如 PDF 整页）→ 二次切分（按换行 / 句末标点 / 长度，max 250 字）
- 目的：既不产生无意义碎片，也不让大块文本稀释语义，保证检索精度。

**检索**（`knowledge_base_service.search` + `rag_service`）
- 按 `kb_id` 限定检索范围（多知识库隔离）
- 多召回候选 → 过滤过短碎片 → 取 top_k（不足则补齐保底）
- 距离超过 `RAG_MAX_DISTANCE` 的片段视为不相关而丢弃
- 命中片段拼成资料，交由 DeepSeek 依据资料作答

---

## 数据持久化与降级

文档元数据、会话历史、主题分类均落 MySQL，统一采用**双仓库 + 懒连接 + 自动降级 + 自动建表**的范式（见 `metadata_service` / `session_service` / `topic_service`）：连不上 MySQL 时自动切换到内存实现，问答 / 上传主流程不受影响，仅数据不落盘。这使得本地开发无需 MySQL 也能跑通，生产接上 MySQL 即持久化。

---

## 测试

```powershell
python -m unittest discover -s tests
```
当前 **159 个测试**，覆盖各 service、API 端点、认证、多知识库隔离、会话归属隔离、主题分类按库隔离与联动等。普通测试使用 fake provider 与内存仓库，不会调用真实阿里云 / DeepSeek API，也不依赖真实 MySQL。

---

## 常见问题

**Q：在外部脚本重新入库后，问答检索不到新数据？**
后端进程启动时会缓存向量库连接。外部改动数据后，点前端「重载知识库」按钮（或 `POST /maintenance/reload`），或重启后端即可。

**Q：删除文档后，片段数 / 图表仍显示它？**
可能是直接在文件夹删了文件、没走前端删除按钮，导致向量残留。点「数据对账」清理即可。

**Q：上传大文件（如大 PDF）很慢？**
上传接口存盘即返回，解析 / 向量化在后台异步进行，前端轮询状态。Embedding 采用分批批量调用（默认每批 10 条）提速。超大文档仍需一定时间，属正常现象。

**Q：没有 MySQL 能跑吗？**
能。设 `MYSQL_ENABLED=false` 或数据库不可用时，元数据 / 会话 / 主题自动走内存实现，功能可用但重启后不保留。

---

## 说明

本项目用于学习 Python 项目结构、FastAPI 后端、Vue 前端、JWT 认证、多租户隔离、文档解析与切分、向量数据库、RAG 检索问答与企业级知识库设计。
