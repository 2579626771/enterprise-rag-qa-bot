# Enterprise RAG · 前端

企业知识库问答系统的前端工作台，基于 **Vue 3 + Vite + TypeScript**。

## 启动

```bash
npm install
npm run dev      # 开发服务器 http://localhost:5173
npm run build    # 类型检查 + 生产构建
```

或双击 `启动前端.bat`。

> 需先启动后端（默认 `http://127.0.0.1:8000`）。Vite 已配置代理，把前端 `/api/*` 请求转发到后端，无需额外处理跨域。

## 页面

| 页面 | 文件 | 说明 |
|------|------|------|
| 智能问答 | `views/ChatView.vue` | 会话管理（历史/新建/收藏/恢复）+ 对话问答 + 来源溯源 |
| 资料档案库 | `views/ArchiveView.vue` | 统计卡 + 表格 + 分类筛选 + 上传 + 对账 + 重载 |
| 运行概览 | `views/OverviewView.vue` | ECharts 图表（片段占比 / 分布 / 排名） |

## 组件与状态

- `components/UploadModal.vue` — 上传弹窗（拖拽、分类、描述）
- `components/UploadProgressModal.vue` — 上传进度面板
- `composables/useSessions.ts` — 会话（localStorage 持久化）
- `composables/useDocMeta.ts` — 文档分类/描述元数据（localStorage 占位，后续可落库）
- `composables/useUploadTasks.ts` — 全局上传任务（进度、关闭弹窗仍继续）
- `api/client.ts` — 后端接口封装 + 类型定义

## 技术栈

Vue 3、Vite 6、TypeScript、axios、ECharts（按需引入、懒加载）、Font Awesome。
