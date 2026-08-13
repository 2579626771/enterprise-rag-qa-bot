import axios from 'axios'

// 统一的 axios 实例。baseURL 用 /api，由 vite proxy 转发到后端。
const http = axios.create({
  baseURL: '/api',
  timeout: 60000, // RAG 回答可能较慢，给 60 秒
})

// 登录令牌的存储 key（与 useAuth 保持一致）。这里直接读 localStorage，
// 避免 client 与 composable 循环依赖。
const TOKEN_KEY = 'rag_auth_v1'

/** 从 localStorage 读取 token（登录态由 useAuth 写入）。 */
function readToken(): string {
  try {
    const raw = localStorage.getItem(TOKEN_KEY)
    if (raw) return (JSON.parse(raw)?.token as string) || ''
  } catch {
    // ignore
  }
  return ''
}

// 请求拦截器：自动给每个请求带上 Authorization 头。
http.interceptors.request.use((config) => {
  const token = readToken()
  if (token) {
    config.headers = config.headers ?? {}
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 响应拦截器：令牌失效（401）时清登录态并跳回登录页。
http.interceptors.response.use(
  (resp) => resp,
  (error) => {
    if (axios.isAxiosError(error) && error.response?.status === 401) {
      // 清除本地登录态；派发事件让 App 切回登录页（不硬跳转，保留 SPA 状态）。
      localStorage.removeItem(TOKEN_KEY)
      window.dispatchEvent(new CustomEvent('auth:unauthorized'))
    }
    return Promise.reject(error)
  },
)

// ---- 类型定义：严格对齐后端 api.py 的返回结构 ----

// 单条文档（含 MySQL 元数据）
export interface DocumentItem {
  filename: string
  topic: string
  description: string
  status: string
  uploaded_at: string
  chunk_count?: number
  error?: string
}

// GET /documents 返回 { documents: DocumentItem[] }
export interface DocumentListResponse {
  documents: DocumentItem[]
}

// POST /documents/upload 返回 { filename, file_path, status }
// 改为异步入库后，上传接口存盘即返回，status 恒为「处理中」；
// 真正的入库结果（就绪/失败）由前端轮询 GET /documents 获取。
export interface UploadResponse {
  filename: string
  file_path: string
  status: string
}

// /rag/ask 返回的单条来源
export interface Source {
  filename: string
  chunk_index: number
  content: string
}

// POST /rag/ask 返回 { question, answer, sources }
export interface AskResponse {
  question: string
  answer: string
  sources: Source[]
}

// GET /stats 返回知识库聚合统计
export interface StatsResponse {
  total_chunks: number
  document_count: number
  per_document: Array<{ filename: string; chunk_count: number }>
}

// ---- 接口封装：均带知识库 id（kb_id）以隔离数据 ----

/** 获取指定知识库的文档列表（含分类/描述/上传时间/状态等元数据） */
export async function listDocuments(kbId: number): Promise<DocumentItem[]> {
  const { data } = await http.get<DocumentListResponse>('/documents', {
    params: { kb_id: kbId },
  })
  return data.documents
}

/** 上传文档到指定知识库（上传即入库）。
 *  onProgress 回传文件传输阶段的真实百分比(0-100) */
export async function uploadDocument(
  file: File,
  kbId: number,
  topic: string,
  description: string,
  onProgress?: (percent: number) => void,
): Promise<UploadResponse> {
  const form = new FormData()
  form.append('file', file)
  form.append('kb_id', String(kbId))
  form.append('topic', topic)
  form.append('description', description)
  const { data } = await http.post<UploadResponse>('/documents/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: (e) => {
      if (onProgress && e.total) {
        onProgress(Math.round((e.loaded / e.total) * 100))
      }
    },
  })
  return data
}

/** 从指定知识库删除文档（同时删除其在向量库中的片段） */
export async function deleteDocument(filename: string, kbId: number): Promise<void> {
  await http.delete(`/documents/${encodeURIComponent(filename)}`, {
    params: { kb_id: kbId },
  })
}

/** 在指定知识库范围内提问 */
export async function askQuestion(question: string, kbId: number): Promise<AskResponse> {
  const { data } = await http.post<AskResponse>('/rag/ask', { question, kb_id: kbId })
  return data
}

/** 指定知识库的概览统计（供图表使用） */
export async function fetchStats(kbId: number): Promise<StatsResponse> {
  const { data } = await http.get<StatsResponse>('/stats', { params: { kb_id: kbId } })
  return data
}

/** 对账修复结果 */
export interface ReconcileResponse {
  removed_files: Array<{ filename: string; chunk_count: number }>
  removed_chunks: number
  total_before: number
  total_after: number
}

/** 数据对账：清理指定知识库里"文件已删除但向量仍残留"的僵尸片段 */
export async function reconcile(kbId: number): Promise<ReconcileResponse> {
  const { data } = await http.post<ReconcileResponse>('/maintenance/reconcile', null, {
    params: { kb_id: kbId },
  })
  return data
}

/** 重载知识库：重新连接向量库、加载最新数据（返回当前知识库的片段数） */
export async function reloadKnowledgeBase(kbId: number): Promise<{ reloaded: boolean; total_chunks: number }> {
  const { data } = await http.post<{ reloaded: boolean; total_chunks: number }>('/maintenance/reload', null, {
    params: { kb_id: kbId },
  })
  return data
}

/** 从 axios 错误里提取后端返回的 detail 文案，便于界面展示 */
export function extractErrorMessage(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail
    if (typeof detail === 'string') return detail
    if (err.message) return err.message
  }
  return '请求失败，请稍后重试'
}

/** 后端 /documents 返回的是完整路径，这里取文件名部分用于展示与删除 */
export function basename(path: string): string {
  return path.split(/[\\/]/).pop() || path
}

/** 从文件名推断类型标签（大写扩展名） */
export function fileExt(name: string): string {
  const ext = name.split('.').pop()
  return ext ? ext.toUpperCase() : 'FILE'
}

/** 知识主题分类选项（参考图3；本轮前端占位，下轮落 MySQL） */
export const KNOWLEDGE_TOPICS = [
  '技术文档',
  '产品手册',
  '规章制度',
  '培训资料',
  '会议纪要',
  '研究报告',
  '常见问答',
  '其他',
] as const

// ---- 认证与用户管理 ----

export interface AuthUser {
  id: number
  username: string
  role: string
  display_name: string
  kb_quota?: number
  created_at?: string
}

export interface LoginResponse {
  access_token: string
  token_type: string
  user: AuthUser
}

/** 登录：成功返回令牌与用户信息 */
export async function login(username: string, password: string): Promise<LoginResponse> {
  const { data } = await http.post<LoginResponse>('/auth/login', { username, password })
  return data
}

/** 自助注册：成功返回令牌与用户信息（可直接自动登录）。只能注册普通用户。 */
export async function register(
  username: string,
  password: string,
  displayName = '',
): Promise<LoginResponse> {
  const { data } = await http.post<LoginResponse>('/auth/register', {
    username,
    password,
    display_name: displayName,
  })
  return data
}

/** 取当前登录用户（用于刷新后校验令牌是否有效） */
export async function fetchMe(): Promise<AuthUser> {
  const { data } = await http.get<AuthUser>('/auth/me')
  return data
}

/** 用户列表（仅管理员） */
export async function listUsers(): Promise<AuthUser[]> {
  const { data } = await http.get<{ users: AuthUser[] }>('/users')
  return data.users
}

/** 新建用户（仅管理员） */
export async function createUser(payload: {
  username: string
  password: string
  role: string
  display_name?: string
}): Promise<AuthUser> {
  const { data } = await http.post<AuthUser>('/users', payload)
  return data
}

/** 删除用户（仅管理员） */
export async function deleteUser(userId: number): Promise<void> {
  await http.delete(`/users/${userId}`)
}

// ---- 知识库 ----

export interface KnowledgeBase {
  id: number
  owner_id: number
  name: string
  description: string
  created_at?: string
}

export interface KbListResponse {
  kbs: KnowledgeBase[]
  quota: number
  used: number
}

/** 知识库列表。all=true 且为管理员时返回全部用户的库。 */
export async function listKbs(all = false): Promise<KbListResponse> {
  const { data } = await http.get<KbListResponse>('/kbs', {
    params: all ? { all: true } : undefined,
  })
  return data
}

/** 新建知识库（受配额限制） */
export async function createKb(name: string, description = ''): Promise<KnowledgeBase> {
  const { data } = await http.post<KnowledgeBase>('/kbs', { name, description })
  return data
}

/** 删除知识库（连带清除其文件、向量、元数据） */
export async function deleteKb(kbId: number): Promise<void> {
  await http.delete(`/kbs/${kbId}`)
}

// ---- 配额申请 ----

export interface QuotaRequest {
  id: number
  user_id: number
  amount: number
  reason: string
  status: string
  reviewed_by: number | null
  created_at?: string
  reviewed_at?: string
}

/** 提交额外知识库配额申请 */
export async function submitQuotaRequest(amount: number, reason: string): Promise<QuotaRequest> {
  const { data } = await http.post<QuotaRequest>('/kb-requests', { amount, reason })
  return data
}

/** 我的申请记录 */
export async function myQuotaRequests(): Promise<QuotaRequest[]> {
  const { data } = await http.get<{ requests: QuotaRequest[] }>('/kb-requests/mine')
  return data.requests
}

/** 待审批申请列表（仅管理员） */
export async function pendingQuotaRequests(): Promise<QuotaRequest[]> {
  const { data } = await http.get<{ requests: QuotaRequest[] }>('/kb-requests/pending')
  return data.requests
}

/** 通过申请（仅管理员） */
export async function approveQuotaRequest(id: number): Promise<QuotaRequest> {
  const { data } = await http.post<QuotaRequest>(`/kb-requests/${id}/approve`)
  return data
}

/** 驳回申请（仅管理员） */
export async function rejectQuotaRequest(id: number): Promise<QuotaRequest> {
  const { data } = await http.post<QuotaRequest>(`/kb-requests/${id}/reject`)
  return data
}
