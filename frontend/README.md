# Enterprise RAG QA Bot Frontend

Vue 3 + Vite + TypeScript 前端工作台，提供知识库问答、文档管理、账号中心、问题反馈、通知中心和管理员控制台。

## 启动

```bash
npm install
npm run dev
```

默认开发地址为 `http://localhost:5173`。开发服务器会把 `/api/*` 请求代理到 `http://127.0.0.1:8000`，请先启动后端。

## 脚本

```bash
npm test       # Vitest 单元测试
npm run build  # 类型检查 + 生产构建
```

## 页面概览

| 页面 | 说明 |
| --- | --- |
| 登录 / 注册 / 忘记密码 | 账号登录、自助注册、三问答密码找回 |
| 智能问答 | 选择知识库范围、发起问答、查看来源、会话管理 |
| 我的知识库 | 创建知识库、上传文档、分类、统计、维护和 DOCX 重切分 |
| 检索配置 | 系统、租户、知识库三级检索参数配置 |
| 个人中心 | 查看账号信息、修改显示名和密码、维护找回问题 |
| 问题反馈 | 提交问题、上传截图、查看管理员回复并确认关闭 |
| 管理员页面 | 用户、知识库、配额申请、反馈、通知和模型用量管理 |

## 主要目录

```text
src/api/          后端接口封装和类型
src/components/   通用组件
src/composables/  登录态、知识库、会话、主题和上传任务状态
src/layouts/      应用布局
src/router/       路由和权限守卫
src/views/        页面
src/test/         Vitest 测试初始化
```

## 发布说明

生产构建产物位于 `frontend/dist/`，属于构建副产物，不提交源码仓库。Docker 部署时由 `frontend/Dockerfile` 构建并交给 Nginx 托管。
