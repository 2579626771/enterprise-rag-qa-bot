# CLAUDE.md — 项目记忆入口

## 🧭 每次会话开始必读

**在开始任何工作前，先读项目根目录的 `PROJECT_STATUS.md`** —— 它是本项目的"会话记忆锚点"，包含：当前进度、已完成、待办全景、怎么启动、关键决策与坑。不读它就等于丢失了全部上下文。

工作有进展后，**及时把进度回写到 `PROJECT_STATUS.md`**（尤其"已完成""待办""未提交改动"三节），保证下次会话不断片。

## 项目一句话

企业级多租户 RAG 问答系统（FastAPI + Chroma + 阿里云embedding + DeepSeek + Vue3）。已完成核心链路、认证、多租户隔离、答案层研判防幻觉；完成度约 85%，主要剩部署工程化与检索质量深化。

## 铁律（最容易踩的坑）

1. **启动后端必须带 `NO_PROXY`**（公司代理会拦阿里云/DeepSeek，否则问答挂）——用 `启动后端.bat` 或手动设 `NO_PROXY`。
2. **必须用 `.venv`** 的 python，不是全局 python。
3. **多租户隔离是红线**：任何"全部/跨库/扩大范围"的功能，普通用户只能看自己的库；改这类功能必配隔离回归测试。
4. **改检索/研判后**，用 `eval/qa_set.json` 跑 `scripts/eval_*.py` 出 before/after 数字，再决定去留。
5. 跑测试：`.venv/Scripts/python.exe -m unittest discover -s tests`（现 170 全绿）。

## 详细文档
- 进度/待办：`PROJECT_STATUS.md`（本目录）
- 每日工作：`../../Thinking_and_learning/Enterprise_RAG/daily_tasks.md`
- 技术复盘：`../../Thinking_and_learning/Enterprise_RAG/KNOWLEDGE_NOTES.md`（#1–#77）
