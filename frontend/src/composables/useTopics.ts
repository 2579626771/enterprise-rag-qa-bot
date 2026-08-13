import { ref, computed, watch } from 'vue'
import {
  fetchTopics,
  createTopic,
  renameTopic,
  deleteTopic,
  KNOWLEDGE_TOPICS,
  type Topic,
} from '../api/client'
import { useKnowledgeBase } from './useKnowledgeBase'

// 文档主题分类：按知识库隔离，跟随「当前知识库」。每个库有独立的一组分类。
// 与 useAuth / useKnowledgeBase 一致的模块级单例：全应用共享一份。
// 内部按 kbId 缓存，切换知识库时自动重新拉取；接口失败降级为内置默认值兜底。
const { currentKbId } = useKnowledgeBase()

const cache = new Map<number, Topic[]>()
const items = ref<Topic[]>([]) // 当前库的完整分类对象（含 id，供管理面板用）
const loadFailed = ref<boolean>(false) // 最近一次拉取是否失败（仅失败时才用内置兜底）
const loadingKb = ref<number>(0)

// 供下拉/筛选使用的分类名数组。
// 只有「接口失败」才回退到内置默认值；正常返回空（该库确实没有分类）就显示空，
// 避免掩盖真实空状态导致与「管理分类」面板不一致。
const topics = computed<string[]>(() =>
  loadFailed.value && items.value.length === 0
    ? [...KNOWLEDGE_TOPICS]
    : items.value.map((t) => t.name),
)

async function loadFor(kbId: number, force = false): Promise<void> {
  if (!kbId) {
    items.value = []
    loadFailed.value = false
    return
  }
  if (!force && cache.has(kbId)) {
    items.value = cache.get(kbId)!
    loadFailed.value = false
    return
  }
  try {
    const list = await fetchTopics(kbId)
    cache.set(kbId, list)
    items.value = list
    loadFailed.value = false
  } catch {
    // 接口失败：不缓存，标记失败让下拉回退到内置默认值兜底。
    items.value = []
    loadFailed.value = true
  }
}

// 当前库变化时自动切换分类列表。
watch(
  currentKbId,
  (kbId) => {
    void loadFor(kbId)
  },
  { immediate: true },
)

export function useTopics() {
  // 首次使用时确保已加载当前库（幂等）。
  async function ensureLoaded(): Promise<void> {
    if (currentKbId.value && !cache.has(currentKbId.value)) {
      await loadFor(currentKbId.value)
    }
  }

  // 强制刷新当前库（增删改后调用）。
  async function refresh(): Promise<void> {
    await loadFor(currentKbId.value, true)
  }

  async function addTopic(name: string): Promise<void> {
    await createTopic(currentKbId.value, name.trim())
    await refresh()
  }

  async function editTopic(id: number, name: string): Promise<void> {
    await renameTopic(id, name.trim())
    await refresh()
  }

  async function removeTopic(id: number): Promise<void> {
    await deleteTopic(id)
    await refresh()
  }

  return {
    topics, // string[]：下拉/筛选用
    items, // Topic[]：管理面板用（含 id）
    loadingKb,
    ensureLoaded,
    refresh,
    addTopic,
    editTopic,
    removeTopic,
  }
}
