# PROJECT STATUS — 企业级 RAG 问答系统

> **这份文件是"会话记忆锚点"**：任何新会话开始时，先读这份文件即可恢复完整上下文——当前进度、已完成、待办、怎么启动、有哪些坑。
> 每完成一块工作就更新这里。详细技术复盘见 `../Thinking_and_learning/Enterprise_RAG/KNOWLEDGE_NOTES.md`（#1–#77），每日进度见同目录 `daily_tasks.md`。
>
> **最后更新：2026-08-14（下午）**

---

## 0. 一句话现状

企业级多租户 RAG 问答系统，核心链路 + 认证 + 多租户隔离 + **答案层研判防幻觉** 均已完成并真机验证。整体完成度 **约 85%**（面向"企业级可上线"）。**唯一剩的 P0 是部署工程化**；检索质量专线下一步是 **rerank**。

**⚠️ 今天(08-14)一大批改动尚未 git commit**（见 §5）——新会话第一件事可考虑先提交落袋。

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
    扩 `test_rag_service.py`（参数覆盖生效）。**170 → 184 全绿**。前端 vue-tsc 通过。
  - ⚠️ 真机端到端（启动前后端点一遍）+ commit 尚未做（见 §5）。

---

## 4. ⬜ 待办（剩余任务全景）

### A. 检索质量专线（当前主战场，评测驱动）
- ⬜ **阶段 3：Rerank 重排** ⭐下一个高价值项：bge-reranker，拉开"能答/不能答"分数差、修 #8/#55 漏召回。内网需验证 torch 或用 rerank API。
- ⬜ **阶段 1：LangChain 适配层**：把阿里云 embedding 包成 `Embeddings` 子类、Chroma 接 `langchain_chroma`（rerank 的地基，可与阶段3合并做）。
- ✅ **阶段 5：检索配置页**（08-14 晚完成，未提交）：三级配置层次 + 在线可调 top_k/阈值/JUDGE_ENABLED/作答prompt，存 MySQL。剩：真机端到端验证 + commit。
- ⬜ 阶段 2：混合检索 BM25+jieba（**已降级**，召回无短板，收益存疑，靠后）
- ⬜ 阶段 4：多查询改写（召回补强）
- ⬜ 阶段 6：降级开关 `RETRIEVAL_MODE`、补测、README、（可选）LangSmith

### B. 离"可上线"还差的（专线之外）
- ⬜ **P0 部署方案**（唯一硬门槛）：后端 Docker 化 + 前端构建托管 + Nginx 反代 + 生产 `.env` + 进程守护。**别忘 NO_PROXY！**
- ⬜ P1 账号体验：**修改密码 / 找回密码 / 登录失败次数限制**（评测里这些还是 TODO，问就拒答）
- ⬜ P1 流式输出（打字机）：研判现在 8-15s/次，流式能大幅改善体感
- ⬜ P1 前端自动化测试（目前为 0）
- ⬜ P1 统一存量 docx 切分

### C. 收尾杂项
- ⬜ **git commit 今天全部改动**（尚未提交，见 §5）
- ⬜ 研判性能：换非 thinking 模型专做研判（现在慢）

---

## 5. ⚠️ 未提交改动（08-14 晚：阶段5 检索配置页）

08-14 白天的一批（研判/徽标/选择器）**已提交**为 `078fe3b`。当前未提交的是**阶段5 检索配置页**：
- 新增：`app/services/retrieval_config_service.py`、`tests/test_retrieval_config_service.py`、
  `frontend/src/components/ConfigForm.vue`
- 修改：`app/api.py`、`app/services/{answer,rag}_service.py`、
  `frontend/src/api/client.ts`、`frontend/src/views/ConfigPlaceholder.vue`、`tests/test_rag_service.py`
- 追加：保存结果弹窗（成功/失败都弹）+ 按级别正确文案（系统级=所有用户；租户/kb 级=仅自己）。
  已真机验证：管理员改系统默认、普通用户改租户默认均保存成功并弹窗。

建议提交信息主题：`feat: 检索配置页（系统/租户/知识库三级参数在线可调，存 MySQL）`

**提交前建议**：启动前后端真机点一遍（管理员改系统默认→保存刷新仍在；某库设独立阈值→问答日志阈值变化；
普通用户读不到他人库配置）。

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
