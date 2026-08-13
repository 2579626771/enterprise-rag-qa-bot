import { ref, computed } from 'vue'
import { listKbs, type KnowledgeBase } from '../api/client'

// 模块级单例：全应用共享「当前知识库」与「知识库列表」。
// 与 useAuth / useSessions / useUploadTasks 一致的单例模式。
const kbList = ref<KnowledgeBase[]>([])
const currentKbId = ref<number>(0)
const quota = ref<number>(0)
const used = ref<number>(0)
const loading = ref<boolean>(false)

// 记住上次选中的库，刷新后尽量恢复
const LAST_KB_KEY = 'rag_current_kb_v1'

function loadLastKb(): number {
  try {
    const raw = localStorage.getItem(LAST_KB_KEY)
    if (raw) return Number(raw) || 0
  } catch {
    // ignore
  }
  return 0
}

function saveLastKb(id: number) {
  try {
    localStorage.setItem(LAST_KB_KEY, String(id))
  } catch {
    // ignore
  }
}

export function useKnowledgeBase() {
  const currentKb = computed(() => kbList.value.find((k) => k.id === currentKbId.value) ?? null)
  const canCreate = computed(() => used.value < quota.value)

  /** 拉取当前用户的知识库列表，并确保有一个选中的库。 */
  async function refreshKbs(): Promise<void> {
    loading.value = true
    try {
      const res = await listKbs(false)
      kbList.value = res.kbs
      quota.value = res.quota
      used.value = res.used
      // 选中逻辑：优先保持当前选中；否则用上次记忆；再否则用第一个。
      const ids = res.kbs.map((k) => k.id)
      if (!ids.includes(currentKbId.value)) {
        const last = loadLastKb()
        currentKbId.value = ids.includes(last) ? last : ids[0] ?? 0
      }
    } finally {
      loading.value = false
    }
  }

  function selectKb(id: number) {
    currentKbId.value = id
    saveLastKb(id)
  }

  /** 退出登录时清空，避免串号。 */
  function resetKbs() {
    kbList.value = []
    currentKbId.value = 0
    quota.value = 0
    used.value = 0
  }

  return {
    kbList,
    currentKbId,
    currentKb,
    quota,
    used,
    canCreate,
    loading,
    refreshKbs,
    selectKb,
    resetKbs,
  }
}
