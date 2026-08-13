import { ref, computed, watch } from 'vue'
import type { Source } from '../api/client'

// 会话中的一条消息
export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  sources?: Source[]
}

// 一个问答会话
export interface Session {
  sessionId: string
  sessionTitle: string
  isFavorite: boolean
  lastTime: string
  messages: ChatMessage[]
}

const STORAGE_KEY = 'rag_sessions_v1'

// 本轮：会话历史用 localStorage 持久化（占位）。
// 下一轮做多轮对话时，会替换为后端 Redis(热) + MySQL(冷) 分层存储。
function load(): Session[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) return JSON.parse(raw) as Session[]
  } catch {
    // 忽略解析错误，回退到空列表
  }
  return []
}

const sessions = ref<Session[]>(load())
const currentSessionId = ref<string>(sessions.value[0]?.sessionId ?? '')

// 任何变动自动写回 localStorage
watch(
  sessions,
  (val) => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(val))
    } catch {
      // 存储失败（隐私模式/超限）静默忽略
    }
  },
  { deep: true },
)

let seq = 0
function uid(prefix: string): string {
  seq += 1
  return `${prefix}_${seq}_${sessions.value.length}`
}

function nowLabel(): string {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

export function useSessions() {
  const currentSession = computed(() =>
    sessions.value.find((s) => s.sessionId === currentSessionId.value),
  )
  const currentMessages = computed(() => currentSession.value?.messages ?? [])

  function newConversation(): Session {
    const session: Session = {
      sessionId: uid('sess'),
      sessionTitle: '未命名会话',
      isFavorite: false,
      lastTime: nowLabel(),
      messages: [],
    }
    sessions.value.unshift(session)
    currentSessionId.value = session.sessionId
    return session
  }

  function selectSession(sessionId: string) {
    currentSessionId.value = sessionId
  }

  function toggleFavorite(sessionId: string) {
    const s = sessions.value.find((x) => x.sessionId === sessionId)
    if (s) s.isFavorite = !s.isFavorite
  }

  function deleteSession(sessionId: string) {
    const idx = sessions.value.findIndex((x) => x.sessionId === sessionId)
    if (idx >= 0) sessions.value.splice(idx, 1)
    if (currentSessionId.value === sessionId) {
      currentSessionId.value = sessions.value[0]?.sessionId ?? ''
    }
  }

  function renameSession(sessionId: string, title: string) {
    const s = sessions.value.find((x) => x.sessionId === sessionId)
    if (s && title.trim()) s.sessionTitle = title.trim()
  }

  // 追加一条消息；若是本会话首条 user 消息，用它更新标题
  function appendMessage(sessionId: string, msg: Omit<ChatMessage, 'id'>): void {
    const s = sessions.value.find((x) => x.sessionId === sessionId)
    if (!s) return
    s.messages.push({ ...msg, id: uid('msg') })
    s.lastTime = nowLabel()
    if (msg.role === 'user' && s.messages.filter((m) => m.role === 'user').length === 1) {
      s.sessionTitle = msg.content.length > 16 ? `${msg.content.slice(0, 16)}…` : msg.content
    }
  }

  // 确保有一个当前会话（没有则新建），返回其 id
  function ensureCurrent(): string {
    if (!currentSession.value) newConversation()
    return currentSessionId.value
  }

  return {
    sessions,
    currentSessionId,
    currentSession,
    currentMessages,
    newConversation,
    selectSession,
    toggleFavorite,
    deleteSession,
    renameSession,
    appendMessage,
    ensureCurrent,
    nowLabel,
  }
}
