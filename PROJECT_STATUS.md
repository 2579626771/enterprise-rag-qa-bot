# PROJECT STATUS — 企业级 RAG 问答系统

> **这份文件是"会话记忆锚点"**：任何新会话开始时，先读这份文件即可恢复完整上下文——当前进度、已完成、待办、怎么启动、有哪些坑。
> 每完成一块工作就更新这里。详细技术复盘见 `../Thinking_and_learning/Enterprise_RAG/KNOWLEDGE_NOTES.md`（#1–#77），每日进度见同目录 `daily_tasks.md`。
>
> **最后更新：2026-08-14（晚·阶段1 LangChain 地基 + 阶段3 rerank）**

---

## 0. 一句话现状

企业级多租户 RAG 问答系统，核心链路 + 认证 + 多租户隔离 + **答案层研判防幻觉** 均已完成并真机验证。整体完成度 **约 87%**（面向"企业级可上线"）。**唯一剩的 P0 是部署工程化**；检索质量专线：LangChain 地基已落地，rerank 已接入但**评测证明整体伤召回、默认关**（详见 §3/§4.A），下一步价值点转向 **调 rerank 融合策略** 或 **多查询改写**。

---

## 1. 技术栈与架构（快速回忆）

- **后端**：FastAPI（`app/api.py` 单文件路由）+ 服务层 `app/services/*`
- **向量库**：Chroma（持久化 `data/chroma/`），单 collection + `where={"kb_id"}` 过滤做多租户隔离
- **Embedding**：阿里云百炼（`embedding_service.py`，1024维，带重试/批量/并发）
- **作答 LLM**：DeepSeek（`answer_service.py`，urllib 直连）
- **研判 LLM**：DeepSeek via LangChain `ChatOpenAI`（`judge_service.py`，防幻觉）
- **持久化**：MySQL（用户/知识库/配额/文档元数据/会话历史/主题分类；均"双仓库=MySQL+内存自动降级"骨架）
- **认证**：JWT + bcrypt，角色 admin/user
- **前端**：Vue3 + Vite + TS，vue-router，Element Plus；`frontend/src/`
- **测试**：unittest，170 个全绿；`python -m unittest discover -s tests`

---

## 2. 怎么启动 / 验证（照抄即可）

```bash
# 后端（必须用 .venv，且需要 NO_PROXY 绕过公司代理，否则问答挂！）
cd D:/ClaudeWorkspace/Projects/enterprise-rag-qa-bot-main
# 双击 启动后端.bat（已内置 NO_PROXY），或手动：
NO_PROXY="*" .venv/Scripts/python.exe -m uvicorn app.api:app --host 127.0.0.1 --port 8000

# 前端
cd frontend && npm run dev   # http://localhost:5173

# 登录：admin / admin123
# 跑测试
.venv/Scripts/python.exe -m unittest discover -s tests
# 检索层评测（不调LLM研判）
.venv/Scripts/python.exe -m scripts.eval_retrieval --top-k 5 --save eval/xxx.json
# 研判层评测（真调 DeepSeek，~8s/题）
.venv/Scripts/python.exe -m scripts.eval_answer --save eval/xxx.json
```

关键 `.env` 开关：`JUDGE_ENABLED=true`（研判防幻觉，默认建议关，现开着测试中）、`ANSWER_PROVIDER=deepseek`、`EMBEDDING_PROVIDER=aliyun`、`MYSQL_ENABLED=true`。

---

## 3. ✅ 已完成（截至 2026-08-14）

**基础平台（08-11 ~ 08-13，已提交）**
- 全栈 RAG：多格式解析(txt/md/pdf/docx)、切分优化、批量embedding、来源溯源
- 认证鉴权：JWT+bcrypt+角色、自助注册
- **多租户隔离**：kb_id 贯穿向量/文件/元数据；配额申请审批
- 会话历史落库、主题分类按库隔离、文档目录物理隔离、知识库管理三级主从导航

**检索质量专线（08-14，未提交）**
- **阶段 0**：建 62 题评测集（含 21 hard-negative）+ `scripts/eval_retrieval.py`/`eval_answer.py`。
  数据结论：正例召回已 94.7%，真短板是**幻觉**（基线 hard-neg 拒答率 0%、幻觉风险 91.7%）；
  距离阈值无法区分"能答/不能答"（区间重叠）。→ 方向锁定"防幻觉优先"。
- **阶段 A**：答案层"研判"防幻觉（`judge_service.py`，LangChain ChatOpenAI+DeepSeek，一次调用判研+作答）。
  `JUDGE_ENABLED` 开关；研判失败自动降级放行。
  **结果：幻觉风险 91.7%→8.3%，正例保持 94.7% 零误伤**（`eval/result_judge_v2.json`）。
- **阶段 B**：拒答/低可信前端徽标 + verdict 持久化（chat_messages 加 verdict 列，切换/刷新会话徽标仍在）。
- **知识库选择器**：问答页输入框左侧下拉，默认"全部"；普通用户"全部"=只查自己的库（隔离），管理员=真全库。3 个隔离回归测试。
- **部署坑排查**：NO_PROXY、truststore SSL、SSL_CERT_FILE 防御、DeepSeek 不支持结构化输出→改JSON解析、端口僵尸进程。

测试 159 → **170 全绿**。

**检索配置页（08-14 晚，未提交）**
- **阶段 5：检索配置页三级配置层次**（系统默认 / 租户默认 / 按知识库），top_k/阈值/研判开关/作答提示词
  在线可调、存 MySQL，无需改 .env 重启。多/全库查询用哪份配置由租户 `multi_scope` 偏好决定（配置页设，聊天页不选）。
  - 新增 `app/services/retrieval_config_service.py`（照 kb_service 双仓库骨架，表 `retrieval_configs`，
    `resolve_effective` 三级解析 kb→tenant→system→硬默认）。
  - **破解 import-time 常量快照坑**：`answer_from_knowledge_base` 新增 `max_distance/judge_enabled/answer_prompt`
    形参，`/rag/ask` 先 `resolve_effective` 再显式传入——否则改库不生效（详见坑#7）。
  - `answer_service` 抽 `DEFAULT_ANSWER_PROMPT` 常量、支持 `answer_prompt` 覆盖。
  - api 加 GET/PUT/DELETE `/config/retrieval`（system 仅管理员、kb 走 require_kb_access 隔离）。
  - 前端：`client.ts` 加接口；`ConfigPlaceholder.vue` 占位→三分区真实页 + 新增 `components/ConfigForm.vue`。
  - 测试：新增 `tests/test_retrieval_config_service.py`（解析优先级/多全库偏好/隔离回归/仅管理员），
    扩 `test_rag_service.py`（参数覆盖生效）。**170 → 184 全绿**。前端 vue-tsc 通过。已提交 `c624191`。

**检索质量专线：阶段1 LangChain 地基 + 阶段3 rerank（08-14 晚，未提交）**
- **阶段 1：LangChain 适配层（地基，已落地）**
  - 新增 `app/services/langchain_adapters.py`：`AliyunEmbeddings`（鸭子类型 Embeddings，委托 embedding_service，
    尊重 fake）；`build_chroma_vectorstore(client, collection_name)` 用 `langchain_chroma.Chroma` 包住**已存在的
    公共 client + 集合**（照抄 judge_service 的 truststore/SSL 内网防御，惰性 import）。
  - `knowledge_base_service.search()` 的召回改经 `similarity_search_with_score`；**实测 score == 原生 Chroma
    余弦距离，逐位一致**（eval 距离最大差 2e-4，纯 API 浮点抖动），distance 语义零漂移、指标与 legacy 完全一致。
  - **踩坑记**：langchain_chroma 要**公共 Client**（`chromadb.Client`），不能传 `collection._client`（那是底层
    RustBindingsAPI，会崩）；`_set_collection_for_test` 加可选 client 参数、缺省时从注入集合重建公共 Client。
    构造用 `create_collection_if_not_exists=False`（集合必已存在）。→ 详见新坑 §6.8。
- **阶段 3：rerank 重排（已接入，评测后默认关）**
  - 新增 `app/services/rerank_service.py`：阿里云 **gte-rerank-v2**（urllib 直连，复用 ALIYUN_API_KEY，
    仿 embedding_service 重试）；`RERANK_PROVIDER=fake` 确定性分支；**失败降级为原顺序**，绝不中断检索。
    端点 `.../api/v1/services/rerank/text-rerank/text-rerank`，响应 `output.results[].{index,relevance_score}`。
  - `search()` 召回后、截 top_k 前用 rerank **只重排候选顺序、保留每条原向量 distance**（阈值/研判语义不受影响）。
    config 加 `RERANK_ENABLED`(默认 false)/`RERANK_PROVIDER`/`ALIYUN_RERANK_MODEL`/`ALIYUN_RERANK_URL`。
  - 测试：新增 `test_rerank_service.py`（排序/降级/top_n）、扩 `test_rag_service.py`（rerank 开关 + distance 保留）、
    扩 `test_kb_isolation.py`（**rerank 开启下隔离红线回归**，菠萝泄露断言）。**184 → 193 全绿**。
  - **⚠️ 评测结论（真调阿里云 before/after，`eval/result_lc_base.json` vs `eval/result_rerank.json`）**：
    rerank **整体伤召回** —— Hit@5 **94.7%→89.5%**（#58/#62 两道口语化/多意图正例掉出 top5），
    虽 7 题排名上升、MRR 0.776→0.781、hard-neg 拒答 0→4.8%、幻觉风险 91.7%→87.5% 微升，**且未修好 #8/#55**。
    → 决策：**代码/开关/测试全保留，默认 `RERANK_ENABLED=false`**（可一键开）；作为已验证的负面结论归档，
    下一步优先**调 rerank 融合策略**（只重排 top_k*2、或 rerank 分与距离加权）或**多查询改写**。

---

## 4. ⬜ 待办（剩余任务全景）

### A. 检索质量专线（当前主战场，评测驱动）
- ✅ **阶段 1：LangChain 适配层**（08-14 晚完成）：阿里云 embedding 包成 Embeddings、Chroma 召回接 `langchain_chroma`，
  距离零漂移。作为 rerank/多查询的地基。
- ⚠️ **阶段 3：Rerank 重排**（08-14 晚接入，**评测证明伤召回、默认关**）：gte-rerank-v2 API 已接，
  Hit@5 94.7%→89.5%，未修 #8/#55。代码/开关保留。**下一步：调融合策略再评**（只重排 top_k*2 或分数加权）。
- ⬜ **阶段 4：多查询改写**（召回补强）——rerank 不理想后，这可能是更稳的召回增强项，可优先。
- ⬜ 阶段 2：混合检索 BM25+jieba（**已降级**，召回无短板，收益存疑，靠后）
- ⬜ 阶段 6：降级开关 `RETRIEVAL_MODE`、补测、README、（可选）LangSmith

### B. 离"可上线"还差的（专线之外）
- ⬜ **P0 部署方案**（唯一硬门槛）：后端 Docker 化 + 前端构建托管 + Nginx 反代 + 生产 `.env` + 进程守护。**别忘 NO_PROXY！**
- ⬜ P1 账号体验：**修改密码 / 找回密码 / 登录失败次数限制**（评测里这些还是 TODO，问就拒答）
- ⬜ P1 流式输出（打字机）：研判现在 8-15s/次，流式能大幅改善体感
- ⬜ P1 前端自动化测试（目前为 0）
- ⬜ P1 统一存量 docx 切分

### C. 收尾杂项
- ⬜ 研判性能：换非 thinking 模型专做研判（现在慢）

---

## 5. ✅ 提交状态

- `078fe3b` 研判/徽标/选择器（08-14 白天）——已提交
- `c624191` **阶段5 检索配置页**（三级参数在线可调，存 MySQL）——已提交，184 测试全绿
- `75e915b` docs 修正 §5——已提交
- **阶段1 LangChain 地基 + 阶段3 rerank（本次）**：待提交（见下方文件清单）。193 测试全绿。
  - 新增：`app/services/langchain_adapters.py`、`app/services/rerank_service.py`、
    `tests/test_rerank_service.py`、`eval/result_lc_base.json`、`eval/result_rerank.json`
  - 修改：`app/services/knowledge_base_service.py`、`app/config.py`、`.env`、
    `tests/test_rag_service.py`、`tests/test_kb_isolation.py`、`PROJECT_STATUS.md`
  - 建议提交信息：`feat: 检索质量专线 阶段1 LangChain 地基 + 阶段3 rerank(默认关，评测伤召回归档)`
- 本地 `master` 领先 `origin/main`，尚未 `git push`（等确认后再推）。

> 下一战场：**P0 部署工程化**（唯一硬门槛）或 **检索专线阶段4 多查询改写 / 调 rerank 融合**。

---

## 6. 关键决策与坑（避免重复踩/重复讨论）

1. **要不要引 LangChain/LangGraph**：已定——打磨检索质量引 LangChain（绞杀者模式，只接管增强层）；LangGraph 等有 Agent/回环需求再说。研判层因需 structured 让 LangChain 破例进了主链路，用 JUDGE_ENABLED 开关兜底。
2. **防幻觉为何在答案层不在检索层**：评测证明距离阈值分不开能答/不能答（区间重叠），只能靠 LLM 语义研判。
3. **"全部知识库"的安全线**：普通用户"全部"只能是"自己所有库"，绝不能真全库（会泄露他人数据）。改这类"扩大范围"功能必配隔离回归测试。
4. **内网部署三件套**：代理(NO_PROXY)、证书(truststore)、端口(僵尸进程)。LLM功能"本地能调通≠部署能用"。
5. **DeepSeek thinking 模型**不支持 response_format/强制 tool_choice → 研判用"提示输出JSON+正则解析"，别用 with_structured_output。
6. **评测集是尺子**：任何"提升质量"的改动，先用 `eval/qa_set.json` 跑 before/after，数字说话再进下一步。
7. **import-time 常量快照坑**：`rag_service` 用 `from app.config import RAG_TOP_K, RAG_MAX_DISTANCE, JUDGE_ENABLED`
   把值绑成了模块自己的名字（import 时一次性快照）。**在线改配置光写库不会生效**，必须让运行时读取路径拿到新值。
   阶段5 的解法：把这三项（+answer_prompt）做成 `answer_from_knowledge_base` 的显式形参，由 `/rag/ask`
   先 `retrieval_config_service.resolve_effective()` 解析再传入。改这类"配置驱动行为"务必检查是否走了运行时读取。
8. **langchain_chroma 要公共 Client、不要私有 bindings**：`langchain_chroma.Chroma(client=...)` 必须传
   `chromadb.Client`（EphemeralClient/PersistentClient 返回值），**不能传 `collection._client`**——那是底层
   `RustBindingsAPI`，签名/返回类型不同，`similarity_search_with_score` 会报 `'Collection' object has no
   attribute 'query'` 或 `get_or_create_collection() got unexpected kwarg embedding_function`。构造时用
   `create_collection_if_not_exists=False`（集合都是先 get_or_create 建好的）。测试注入 `_set_collection_for_test`
   缺省时从注入集合的 `_client` 重建一个公共 `Client`（复用其 `_server`）供检索用。**排错先确认传的是公共 client。**
9. **rerank 不是银弹（评测实证）**：gte-rerank-v2 对本库整体**伤召回**（Hit@5 94.7%→89.5%，口语化/多意图正例
   #58/#62 被压出 top5），MRR/幻觉风险仅微升。默认 `RERANK_ENABLED=false`。要用先跑 before/after，别凭感觉开。
