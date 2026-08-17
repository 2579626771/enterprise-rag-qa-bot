# eval —— 检索/研判质量评测

本目录用于**评测驱动**地打磨检索与研判质量：任何影响检索或研判的改动，都先用评测集跑 before/after，用数字决定去留（详见根目录 `CLAUDE.md` 铁律 #4）。

> ⚠️ **关于数据文件**：真实评测集基于内部资料标注，**不进公开仓库**（`.gitignore` 已忽略 `eval/*.json` 中的真实数据，仅放行本 README 与 `qa_set.example.json`）。真实评测集在本地 `eval/qa_set.json`，评测结果在本地 `eval/result_*.json`。
>
> 仓库内提供一份**脱敏示例** `qa_set.example.json`：结构与真实评测集**完全一致**，内容为虚构的开源软件文档场景，不含任何真实业务/内部信息，仅供理解字段 schema 与复现评测流程。

---

## 评测集字段（schema）

`qa_set.json` / `qa_set.example.json` 顶层为 `_meta` + `items`，每个 item：

| 字段 | 说明 |
|------|------|
| `id` | 题号 |
| `question` | 用户可能真实输入的问题（含口语 / 错别字） |
| `kb_id` | 该问题应在哪个知识库检索 |
| `type` | 问题类型（见下） |
| `answerable` | `true`=库里有答案（正例）/ `false`=库里没有（应拒答） |
| `gold_files` | 正例：答案应来自的文件（命中其一即算对）；拒答题为空 |
| `gold_keywords` | 正例：答案片段应含的关键信息点（用于判命中） |
| `trap_files` | 拒答题专用：会被误召回的「主题相关但不含答案」的文件（诊断幻觉来源，不参与判分） |
| `note` | 标注依据 |

**问题类型（`type`）**：`fact`（事实型）、`exact-term`（专名/编号精确匹配）、`colloquial`（口语/错别字）、`detail`（数字/细节）、`cross-file`（散落多文件）、`hard-negative`（主题相关但库里无答案，最危险的幻觉源，应拒答）、`negative`（完全无关，应拒答）、`partial`（多子问只覆盖一部分，考验是否假装全答）。

---

## 怎么跑

```bash
# 检索层评测（不调研判 LLM，出 Hit@k / MRR / 命中距离 / 拒答率）
.venv/Scripts/python.exe -m scripts.eval_retrieval --top-k 5 --save eval/result_xxx.json

# 只跑指定题并打印 topK 命中明细，适合诊断 hard case
.venv/Scripts/python.exe -m scripts.eval_retrieval --ids 8,55 --top-k 5 --show-hits --show-content

# 临时覆盖检索模式 / 邻近上下文 / rerank 策略，不必改 .env
.venv/Scripts/python.exe -m scripts.eval_retrieval --top-k 5 --retrieval-mode vector --context-window 1 --save eval/result_context_window.json
.venv/Scripts/python.exe -m scripts.eval_retrieval --top-k 5 --retrieval-mode rerank_fusion --rerank-strategy weighted --save eval/result_rerank_fusion_weighted.json

# 单题入库形态诊断：打印 top hits、gold 文件关键词所在 chunk 与邻近 chunk
.venv/Scripts/python.exe -m scripts.diagnose_retrieval_case --ids 8 --top-k 5

# 研判层评测（真调 DeepSeek，~8s/题，出幻觉风险 / 拒答率）
.venv/Scripts/python.exe -m scripts.eval_answer --save eval/result_xxx.json
```

> 脚本默认读取 `eval/qa_set.json`。若只想跑脱敏示例，把 `qa_set.example.json` 复制为 `qa_set.json` 即可（示例的 `kb_id` 需对应你本地实际存在的知识库，否则检索为空）。

结果文件（`result_*.json`）结构：`top_k` / `reject_threshold` / `ids` / `metrics`（聚合指标）/ `distance_dist`（距离分布）/ `results`（逐题明细）。保存结果或开启 `--show-hits` 时，逐题明细会额外包含 top chunks、命中关键词和 `combined_hit`（topK 合并证据命中，用于诊断跨 chunk 证据，不替代主 Hit@K）。

---

## 真实评测达成的关键指标（供参考，纯数字不涉密）

基于真实评测集（62 题，含 21 道 hard-negative）：

| 改动 | 关键指标 | 结论 |
|------|---------|------|
| **答案层研判防幻觉** | 幻觉风险 **91.7% → 8.3%**，正例召回保持 **94.7% 零误伤** | ✅ 采用（`JUDGE_ENABLED` 开关） |
| **邻近上下文扩展** | `RETRIEVAL_CONTEXT_WINDOW=1` 后 Hit@5 **94.7% → 100%**、MRR **0.776 → 0.845**，#8/#55 修复 | ✅ 质量优先时推荐评测后开启 |
| **多查询改写** | MRR **0.776 → 0.807**、平均命中距离 0.224→0.214、Hit@5 **零误伤** | ✅ 正向，因慢默认关（`MULTI_QUERY_ENABLED` / `RETRIEVAL_MODE=multi_query`） |
| **rerank 重排** | Hit@5 **94.7% → 89.5%**（口语/多意图正例被压出 top5） | ⚠️ 旧 pure rerank 伤召回，默认关归档（`RERANK_ENABLED`） |
| **rerank 融合 weighted** | Hit@5 保持 **94.7%**、MRR **0.776 → 0.794** | 可选；不再伤 Hit@5，但未修 #8/#55 |
| **BM25+jieba hybrid** | Hit@5 **92.1%**、MRR **0.732** | ⚠️ 单开伤召回，代码保留默认不开 |

> 结论一句话：本库检索的正例召回已很高（94.7%），真短板首先是**幻觉**（主题相关但库里无答案时硬编），故防幻觉优先放在**答案层**（距离阈值无法区分能答/不能答，区间重叠）；剩余 #8/#55 这类漏召回根因是**相邻 chunk / 跨 chunk 证据**，优先用邻近上下文扩展处理，而不是继续盲目叠 rerank/hybrid。
