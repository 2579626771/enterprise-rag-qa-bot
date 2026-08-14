import { ref, computed } from 'vue'
import {
  type Source,
  type Verdict,
  type SessionSummary,
  type SessionMessage,
  listSessions,
  createSession,
  renameSessionApi,
  toggleSessionFavorite,
  deleteSessionApi,
  listSessionMessages,
  appendSessionMessage,
} from '../api/client'

// 会话中的一条消息（本地视图模型；id 用后端返回的数值）
export interface ChatMessage {
  id: number
  role: 'user' | 'assistant'
  content: string
  sources?: Source[]
  verdict?: Verdict | null
}

// 一个问答会话（本地视图模型）
export interface Session {
  sessionId: number
  sessionTitle: string
  isFavorite: boolean
  lastTime: string
  messageCount: number
  messages: ChatMessage[]
  loaded: boolean // 该会话的历史消息是否已从后端拉取
}

// 会话历史改为后端 MySQL 服务端持久化（替换早期 localStorage 占位）。
// 状态用模块级单例，多个组件共享同一份。
const sessions = ref<Session[]>([])
const currentSessionId = ref<number | null>(null)
let initialized = false

function fromSummary(s: SessionSummary): Session {
  return {
    sessionId: s.id,
    sessionTitle: s.title,
    isFavorite: s.is_favorite,
    lastTime: s.updated_at,
    messageCount: s.message_count,
    messages: [],
    loaded: false,
  }
}

function toChatMessage(m: SessionMessage): ChatMessage {
  return { id: m.id, role: m.role, content: m.content, sources: m.sources, verdict: m.verdict ?? null }
}

// 从后端加载会话列表（登录后首次进入时调用）。
async function refresh(): Promise<void> {
  const list = await listSessions()
  sessions.value = list.map(fromSummary)
  if (!sessions.value.find((s) => s.sessionId === currentSessionId.value)) {
    currentSessionId.value = sessions.value[0]?.sessionId ?? null
  }
  if (currentSessionId.value != null) {
    await loadMessages(currentSessionId.value)
  }
}

// 惰性加载某会话的历史消息。
async function loadMessages(sessionId: number): Promise<void> {
  const s = sessions.value.find((x) => x.sessionId === sessionId)
  if (!s || s.loaded) return
  const msgs = await listSessionMessages(sessionId)
  s.messages = msgs.map(toChatMessage)
  s.messageCount = s.messages.length
  s.loaded = true
}

// 登出时清空本地会话状态，避免串号到下一个用户。
function reset(): void {
  sessions.value = []
  currentSessionId.value = null
  initialized = false
}

export function useSessions() {
  const currentSession = computed(() =>
    sessions.value.find((s) => s.sessionId === currentSessionId.value),
  )
  const currentMessages = computed(() => currentSession.value?.messages ?? [])

  // 首次使用时自动拉取一次（幂等）。
  async function init(): Promise<void> {
    if (initialized) return
    initialized = true
    try {
      await refresh()
    } catch {
      initialized = false // 失败允许下次重试
    }
  }

  async function newConversation(): Promise<Session> {
    const created = await createSession('未命名会话')
    const session = fromSummary(created)
    session.loaded = true // 新会话无历史消息，视为已加载
    sessions.value.unshift(session)
    currentSessionId.value = session.sessionId
    return session
  }

  async function selectSession(sessionId: number): Promise<void> {
    currentSessionId.value = sessionId
    await loadMessages(sessionId)
  }

  async function toggleFavorite(sessionId: number): Promise<void> {
    const updated = await toggleSessionFavorite(sessionId)
    const s = sessions.value.find((x) => x.sessionId === sessionId)
    if (s) s.isFavorite = updated.is_favorite
  }

  async function deleteSession(sessionId: number): Promise<void> {
    await deleteSessionApi(sessionId)
    const idx = sessions.value.findIndex((x) => x.sessionId === sessionId)
    if (idx >= 0) sessions.value.splice(idx, 1)
    if (currentSessionId.value === sessionId) {
      currentSessionId.value = sessions.value[0]?.sessionId ?? null
      if (currentSessionId.value != null) await loadMessages(currentSessionId.value)
    }
  }

  async function renameSession(sessionId: number, title: string): Promise<void> {
    if (!title.trim()) return
    const updated = await renameSessionApi(sessionId, title.trim())
    const s = sessions.value.find((x) => x.sessionId === sessionId)
    if (s) s.sessionTitle = updated.title
  }

  // 追加一条消息：写后端并把返回结果并入本地会话。
  async function appendMessage(
    sessionId: number,
    msg: Omit<ChatMessage, 'id'>,
  ): Promise<void> {
    const saved = await appendSessionMessage(
      sessionId,
      msg.role,
      msg.content,
      msg.sources ?? [],
      msg.verdict ?? null,
    )
    const s = sessions.value.find((x) => x.sessionId === sessionId)
    if (!s) return
    s.messages.push(toChatMessage(saved))
    s.messageCount = s.messages.length
    // 首条 user 消息且标题仍为默认时，本地同步后端的自动命名逻辑。
    if (
      msg.role === 'user' &&
      (s.sessionTitle === '未命名会话' || !s.sessionTitle) &&
      s.messages.filter((m) => m.role === 'user').length === 1
    ) {
      s.sessionTitle = msg.content.length > 16 ? `${msg.content.slice(0, 16)}…` : msg.content
    }
  }

  // 确保有一个当前会话（没有则新建），返回其 id。
  async function ensureCurrent(): Promise<number> {
    if (!currentSession.value) {
      const s = await newConversation()
      return s.sessionId
    }
    return currentSessionId.value as number
  }

  return {
    sessions,
    currentSessionId,
    currentSession,
    currentMessages,
    init,
    refresh,
    reset,
    newConversation,
    selectSession,
    toggleFavorite,
    deleteSession,
    renameSession,
    appendMessage,
    ensureCurrent,
  }
}
