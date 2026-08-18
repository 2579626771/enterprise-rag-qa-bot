# Enterprise RAG QA Bot

企业级知识库问答系统，基于 FastAPI、ChromaDB、MySQL、Vue 3 和大模型能力构建。系统支持多知识库隔离、文档上传入库、语义检索问答、来源溯源、账号权限、配置管理、反馈闭环、通知中心和模型用量监控。

## 功能概览

- 知识库问答：支持 TXT、Markdown、PDF、DOCX 文档解析、切分、向量化入库和基于来源片段的回答。
- 多知识库隔离：普通用户只能访问自己的知识库；管理员可管理用户、配额和全局数据。
- 账号体系：JWT 登录、自助注册、密码找回、个人中心、登录失败短时锁定、管理员重置密码。
- 检索增强：支持向量检索、邻近上下文扩展、rerank、多查询改写、BM25 + jieba 混合检索和三级检索配置。
- 答案研判：可启用回答前研判，降低资料不足时的幻觉回答风险。
- 运营能力：问题反馈、截图附件、管理员回复闭环、系统通知、模型调用次数/token/延迟/失败率统计。
- 部署能力：提供 Dockerfile、Docker Compose、Nginx 反代配置和生产环境变量示例。

## 技术栈

| 层级 | 技术 |
| --- | --- |
| 后端 | Python 3.12、FastAPI、Uvicorn |
| 向量库 | ChromaDB |
| 元数据 | MySQL、PyMySQL |
| 认证 | JWT、bcrypt |
| 文档解析 | pypdf、python-docx |
| 检索增强 | LangChain、langchain-chroma、jieba |
| 前端 | Vue 3、Vite、TypeScript、Element Plus、ECharts、Vitest |

## 目录结构

```text
app/                 后端 API、配置、服务和数据模型
frontend/            Vue 3 前端工作台
scripts/             迁移、诊断、评测脚本
tests/               后端单元测试
eval/                脱敏评测示例和评测说明
data/                仅保留脱敏示例；运行时上传文档和向量库不入仓
Dockerfile           后端生产镜像
docker-compose.yml   MySQL + 后端 + Nginx 前端部署编排
```

## 本地开发

### 后端

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m uvicorn app.api:app --reload
```

后端默认地址为 `http://127.0.0.1:8000`，接口文档为 `http://127.0.0.1:8000/docs`。

### 前端

```powershell
cd frontend
npm install
npm run dev
```

前端默认地址为 `http://localhost:5173`，Vite 会把 `/api/*` 请求代理到本地后端。

## 环境变量

- `.env.example`：本地开发示例，所有密钥均为占位符。
- `.env.production.example`：生产部署示例，提交前不得填入真实密码、API Key、JWT secret、真实域名或内网地址。
- 本地真实配置写入 `.env` 或 `.env.production`，这些文件已被 `.gitignore` 排除。

关键变量：

| 变量 | 说明 |
| --- | --- |
| `ALIYUN_API_KEY` | 阿里云 DashScope Embedding/Rerank Key |
| `DEEPSEEK_API_KEY` | DeepSeek API Key |
| `MYSQL_*` | MySQL 连接信息 |
| `JWT_SECRET` | JWT 签名密钥，生产环境必须替换为足够随机的长字符串 |
| `DOCUMENTS_DIR` | 上传文档存储目录 |
| `CHROMA_DIR` | Chroma 向量库存储目录 |
| `RETRIEVAL_MODE` | 检索模式：`auto`、`vector`、`multi_query`、`rerank`、`rerank_fusion`、`hybrid`、`hybrid_rerank_fusion` |

## Docker Compose 部署

```bash
cp .env.production.example .env.production
# 编辑 .env.production，替换所有占位符
docker compose --env-file .env.production config
docker compose --env-file .env.production build
docker compose --env-file .env.production up -d
```

生产部署会将上传文档、向量库、反馈附件和日志挂载到运行时目录。这些目录属于业务数据或运行副产物，不应提交到源码仓库。

## 测试

```powershell
# 后端
.\.venv\Scripts\python.exe -m unittest discover -s tests

# 前端
cd frontend
npm test
npm run build

# Docker Compose 配置校验
docker compose --env-file .env.production.example config
```

## 安全与公开仓库约定

- 不提交 `.env`、真实 API Key、真实数据库密码、JWT secret、证书、日志、上传文档、向量库、反馈附件或内部评测数据。
- `eval/qa_set.example.json` 是脱敏示例，真实评测集和评测结果应保留在本地。
- `data/sample.txt` 与 `data/upload_demo.txt` 仅用于演示解析和上传流程，不包含真实业务内容。
- 如果曾经误提交真实密钥，应立即轮换密钥，并根据需要清理 Git 历史。
