import { ref, computed } from 'vue'
import { listKbs, type KnowledgeBase } from '../api/client'

// 模块级单例：全应用共享「当前知识库」与「知识库列表」。
// 与 useAuth / useSessions / useUploadTasks 一致的单例模式。
//
// 约定：currentKbId === 0 表示「全部知识库」（问答时对自己可访问范围内的所有库检索）。
// 这是问答页的默认范围；具体某个库则用其真实 id（>0）。
const ALL_KB_ID = 0
const kbList = ref<KnowledgeBase[]>([])
const currentKbId = ref<number>(ALL_KB_ID)
const quota = ref<number>(0)
const used = ref<number>(0)
const loading = ref<boolean>(false)

// 记住上次选中的库，刷新后尽量恢复
const LAST_KB_KEY = 'rag_current_kb_v1'

function loadLastKb(): number {
  try {
    const raw = localStorage.getItem(LAST_KB_KEY)
    if (raw !== null) return Number(raw) || ALL_KB_ID
  } catch {
    // ignore
  }
  return ALL_KB_ID
}

function saveLastKb(id: number) {
  try {
    localStorage.setItem(LAST_KB_KEY, String(id))
  } catch {
    // ignore
  }
}

export function useKnowledgeBase() {
  // 「全部」时 currentKb 为 null；否则返回对应库对象。
  const currentKb = computed(() =>
    currentKbId.value === ALL_KB_ID
      ? null
      : kbList.value.find((k) => k.id === currentKbId.value) ?? null,
  )
  const canCreate = computed(() => used.value < quota.value)

  /** 拉取当前用户的知识库列表。默认「全部」，尽量恢复上次选择。 */
  async function refreshKbs(): Promise<void> {
    loading.value = true
    try {
      const res = await listKbs(false)
      kbList.value = res.kbs
      quota.value = res.quota
      used.value = res.used
      // 选中逻辑：0（全部）恒合法且为默认；若当前选了某个已不存在的库，回退到上次记忆或「全部」。
      const ids = res.kbs.map((k) => k.id)
      if (currentKbId.value !== ALL_KB_ID && !ids.includes(currentKbId.value)) {
        const last = loadLastKb()
        currentKbId.value = ids.includes(last) ? last : ALL_KB_ID
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
    currentKbId.value = ALL_KB_ID
    quota.value = 0
    used.value = 0
  }

  return {
    ALL_KB_ID,
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
