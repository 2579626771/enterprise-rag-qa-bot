# Project Status

## 当前状态

Enterprise RAG QA Bot 已具备完整的本地开发、测试和 Docker Compose 部署基础。当前公开版本聚焦源码交付，不包含任何运行时数据、真实配置、真实评测集或内部协作文档。

## 已完成能力

- 后端 RAG 主链路：文档解析、切分、Embedding、Chroma 检索、来源溯源和回答生成。
- 多知识库与多用户隔离：用户知识库、配额申请、管理员审批和跨库访问控制。
- 账号安全：JWT 登录、注册、个人中心、改密、密码找回、管理员重置密码、登录失败锁定。
- 检索配置：系统、租户、知识库三级配置，可控制 top_k、距离阈值、研判开关和回答提示词。
- 检索增强：LangChain 适配、rerank、多查询改写、BM25 + jieba 混合检索、邻近上下文扩展和模式开关。
- 运营功能：问题反馈、截图附件、管理员回复、通知中心、模型用量监控。
- 前端工作台：Vue 3 + TypeScript + Element Plus，覆盖用户端和管理员端主要页面。
- 工程化：后端 Dockerfile、前端 Nginx 镜像、Docker Compose、生产环境变量样例和基础测试。

## 当前验证项

- 后端测试：`.\.venv\Scripts\python.exe -m unittest discover -s tests`
- 前端测试：`cd frontend && npm test`
- 前端构建：`cd frontend && npm run build`
- 部署配置校验：`docker compose --env-file .env.production.example config`

## 后续建议

- 在真实部署前替换 `.env.production` 中所有占位符，并将运行时数据目录挂载到持久化存储。
- 根据业务语料继续扩展脱敏评测集，使用 `scripts/eval_retrieval.py` 和 `scripts/eval_answer.py` 做 before/after 验证。
- 若要启用 rerank、多查询改写或混合检索，先用本地评测数据确认收益和延迟成本。
- 生产环境建议接入集中日志、备份、监控告警和 HTTPS 证书自动续期。
