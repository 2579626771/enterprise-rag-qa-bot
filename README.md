# Enterprise RAG · 企业知识库问答系统

一个从 0 用 Python + Vue 构建的全栈 RAG（检索增强生成）知识库系统：上传文档 → 自动切分向量化入库 → 全库语义检索 → 大模型基于检索结果作答，并标注来源片段，做到「可追溯、有依据」。

后端 FastAPI + ChromaDB，接入阿里云百炼 Embedding 与 DeepSeek 回答模型；前端 Vue 3 + Vite + TypeScript 工作台界面。

---

## 功能特性

**问答**
- 全库语义检索问答，回答标注来源片段（文件名 + 第几段，可展开查看原文）
- 相似度距离阈值过滤，避免对无关问题硬凑答案
- 会话管理：历史会话、新建、收藏、恢复（前端 localStorage 持久化）

**资料档案库**
- 文档列表（统计卡 + 表格 + 分类筛选 + 搜索 + 分页）
- 上传弹窗：拖拽上传、知识主题分类、文档描述
- **多格式解析入库**：TXT / Markdown / PDF / Word(DOCX)
- 上传进度：真实传输百分比 → 处理中 → 成功片段数 / 失败原因
- 详情、删除

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
| Embedding | 阿里云百炼 |
| 回答模型 | DeepSeek |
| 文档解析 | pypdf（PDF）、python-docx（Word） |
| 前端 | Vue 3、Vite、TypeScript、axios、ECharts、Font Awesome |

---

## 目录结构

```
enterprise-rag-qa-bot-main/
├── app/                      # 后端
│   ├── api.py                # FastAPI 路由（9 个端点）
│   ├── config.py             # 读取 .env 配置
│   ├── services/
│   │   ├── document_service.py       # 文档解析、切分（多格式 + 长度控制）
│   │   ├── embedding_service.py      # 向量化（阿里云）
│   │   ├── knowledge_base_service.py # 向量库读写、检索、对账、重载
│   │   ├── rag_service.py            # 全库问答编排（检索 + 阈值过滤 + 生成）
│   │   └── answer_service.py         # 调 DeepSeek 生成回答
│   └── schemas/              # 数据模型
├── frontend/                 # 前端（Vue 3 + Vite）
│   ├── src/
│   │   ├── views/            # ChatView / ArchiveView / OverviewView
│   │   ├── components/       # UploadModal / UploadProgressModal
│   │   ├── composables/      # useSessions / useDocMeta / useUploadTasks
│   │   └── api/client.ts     # 后端接口封装
│   └── package.json
├── data/
│   ├── documents/            # 上传的文档
│   └── chroma/               # 向量库持久化
├── tests/                    # 后端测试（unittest）
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

**3. 配置环境变量**：复制 `.env.example` 为 `.env`，填入真实 API Key。

> 真实 Key 只写在 `.env`，切勿写入代码或提交仓库。

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
或双击 `frontend/启动前端.bat`。浏览器打开 `http://localhost:5173`。

> 前端通过 Vite 代理把 `/api` 转发到后端 8000 端口，无需额外配置跨域。

---

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 健康检查 |
| GET | `/documents` | 文档列表（含 txt/md/pdf/docx） |
| GET | `/stats` | 知识库统计（文档数、片段数、每文档片段数） |
| POST | `/documents/upload` | 上传文档并入库（支持 txt/md/pdf/docx；解析失败或空内容会删除文件并报错） |
| POST | `/documents/ingest` | 将已存在的文件入库 |
| DELETE | `/documents/{filename}` | 删除文档及其向量片段 |
| POST | `/rag/ask` | 全库问答，返回 answer + sources |
| POST | `/maintenance/reconcile` | 数据对账，清理僵尸片段 |
| POST | `/maintenance/reload` | 重载向量库，加载最新数据 |

### 问答接口示例

请求 `POST /rag/ask`：
```json
{ "question": "怎么读取文档内容？" }
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
  - 过短的标题/目录碎片 → 合并到相邻正文（min 60 字）
  - 过长的段落（如 PDF 整页）→ 二次切分（按换行 / 句末标点 / 长度，max 250 字）
- 目的：既不产生无意义碎片，也不让大块文本稀释语义，保证检索精度。

**检索**（`knowledge_base_service.search` + `rag_service`）
- 多召回候选 → 过滤过短碎片 → 取 top_k（不足则补齐保底）
- 距离超过 `RAG_MAX_DISTANCE` 的片段视为不相关而丢弃
- 命中片段拼成资料，交由 DeepSeek 依据资料作答

---

## 测试

```powershell
python -m unittest discover -s tests
```
当前 45 个测试。普通测试使用 fake provider，不会调用真实阿里云 / DeepSeek API。

---

## 常见问题

**Q：在外部脚本重新入库后，问答检索不到新数据？**
后端进程启动时会缓存向量库连接。外部改动数据后，点前端「重载知识库」按钮（或 `POST /maintenance/reload`），或重启后端即可。

**Q：删除文档后，片段数/图表仍显示它？**
可能是直接在文件夹删了文件、没走前端删除按钮，导致向量残留。点「数据对账」清理即可。

**Q：上传大文件（如大 PDF）很慢？**
Embedding 采用分批批量调用（默认每批 10 条），相比逐个调用大幅提速。超大文档仍需一定时间，属正常现象。

---

## 说明

本项目用于学习 Python 项目结构、FastAPI 后端、Vue 前端、文档解析与切分、向量数据库、RAG 检索问答与企业级知识库设计。
