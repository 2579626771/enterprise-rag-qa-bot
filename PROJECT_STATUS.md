# PROJECT STATUS — 企业级 RAG 问答系统

> **这份文件是"会话记忆锚点"**：任何新会话开始时，先读这份文件即可恢复完整上下文——当前进度、已完成、待办、怎么启动、有哪些坑。
> 每完成一块工作就更新这里。详细技术复盘见 `../Thinking_and_learning/Enterprise_RAG/KNOWLEDGE_NOTES.md`（#1–#83），每日进度见同目录 `daily_tasks.md`。
>
> **最后更新：2026-08-17（完成 P1 账号体验闭环 + 管理员模型用量监控 + 检索质量 #8/#55 诊断修复 + rerank 融合 + BM25+jieba 混合检索 + RETRIEVAL_MODE 阶段6收尾）**

---

## 0. 一句话现状

企业级多租户 RAG 问答系统，核心链路 + 认证 + 多租户隔离 + **答案层研判防幻觉** 均已完成并真机验证，P1 账号体验 + 个人中心已补齐（改密/管理员重置/登录失败锁定/3 问题自助找回密码），并新增用户问题反馈 + 多截图附件 + 管理员处理回复闭环、管理员通知下发 + 用户消息中心、管理员模型用量监控、问答前端打字机式渐进输出、前端自动化测试地基、存量 DOCX 统一重切分维护能力。整体完成度 **约 96%**（面向"企业级可上线"）。**唯一剩的 P0 是部署工程化**；检索质量专线：LangChain 地基已落地；rerank / 多查询 / BM25+jieba / 邻近上下文 / `RETRIEVAL_MODE` 均已接入且评测驱动。#8/#55 根因已确认是相邻 chunk/跨 chunk 证据，`RETRIEVAL_CONTEXT_WINDOW=1` 可修复（Hit@5 94.7%→100%）；hybrid 单开伤召回，默认不开。

---

## 1. 技术栈与架构（快速回忆）

- **后端**：FastAPI（`app/api.py` 单文件路由）+ 服务层 `app/services/*`
- **向量库**：Chroma（持久化 `data/chroma/`），单 collection + `where={"kb_id"}` 过滤做多租户隔离
- **Embedding**：阿里云百炼（`embedding_service.py`，1024维，带重试/批量/并发）
- **作答 LLM**：DeepSeek（`answer_service.py`，urllib 直连）
- **研判 LLM**：DeepSeek via LangChain `ChatOpenAI`（`judge_service.py`，防幻觉）
- **持久化**：MySQL（用户/知识库/配额/问题反馈/通知/模型用量/文档元数据/会话历史/主题分类；均"双仓库=MySQL+内存自动降级"骨架）
- **认证**：JWT + bcrypt，角色 admin/user
- **前端**：Vue3 + Vite + TS，vue-router，Element Plus；`frontend/src/`
- **测试**：后端 unittest，280 个全绿；前端 Vitest，12 个全绿；`.venv/Scripts/python.exe -m unittest discover -s tests` / `npm test`

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
cd frontend && npm test && npm run build
# 检索层评测（不调LLM研判）
.venv/Scripts/python.exe -m scripts.eval_retrieval --top-k 5 --save eval/xxx.json
# 指定题诊断 / 模式覆盖
.venv/Scripts/python.exe -m scripts.eval_retrieval --ids 8,55 --top-k 5 --show-hits
.venv/Scripts/python.exe -m scripts.eval_retrieval --top-k 5 --retrieval-mode vector --context-window 1 --save eval/xxx.json
# 研判层评测（真调 DeepSeek，~8s/题）
.venv/Scripts/python.exe -m scripts.eval_answer --save eval/xxx.json
```

关键 `.env` 开关：`JUDGE_ENABLED=true`（研判防幻觉，默认建议关，现开着测试中）、`ANSWER_PROVIDER=deepseek`、`EMBEDDING_PROVIDER=aliyun`、`MYSQL_ENABLED=true`、`RETRIEVAL_MODE=auto`（默认兼容旧行为）、`RETRIEVAL_CONTEXT_WINDOW=0`（质量优先可设 1，已修复 #8/#55）、`MODEL_USAGE_ALERT_*`（管理员模型监控告警阈值）。

---

## 3. ✅ 已完成（截至 2026-08-17）

**基础平台（08-11 ~ 08-13，已提交）**
- 全栈 RAG：多格式解析(txt/md/pdf/docx)、切分优化、批量embedding、来源溯源
- 认证鉴权：JWT+bcrypt+角色、自助注册
- **多租户隔离**：kb_id 贯穿向量/文件/元数据；配额申请审批
- 会话历史落库、主题分类按库隔离、文档目录物理隔离、知识库管理三级主从导航

**P1 账号体验 + 个人中心（08-17，本次完成）**
- 后端用户服务扩展账号安全字段：失败次数、锁定到期、上次登录、密码更新时间、强制改密标记；MySQL 自动补列，内存仓库同步支持。
- 登录改走 `authenticate()`：连续输错达到 `LOGIN_MAX_FAILED_ATTEMPTS` 后按 `LOGIN_LOCK_MINUTES` 短时锁定；成功登录清失败计数。
- 新增当前用户资料/改密接口：`PATCH /auth/me`、`POST /auth/password/change`；改密成功清除强制改密与锁定状态。
- 新增管理员重置密码：`POST /users/{id}/password-reset`，默认要求用户下次登录先改密；重置会清除锁定。管理员不能用该接口重置自己，自己改密走个人中心。
- 前端新增 `ProfileView.vue` 个人中心，顶栏入口可达；管理员账户管理页增加登录安全状态和重置密码弹窗。
- 自助找回密码闭环：注册页强制设置 3 组自定义问题/答案；登录页新增“忘记密码？”入口与 `ForgotPasswordView.vue`；未登录用户必须按登录用户名取问题（不允许显示名）、答对 3 题后重置密码；个人中心可维护/覆盖找回问题。答案仅存 bcrypt hash，不明文返回。
- 测试：`test_auth.py` 扩到 41 项；全量后端 **219 全绿**；前端 `npm run build` 通过（仅 Vite 体积/第三方注释警告）。

**P1 问题反馈与解决窗口（08-17，本次完成）**
- 新增 `app/services/feedback_service.py`：`feedback_tickets` + `feedback_attachments` 双仓库（MySQL 自动建表 + 内存降级），状态流转 `pending → processing → resolved → closed`。
- 新增反馈 API：用户 `POST /feedback`、`GET /feedback/mine`、`POST /feedback/{id}/close`；管理员 `GET /feedback/admin?status=`、`PATCH /feedback/admin/{id}`。
- 补充截图附件：`POST /feedback/{id}/attachments` 支持多图上传（默认最多 5 张、单张 5MB，仅 png/jpg/jpeg/webp/gif，禁 svg）；`GET /feedback/{id}/attachments/{attachment_id}` 经鉴权下载，本人或管理员可看。
- 前端新增 `FeedbackView.vue` 用户问题反馈页：提交反馈、可附多张截图、查看自己的处理状态/管理员回复、打开截图、对已回复反馈确认关闭。
- 前端新增 `AdminFeedbackView.vue` 管理员反馈处理页：按状态筛选、查看反馈与截图、填写处理回复、流转处理中/已解决/已关闭。
- 导航与指南补齐：侧栏增加“问题反馈”和管理员“反馈处理”，`GuideView` 增加问题反馈说明。
- 测试：新增 `test_feedback_service.py` + `test_feedback_api.py`，反馈相关 25 项；全量后端 **244 全绿**；前端 `npm run build` 通过（仅既有 Vite/rollup 体积与注释警告）。

**P1 管理员通知下发 + 用户消息中心（08-17，本次完成）**
- 新增 `app/services/notification_service.py`：`notifications` + `notification_recipients` 双仓库（MySQL 自动建表 + 内存降级），每个收件人独立 `unread/read/closed` 状态。
- 新增通知 API：用户 `GET /notifications/mine`、`GET /notifications/unread-count`、`POST /notifications/{id}/read`、`POST /notifications/{id}/close`；管理员 `POST /notifications/admin`、`GET /notifications/admin`。
- 前端顶栏「通知」消息中心：显示未读 badge，打开下拉可查看消息、确认已读或关闭；有未读通知时中央弹窗提醒。
- 新增 `AdminNotificationsView.vue` 管理员通知下发页：可发全部用户或指定用户，展示收件数、未读/已读/关闭统计。
- 导航与指南补齐：管理员侧栏增加“通知下发”，`GuideView` 增加通知与消息中心说明。
- 测试：新增 `test_notification_service.py` + `test_notification_api.py` 共 15 项；全量后端 **259 全绿**；前端 `npm run build` 通过（仅既有 Vite/rollup 体积与注释警告）。

**P1 管理员模型用量监控（08-17，本次完成）**
- 新增 `app/services/model_usage_service.py`：`model_usage_records` 双仓库（MySQL 自动建表 + 内存降级），记录 user_id/kb_id/request_id、模型类型、provider/model、operation、成功/失败、token、延迟、错误信息。
- 用 `contextvars` 做调用上下文归因：`/rag/ask`、文档入库、DOCX 重切分设置 user/kb/request，上游 embedding/answer/judge/query_rewrite/rerank 自动记录，监控写入失败只打 warning 不影响主流程。
- 新增管理员 API：`GET /admin/model-usage/summary`、`/records`、`/alerts`，支持按天数/用户/模型类型/成功失败筛选，API 层补 username/display_name。
- 告警规则：失败率、平均延迟、用户 token 消耗阈值由 `MODEL_USAGE_ALERT_*` 配置；第一版实时计算展示，不做外部推送。
- 前端新增 `AdminModelUsageView.vue` 与侧栏“模型监控”：KPI 卡、异常告警、按模型类型统计、按用户归因、最近调用明细。
- 测试：新增 `tests/test_model_usage_service.py` + `tests/test_model_usage_api.py`，全量后端 **280 全绿**；前端 **Vitest 12 全绿**；`npm run build` 通过（仅既有 Vite/rollup 警告）。

**P1 流式输出/打字机（08-17，本次完成）**
- `ChatView.vue` 增加前端打字机式渐进输出：后端完整回答返回后，assistant 气泡按小块逐步展示，并显示光标。
- 保留研判徽标、来源展示与会话持久化：打字完成后再写入服务端会话历史，刷新后仍是完整回答。
- 说明：本轮是前端打字机，不是后端 token streaming；不改变 RAG/研判语义，低风险改善体感。若要降低首字延迟，后续再拆 DeepSeek streaming/SSE。
- 验证：全量后端 **259 全绿**；前端 `npm run build` 通过（仅既有 Vite/rollup 体积与注释警告）。

**P1 前端自动化测试（08-17，本次完成）**
- 前端接入 Vitest + Vue Test Utils + jsdom：`package.json` 新增 `npm test` / `npm run test:watch`，`vite.config.ts` 增加测试环境与 `src/test/setup.ts`。
- 首批测试覆盖 `useAuth` 登录/注册/持久化/401 清理跳转、路由守卫（未登录、公开页、管理员页、强制改密）、问题反馈截图格式校验与提交后上传截图。
- 验证：前端 **3 个测试文件 / 12 项全绿**；`npm run build` 通过（仅既有 Vite/rollup 体积与注释警告）。

**P1 统一存量 DOCX 切分（08-17，本次完成）**
- `knowledge_base_service.rechunk_docx_documents(kb_id, scope_dir)`：按当前 DOCX 解析与段落切分策略重建某知识库下所有 `.docx` 文档；每个文件先按 `kb_id + filename` 删除旧向量片段，再重新解析、切分、embedding、upsert，避免旧 chunk_index 残留。
- 新增维护 API：`POST /maintenance/rechunk-docx?kb_id=`，复用 `require_kb_access`，普通用户只能处理自己的库，管理员可处理任意库；单文件失败不中断整批并回写元数据 `失败` + error。
- 前端知识库文档页新增「统一 DOCX 切分」按钮，执行前确认，完成后展示成功/失败汇总并刷新文档列表与统计。
- 测试：新增 `tests/test_docx_rechunk.py` 3 项，覆盖删除旧片段、只处理 DOCX、API 权限隔离。全量后端 **262 全绿**。

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
    扩 `test_kb_isolation.py`（**rerank 开启下隔离红线回归**，跨租户测试词泄露断言）。**184 → 193 全绿**。
  - **⚠️ 评测结论（真调阿里云 before/after，`eval/result_lc_base.json` vs `eval/result_rerank.json`）**：
    rerank **整体伤召回** —— Hit@5 **94.7%→89.5%**（#58/#62 两道口语化/多意图正例掉出 top5），
    虽 7 题排名上升、MRR 0.776→0.781、hard-neg 拒答 0→4.8%、幻觉风险 91.7%→87.5% 微升，**且未修好 #8/#55**。
    → 决策：**代码/开关/测试全保留，默认 `RERANK_ENABLED=false`**（可一键开）；作为已验证的负面结论归档，
    下一步优先**调 rerank 融合策略**（只重排 top_k*2、或 rerank 分与距离加权）或**多查询改写**。

**检索质量专线：阶段4 多查询改写（08-14 深夜，未提交）**
- 新增 `app/services/query_rewrite_service.py`：DeepSeek urllib 直连（仿 answer_service）把原问题改写成
  N 条语义等价查询；`QUERY_REWRITE_PROVIDER=fake` 确定性分支；**失败降级返回 []（只用原查询）**，绝不中断检索。
- `search()` 接入多查询：原查询 + N 条改写各召回 candidate_k，按 `(filename, chunk_index)` **去重保留最小
  distance**，合并后按距离升序交给下游 rerank/阈值。**所有查询共用同一 where=kb_id 过滤——只扩召回入口、
  不扩范围，隔离红线不受影响。** 原查询始终保底。config 加 `MULTI_QUERY_ENABLED`(默认 false)/`MULTI_QUERY_COUNT`(3)/
  `QUERY_REWRITE_PROVIDER`。
- 测试：新增 `test_query_rewrite_service.py`（改写/降级）、扩 `test_rag_service.py`（合并去重 + distance 保留）、
  扩 `test_kb_isolation.py`（**多查询开启下隔离红线回归**）。**193 → 200 全绿**。
- **✅ 评测结论（真调 DeepSeek 改写 + 阿里云 embedding，`eval/result_multiquery.json` vs `result_lc_base.json`）**：
  **正向改进** —— MRR **0.776→0.807**（3 题升到 @1）、平均命中距离 0.224→0.214、**Hit@5 保持 94.7% 零误伤**
  （优于 rerank，rerank 掉 2 道正例）。但 **#8/#55 仍未修**（detail/partial 型漏召回，改写也没召回进 top5），
  且**慢**——多一次 LLM 调用，评测 62 题跑 7+ 分钟（约 8-10s/题）。
  → 决策：**代码/开关/测试全保留，默认 `MULTI_QUERY_ENABLED=false`**（因慢，要用手动翻开；适合"质量优先胜过
  延迟"的场景）。正向结论归档。

**检索质量专线：#8/#55 诊断 + 阶段2/3/6 收尾（08-17，本次完成，待提交）**
- `scripts/eval_retrieval.py` 增强：新增 `--ids`、`--show-hits`、`--show-content`、`--retrieval-mode`、`--context-window`、`--rerank-strategy`；结果 JSON 增加 top chunk 明细与 `combined_hit`（topK 合并证据命中），用于诊断跨 chunk 证据。
- 新增 `scripts/diagnose_retrieval_case.py`：按题号打印 top hits、gold 文件关键词所在 chunk 与邻近 chunk，专门排查入库形态。
- #8 根因：命中的是标题/限制说明片段，答案短句落在相邻 chunk；同时存在数字写法差异。
- #55 根因：接口说明、字段示例与接入方式分散在同一小节多个相邻 chunk，旧单 chunk 判分会 miss。
- 新增邻近上下文扩展：`RETRIEVAL_CONTEXT_WINDOW` / `RETRIEVAL_CONTEXT_MAX_CHARS`，只扩展最终 sources 的 content，不改原 hit 的 distance/阈值语义；按 `kb_id+filename` 扩展，避免同名文件跨库串入。
- 新增阶段6模式开关：`RETRIEVAL_MODE=auto|vector|multi_query|rerank|rerank_fusion|hybrid|hybrid_rerank_fusion`；`auto` 兼容旧 `MULTI_QUERY_ENABLED`/`RERANK_ENABLED`，`vector` 是最稳降级。
- 新增 rerank 融合：`RERANK_STRATEGY=sort|window|weighted`、`RERANK_WINDOW_MULTIPLIER`、`RERANK_WEIGHT`；`weighted` 用距离归一化 + rerank 分融合，保留原 distance。
- 新增 `app/services/hybrid_search_service.py`：BM25 + jieba（缺失时分词降级）+ RRF 融合；只在已授权 where 范围内取片段，不参与范围决策。
- 评测结果：
  - baseline `result_lc_base.json`：Hit@5 **94.7%**、MRR **0.776**。
  - `RETRIEVAL_CONTEXT_WINDOW=1`（`eval/result_context_window.json`）：Hit@5 **100%**、MRR **0.845**，#8/#55 均修复；拒答/幻觉风险不变（仍靠研判层兜底）。
  - `rerank_fusion weighted`（`eval/result_rerank_fusion_weighted.json`）：Hit@5 **94.7%**、MRR **0.794**，不再像旧 pure rerank 那样伤 Hit@5，但仍未修 #8/#55。
  - `hybrid` 单开（`eval/result_hybrid.json`）：Hit@5 **92.1%**、MRR **0.732**，伤召回；代码保留，默认不开。
- 测试：新增 `tests/test_hybrid_search_service.py`，扩 `test_rag_service.py`、`test_kb_isolation.py`；该阶段完成时后端 **272 全绿**；叠加模型监控后当前全量后端 **280 全绿**。

---

## 4. ⬜ 待办（剩余任务全景）

### A. 检索质量专线（当前主战场，评测驱动）
- ✅ **阶段 1：LangChain 适配层**（08-14 晚完成）：阿里云 embedding 包成 Embeddings、Chroma 召回接 `langchain_chroma`，
  距离零漂移。作为 rerank/多查询的地基。
- ✅ **阶段 3：Rerank 融合策略**：旧 pure rerank 伤召回已归档；新增 `sort/window/weighted`，`weighted` 评测 Hit@5 **94.7%**、MRR **0.794**，不再伤 Hit@5，但不修 #8/#55。
- ✅ **阶段 4：多查询改写**（08-14 深夜完成，**评测正向、默认关**）：DeepSeek 改写原问题成 N 条，多路召回合并去重。MRR **0.776→0.807**、Hit@5 零误伤，但慢(+8-10s/题)、未修 #8/#55。代码/开关保留，`MULTI_QUERY_ENABLED=false`。
- ✅ **阶段 2：混合检索 BM25+jieba**：已接入 `hybrid_search_service` + RRF + 隔离回归；评测 Hit@5 **92.1%**、MRR **0.732**，伤召回，默认不开。
- ✅ **#8/#55 入库形态排查**：根因是相邻 chunk / 跨 chunk 证据，不是继续堆 rerank/multi-query；`RETRIEVAL_CONTEXT_WINDOW=1` 评测 Hit@5 **100%**、MRR **0.845**，两题均修复。
- ✅ **阶段 6：降级开关 `RETRIEVAL_MODE`、补测、README** 已完成；LangSmith 暂不接（外部服务，等后续真需要链路追踪再做）。

### B. 离"可上线"还差的（专线之外）
- ⬜ **P0 部署方案**（唯一硬门槛）：后端 Docker 化 + 前端构建托管 + Nginx 反代 + 生产 `.env` + 进程守护。**别忘 NO_PROXY！**
- ✅ P1 账号体验 + 个人中心（08-17 完成）：登录后个人中心、修改显示名/密码、3 问题自助找回密码、管理员重置兜底、登录失败次数限制与短时锁定。
- ✅ P1 问题反馈与解决窗口（08-17 完成）：用户侧反馈问题入口并可附多张截图；管理员侧查看截图、回复解决方法、流转状态；用户可查看处理结果并确认关闭，形成闭环。
- ✅ P1 管理员通知下发 + 用户消息中心（08-17 完成）：管理员可通知全部/指定用户；用户中央弹窗确认/关闭；顶部「使用指南」左侧新增通知入口与历史消息。
- ✅ P1 管理员模型用量监控（08-17 完成）：监控 embedding/chat/judge/query_rewrite/rerank 调用次数、token、延迟、失败率和异常告警，并按用户归因。
- ✅ P1 流式输出（打字机）（08-17 完成）：前端打字机式渐进输出，完整回答仍持久化到会话历史。
- ✅ P1 前端自动化测试（08-17 完成）：Vitest + Vue Test Utils + jsdom 地基，首批 12 项覆盖认证持久化、路由守卫、反馈截图校验/提交。
- ✅ P1 统一存量 docx 切分（08-17 完成）：按知识库维护入口/API，重建该库 DOCX 向量片段并保持多租户隔离。

### C. 收尾杂项
- ⬜ 研判性能：换非 thinking 模型专做研判（现在慢）

---

## 5. ✅ 提交状态

- `719b7d4` 研判/徽标/选择器（08-14 白天）——已提交
- `545b8b3` **阶段5 检索配置页**（三级参数在线可调，存 MySQL）——已提交，184 测试全绿
- `fbb33e9` docs 修正 §5——已提交
- `166aa09` **阶段1 LangChain 地基 + 阶段3 rerank(默认关)**——已提交，193 测试全绿
- `1dcd35f` **阶段4 多查询改写(默认关，评测 MRR 0.776→0.807 正向)**——已提交，200 测试全绿
- `330dbdb` README/.env.example/requirements 同步最新功能——已提交
- `adf3f12` 移除真实评测集/构建产物并脱敏，仅保留源码——已提交
- `f07bec1` 补脱敏示例评测集与说明——已提交
- `41decfa` 账号体验个人中心实施计划检查点——已提交（执行前回退点）
- `9f4f9cf` **P1 账号体验 + 反馈通知闭环 + 打字机 + 前端测试 + DOCX 重切分**——已提交
- **本次管理员模型用量监控 + 检索质量 #8/#55/阶段6 收尾 + 文档同步（2026-08-17）**：待提交。后端 **280 全绿**，前端 **Vitest 12 全绿**，`npm run build` 通过。
  - 新增：`app/services/model_usage_service.py`、`app/services/hybrid_search_service.py`、`scripts/diagnose_retrieval_case.py`、`tests/test_model_usage_service.py`、`tests/test_model_usage_api.py`、`tests/test_hybrid_search_service.py`、`frontend/src/views/AdminModelUsageView.vue`、`.claude/plans/retrieval-quality-hardcases-rerank-hybrid-phase6.md`、`.claude/plans/admin-model-usage-monitoring.md`
  - 修改：`app/config.py`、`app/services/embedding_service.py`、`app/services/answer_service.py`、`app/services/judge_service.py`、`app/services/query_rewrite_service.py`、`app/services/rerank_service.py`、`app/services/knowledge_base_service.py`、`app/api.py`、`scripts/eval_retrieval.py`、`tests/test_rag_service.py`、`tests/test_kb_isolation.py`、`requirements.txt`、`frontend/src/api/client.ts`、`frontend/src/router/index.ts`、`frontend/src/layouts/AppLayout.vue`、`.env.example`、`README.md`、`PROJECT_STATUS.md`、`CLAUDE.md`、`frontend/README.md`、`eval/README.md`

> 下一战场：P0 **部署工程化**（唯一硬门槛）；或继续检索质量专线（chunk 粒度/邻近上下文默认策略/更多真实 hard case 评测）。

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
