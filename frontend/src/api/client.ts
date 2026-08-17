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

// 研判结果（防幻觉）：随 /rag/ask 返回，也随会话消息持久化。
export interface Verdict {
  answerable: boolean
  reason: string
  confidence: 'high' | 'low' | string
}

// POST /rag/ask 返回 { question, answer, sources, answerable, reason, confidence }
export interface AskResponse {
  question: string
  answer: string
  sources: Source[]
  answerable?: boolean
  reason?: string
  confidence?: 'high' | 'low' | string
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

/** 在指定知识库范围内提问；kbId 传 null 表示「全部知识库」（后端按角色限定范围） */
export async function askQuestion(question: string, kbId: number | null): Promise<AskResponse> {
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

export interface RechunkDocxResult {
  filename: string
  status: 'success' | 'failed'
  chunk_count: number
  error: string
}

export interface RechunkDocxResponse {
  processed: number
  succeeded: number
  failed: number
  skipped: number
  files: RechunkDocxResult[]
}

/** 统一存量 DOCX 切分：按当前解析/段落切分策略重建该库下所有 Word 文档 */
export async function rechunkDocxDocuments(kbId: number): Promise<RechunkDocxResponse> {
  const { data } = await http.post<RechunkDocxResponse>('/maintenance/rechunk-docx', null, {
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
}/** 从文件名推断类型标签（大写扩展名） */
export function fileExt(name: string): string {
  const ext = name.split('.').pop()
  return ext ? ext.toUpperCase() : 'FILE'
}

/** 知识主题分类默认值（接口失败时的降级兜底；正式数据来自后端 /topics） */
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

/** 后端 /topics 返回的单个主题分类（归属某知识库） */
export interface Topic {
  id: number
  kb_id: number
  name: string
  sort_order: number
}

/** 拉取某知识库的主题分类（属主或管理员可读） */
export async function fetchTopics(kbId: number): Promise<Topic[]> {
  const { data } = await http.get<{ topics: Topic[] }>('/topics', { params: { kb_id: kbId } })
  return data.topics
}

/** 在某知识库下新增主题分类（属主或管理员，幂等） */
export async function createTopic(kbId: number, name: string): Promise<Topic> {
  const { data } = await http.post<Topic>('/topics', { kb_id: kbId, name })
  return data
}

/** 重命名主题分类（属主或管理员），后端联动更新本库下用旧分类名的文档 */
export async function renameTopic(id: number, name: string): Promise<Topic> {
  const { data } = await http.patch<Topic>(`/topics/${id}`, { name })
  return data
}

/** 删除主题分类（属主或管理员） */
export async function deleteTopic(id: number): Promise<void> {
  await http.delete(`/topics/${id}`)
}

// ---- 认证与用户管理 ----

export interface AuthUser {
  id: number
  username: string
  role: string
  display_name: string
  kb_quota?: number
  created_at?: string
  last_login_at?: string
  password_changed_at?: string
  force_password_change?: boolean
  locked_until?: string
  has_recovery_questions?: boolean
}

export interface RecoveryItem {
  question: string
  answer: string
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
  recoveryItems: RecoveryItem[] = [],
): Promise<LoginResponse> {
  const { data } = await http.post<LoginResponse>('/auth/register', {
    username,
    password,
    display_name: displayName,
    recovery_items: recoveryItems,
  })
  return data
}

/** 取当前登录用户（用于刷新后校验令牌是否有效） */
export async function fetchMe(): Promise<AuthUser> {
  const { data } = await http.get<AuthUser>('/auth/me')
  return data
}

/** 修改当前用户显示名 */
export async function updateMyProfile(displayName: string): Promise<AuthUser> {
  const { data } = await http.patch<AuthUser>('/auth/me', { display_name: displayName })
  return data
}

/** 当前用户修改自己的密码 */
export async function changeMyPassword(oldPassword: string, newPassword: string): Promise<AuthUser> {
  const { data } = await http.post<AuthUser>('/auth/password/change', {
    old_password: oldPassword,
    new_password: newPassword,
  })
  return data
}

/** 设置/更新当前用户的找回密码问题 */
export async function setRecoveryQuestions(recoveryItems: RecoveryItem[]): Promise<AuthUser> {
  const { data } = await http.put<AuthUser>('/auth/recovery/questions', {
    recovery_items: recoveryItems,
  })
  return data
}

/** 忘记密码：按用户名读取找回问题 */
export async function fetchRecoveryQuestions(username: string): Promise<string[]> {
  const { data } = await http.post<{ questions: string[] }>('/auth/recovery/questions', { username })
  return data.questions
}

/** 忘记密码：回答问题后自助重置密码 */
export async function resetPasswordByRecovery(
  username: string,
  answers: string[],
  newPassword: string,
): Promise<AuthUser> {
  const { data } = await http.post<{ reset: boolean; user: AuthUser }>('/auth/recovery/reset-password', {
    username,
    answers,
    new_password: newPassword,
  })
  return data.user
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

/** 管理员重置其他用户密码 */
export async function resetUserPassword(
  userId: number,
  newPassword: string,
  forceChange = true,
): Promise<AuthUser> {
  const { data } = await http.post<AuthUser>(`/users/${userId}/password-reset`, {
    new_password: newPassword,
    force_change: forceChange,
  })
  return data
}

/** 调整某用户的知识库配额（仅管理员）。返回新配额与当前已用数。 */
export async function setUserQuota(
  userId: number,
  quota: number,
): Promise<{ id: number; kb_quota: number; used: number }> {
  const { data } = await http.patch<{ id: number; kb_quota: number; used: number }>(
    `/users/${userId}/quota`,
    { quota },
  )
  return data
}

// ---- 检索配置（三级：系统/租户/知识库）----

export type ConfigScope = 'system' | 'tenant' | 'kb'

export interface RetrievalConfig {
  top_k: number
  max_distance: number
  judge_enabled: boolean
  answer_prompt: string
  // 仅 tenant 级返回：多/全库查询用哪份配置（'system'|'tenant'）。
  multi_scope?: 'system' | 'tenant'
  // true 表示该级无自有配置、展示的是继承/兜底值。
  inherited?: boolean
}

/** 读取某级检索配置（含继承值 + inherited 标记）。 */
export async function getRetrievalConfig(
  scope: ConfigScope,
  kbId?: number,
): Promise<RetrievalConfig> {
  const params: Record<string, unknown> = { scope }
  if (scope === 'kb' && kbId != null) params.kb_id = kbId
  const { data } = await http.get<RetrievalConfig>('/config/retrieval', { params })
  return data
}

/** 写入/更新某级检索配置。 */
export async function saveRetrievalConfig(
  scope: ConfigScope,
  payload: {
    top_k: number
    max_distance: number
    judge_enabled: boolean
    answer_prompt: string
    multi_scope?: 'system' | 'tenant'
  },
  kbId?: number,
): Promise<RetrievalConfig> {
  const params: Record<string, unknown> = { scope }
  if (scope === 'kb' && kbId != null) params.kb_id = kbId
  const { data } = await http.put<RetrievalConfig>('/config/retrieval', payload, { params })
  return data
}

/** 清除某知识库的独立配置，回落继承。 */
export async function resetKbRetrievalConfig(kbId: number): Promise<RetrievalConfig> {
  const { data } = await http.delete<RetrievalConfig>('/config/retrieval', {
    params: { scope: 'kb', kb_id: kbId },
  })
  return data
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

/** 更新知识库名称/描述（属主或管理员） */
export async function updateKb(
  kbId: number,
  name: string,
  description = '',
): Promise<KnowledgeBase> {
  const { data } = await http.put<KnowledgeBase>(`/kbs/${kbId}`, { name, description })
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

// ---- 通知与消息中心 ----

export type NotificationStatus = 'unread' | 'read' | 'closed'
export type NotificationTargetType = 'all' | 'users'

export interface UserNotification {
  id: number
  title: string
  content: string
  created_by: number
  target_type: NotificationTargetType
  status: NotificationStatus
  created_at?: string
  read_at?: string
  closed_at?: string
}

export interface AdminNotificationSummary {
  id: number
  title: string
  content: string
  created_by: number
  target_type: NotificationTargetType
  created_at?: string
  recipient_count: number
  unread_count: number
  read_count: number
  closed_count: number
}

/** 我的通知列表 */
export async function listMyNotifications(includeClosed = false): Promise<UserNotification[]> {
  const { data } = await http.get<{ notifications: UserNotification[] }>('/notifications/mine', {
    params: { include_closed: includeClosed },
  })
  return data.notifications
}

/** 当前用户未读通知数量 */
export async function getUnreadNotificationCount(): Promise<number> {
  const { data } = await http.get<{ count: number }>('/notifications/unread-count')
  return data.count
}

/** 标记通知已读 */
export async function markNotificationRead(id: number): Promise<UserNotification> {
  const { data } = await http.post<UserNotification>(`/notifications/${id}/read`)
  return data
}

/** 关闭通知 */
export async function closeNotification(id: number): Promise<UserNotification> {
  const { data } = await http.post<UserNotification>(`/notifications/${id}/close`)
  return data
}

/** 管理员下发通知 */
export async function sendAdminNotification(payload: {
  title: string
  content?: string
  send_to_all: boolean
  user_ids?: number[]
}): Promise<AdminNotificationSummary> {
  const { data } = await http.post<AdminNotificationSummary>('/notifications/admin', payload)
  return data
}

/** 管理员通知下发历史 */
export async function listAdminNotifications(): Promise<AdminNotificationSummary[]> {
  const { data } = await http.get<{ notifications: AdminNotificationSummary[] }>('/notifications/admin')
  return data.notifications
}

// ---- 模型用量监控（仅管理员）----

export type ModelType = 'embedding' | 'chat' | 'judge' | 'query_rewrite' | 'rerank'

export interface ModelUsageMetric {
  call_count: number
  success_count: number
  failed_count: number
  success_rate: number
  error_rate: number
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  avg_latency_ms: number
  max_latency_ms: number
  p95_latency_ms: number
}

export interface ModelUsageByModel extends ModelUsageMetric {
  model_type: ModelType | string
}

export interface ModelUsageByUser extends ModelUsageMetric {
  user_id: number | null
  username?: string
  display_name?: string
}

export interface ModelUsageDaily extends ModelUsageMetric {
  date: string
}

export interface ModelUsageAlert {
  type: string
  severity: 'warning' | 'error' | string
  model_type: ModelType | string | null
  user_id: number | null
  username?: string
  display_name?: string
  title: string
  message: string
  current_value: number
  threshold: number
}

export interface ModelUsageSummary {
  days: number
  overall: ModelUsageMetric
  by_model_type: ModelUsageByModel[]
  by_user: ModelUsageByUser[]
  daily_trend: ModelUsageDaily[]
  alerts: ModelUsageAlert[]
}

export interface ModelUsageRecord {
  id: number
  user_id: number | null
  username?: string
  display_name?: string
  kb_id: number | null
  request_id: string
  model_type: ModelType | string
  provider: string
  model_name: string
  operation: string
  success: boolean
  latency_ms: number
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  input_count: number
  error_type: string
  error_message: string
  created_at?: string
}

export interface ModelUsageFilters {
  days?: number
  user_id?: number | null
  model_type?: ModelType | 'all' | string | null
  success?: boolean | null
  limit?: number
}

function usageParams(filters: ModelUsageFilters = {}) {
  return {
    days: filters.days ?? 7,
    user_id: filters.user_id || undefined,
    model_type: filters.model_type && filters.model_type !== 'all' ? filters.model_type : undefined,
    success: filters.success ?? undefined,
    limit: filters.limit,
  }
}

/** 管理员模型用量聚合统计 */
export async function fetchModelUsageSummary(filters: ModelUsageFilters = {}): Promise<ModelUsageSummary> {
  const { data } = await http.get<ModelUsageSummary>('/admin/model-usage/summary', { params: usageParams(filters) })
  return data
}

/** 管理员模型调用明细 */
export async function fetchModelUsageRecords(filters: ModelUsageFilters = {}): Promise<ModelUsageRecord[]> {
  const { data } = await http.get<{ records: ModelUsageRecord[] }>('/admin/model-usage/records', { params: usageParams(filters) })
  return data.records
}

/** 管理员模型异常告警 */
export async function fetchModelUsageAlerts(days = 1): Promise<ModelUsageAlert[]> {
  const { data } = await http.get<{ alerts: ModelUsageAlert[] }>('/admin/model-usage/alerts', { params: { days } })
  return data.alerts
}

// ---- 问题反馈 ----

export type FeedbackStatus = 'pending' | 'processing' | 'resolved' | 'closed'

export interface FeedbackAttachment {
  id: number
  ticket_id: number
  filename: string
  content_type: string
  size: number
  created_at?: string
}

export interface FeedbackTicket {
  id: number
  user_id: number
  title: string
  content: string
  status: FeedbackStatus
  admin_reply: string
  resolved_by: number | null
  created_at?: string
  updated_at?: string
  resolved_at?: string
  attachments: FeedbackAttachment[]
}

/** 提交问题反馈 */
export async function createFeedback(title: string, content = ''): Promise<FeedbackTicket> {
  const { data } = await http.post<FeedbackTicket>('/feedback', { title, content })
  return data
}

/** 给反馈上传截图附件 */
export async function uploadFeedbackScreenshots(
  ticketId: number,
  files: File[],
): Promise<FeedbackAttachment[]> {
  const form = new FormData()
  files.forEach((file) => form.append('files', file))
  const { data } = await http.post<{ attachments: FeedbackAttachment[] }>(
    `/feedback/${ticketId}/attachments`,
    form,
    { headers: { 'Content-Type': 'multipart/form-data' } },
  )
  return data.attachments
}

/** 鉴权下载反馈截图，返回可用于 window.open 的 blob URL。调用方负责 URL.revokeObjectURL。 */
export async function openFeedbackAttachment(ticketId: number, attachmentId: number): Promise<string> {
  const { data } = await http.get<Blob>(`/feedback/${ticketId}/attachments/${attachmentId}`, {
    responseType: 'blob',
  })
  return URL.createObjectURL(data)
}

/** 我的反馈历史 */
export async function listMyFeedback(): Promise<FeedbackTicket[]> {
  const { data } = await http.get<{ tickets: FeedbackTicket[] }>('/feedback/mine')
  return data.tickets
}

/** 用户确认关闭自己的反馈 */
export async function closeFeedback(id: number): Promise<FeedbackTicket> {
  const { data } = await http.post<FeedbackTicket>(`/feedback/${id}/close`)
  return data
}

/** 管理员查看反馈列表，可按状态筛选 */
export async function listAdminFeedback(status: FeedbackStatus | 'all' = 'all'): Promise<FeedbackTicket[]> {
  const { data } = await http.get<{ tickets: FeedbackTicket[] }>('/feedback/admin', {
    params: { status },
  })
  return data.tickets
}

/** 管理员更新反馈状态与回复 */
export async function updateAdminFeedback(
  id: number,
  status: Exclude<FeedbackStatus, 'pending'>,
  reply: string,
): Promise<FeedbackTicket> {
  const { data } = await http.patch<FeedbackTicket>(`/feedback/admin/${id}`, { status, reply })
  return data
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

// ---- 聊天会话（服务端持久化，按用户归属）----

/** 后端 /sessions 返回的会话（不含消息，含消息计数） */
export interface SessionSummary {
  id: number
  title: string
  is_favorite: boolean
  message_count: number
  created_at: string
  updated_at: string
}

/** 后端 /sessions/{id}/messages 返回的单条消息 */
export interface SessionMessage {
  id: number
  role: 'user' | 'assistant'
  content: string
  sources: Source[]
  verdict?: Verdict | null
  created_at: string
}

/** 当前用户的会话列表（最近更新在前） */
export async function listSessions(): Promise<SessionSummary[]> {
  const { data } = await http.get<{ sessions: SessionSummary[] }>('/sessions')
  return data.sessions
}

/** 新建会话 */
export async function createSession(title = '未命名会话'): Promise<SessionSummary> {
  const { data } = await http.post<SessionSummary>('/sessions', { title })
  return data
}

/** 会话改名 */
export async function renameSessionApi(id: number, title: string): Promise<SessionSummary> {
  const { data } = await http.patch<SessionSummary>(`/sessions/${id}`, { title })
  return data
}

/** 切换会话收藏状态 */
export async function toggleSessionFavorite(id: number): Promise<SessionSummary> {
  const { data } = await http.patch<SessionSummary>(`/sessions/${id}`, { toggle_favorite: true })
  return data
}

/** 删除会话（连带其消息） */
export async function deleteSessionApi(id: number): Promise<void> {
  await http.delete(`/sessions/${id}`)
}

/** 拉取会话内的消息（时间正序） */
export async function listSessionMessages(id: number): Promise<SessionMessage[]> {
  const { data } = await http.get<{ messages: SessionMessage[] }>(`/sessions/${id}/messages`)
  return data.messages
}

/** 向会话追加一条消息 */
export async function appendSessionMessage(
  id: number,
  role: 'user' | 'assistant',
  content: string,
  sources: Source[] = [],
  verdict: Verdict | null = null,
): Promise<SessionMessage> {
  const { data } = await http.post<SessionMessage>(`/sessions/${id}/messages`, {
    role,
    content,
    sources,
    verdict,
  })
  return data
}
