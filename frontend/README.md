# Enterprise RAG · 前端

企业知识库问答系统的前端工作台，基于 **Vue 3 + Vite + TypeScript + Element Plus**。

## 启动与验证

```bash
npm install
npm run dev      # 开发服务器 http://localhost:5173
npm test         # Vitest 单元测试
npm run build    # vue-tsc 类型检查 + 生产构建
```

或双击 `启动前端.bat` 启动开发服务器。

> 需先启动后端（默认 `http://127.0.0.1:8000`）。Vite 已配置代理，把前端 `/api/*` 请求转发到后端，无需额外处理跨域。

## 页面

| 页面 | 文件 | 说明 |
|------|------|------|
| 登录 | `views/LoginView.vue` | 账密登录、登录失败提示、忘记密码入口 |
| 注册 | `views/RegisterView.vue` | 自助注册并设置 3 组找回密码问题 |
| 忘记密码 | `views/ForgotPasswordView.vue` | 按登录用户名读取问题，答对后自助重置密码 |
| 智能问答 | `views/ChatView.vue` | 会话管理（历史/新建/收藏/恢复）+ 对话问答 + 来源溯源 + 研判徽标 + 打字机式渐进输出 |
| 我的知识库 | `views/KbView.vue` / `views/KbDocsView.vue` | 知识库列表、文档工作区、上传、分类、对账、重载、统一 DOCX 切分 |
| 运行概览 | `views/OverviewView.vue` | ECharts 图表（片段占比 / 分布 / 排名） |
| 使用指南 | `views/GuideView.vue` | 系统功能与操作说明 |
| 个人中心 | `views/ProfileView.vue` | 查看账号信息、修改显示名/密码、维护找回密码问题、强制改密引导 |
| 问题反馈 | `views/FeedbackView.vue` | 用户提交反馈、多截图附件、查看管理员回复、确认关闭 |
| 检索配置 | `views/ConfigPlaceholder.vue` + `components/ConfigForm.vue` | 系统 / 租户 / 知识库三级检索配置在线调整 |
| 知识库管理 | `views/AdminUsersView.vue` / `views/AdminUserKbsView.vue` / `views/AdminKbDocsView.vue` | 管理员按用户查看和维护知识库 |
| 账户管理 | `views/AccountView.vue` | 管理员用户管理、配额调整、重置其他用户密码、查看登录安全状态 |
| 申请审批 | `views/ReviewView.vue` | 管理员处理知识库配额申请 |
| 反馈处理 | `views/AdminFeedbackView.vue` | 管理员查看反馈与截图，回复并流转状态 |
| 通知下发 | `views/AdminNotificationsView.vue` | 管理员向全部或指定用户发送通知并查看统计 |
| 模型监控 | `views/AdminModelUsageView.vue` | 管理员查看模型调用 KPI、告警、用户归因和最近明细 |

## 组件、状态与测试

- `layouts/AppLayout.vue` — 主布局、侧栏导航、顶部通知消息中心、个人中心入口。
- `components/UploadModal.vue` — 上传弹窗（拖拽、分类、描述）。
- `components/UploadProgressModal.vue` — 上传进度面板。
- `components/ConfigForm.vue` — 检索配置表单。
- `composables/useAuth.ts` — 登录态、用户信息、JWT 持久化与 401 清理。
- `composables/useKnowledgeBase.ts` — 知识库列表与当前库状态。
- `composables/useSessions.ts` — 服务端会话历史状态。
- `composables/useTopics.ts` — 按知识库隔离的主题分类。
- `composables/useUploadTasks.ts` — 全局上传任务（进度、关闭弹窗仍继续）。
- `api/client.ts` — 后端接口封装 + 类型定义。
- `src/test/setup.ts` — Vitest/jsdom 全局测试初始化。

当前前端测试使用 **Vitest + Vue Test Utils + jsdom**，首批覆盖：

- `composables/useAuth.test.ts`：登录 / 注册 / 持久化 / 401 清理跳转。
- `router/index.test.ts`：未登录、公开页、管理员页、强制改密守卫。
- `views/FeedbackView.test.ts`：截图格式校验与反馈提交后上传截图。

## 技术栈

Vue 3、Vite 6、TypeScript、axios、ECharts（按需引入、懒加载）、Element Plus、Font Awesome、Vitest、Vue Test Utils、jsdom。
