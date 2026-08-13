import { ref, computed } from 'vue'
import { uploadDocument, listDocuments, extractErrorMessage } from '../api/client'

// 上传任务的阶段：
// uploading  文件传输中（有真实百分比）
// processing 后端解析入库中（无百分比，只有"处理中"）
// success    完成（拿到入库片段数）
// error      失败（带错误原因）
export type UploadPhase = 'uploading' | 'processing' | 'success' | 'error'

export interface UploadTask {
  id: string
  filename: string
  size: number
  topic: string
  phase: UploadPhase
  percent: number       // 传输阶段百分比 0-100
  chunkCount: number    // 成功后入库片段数
  error: string         // 失败原因
  startedAt: string
}

// 模块级单例：所有组件共享同一份任务列表，关闭弹窗任务不丢
const tasks = ref<UploadTask[]>([])
// 每当有任务成功入库自增，供档案库页 watch 后刷新列表/统计
const completedTick = ref(0)
let counter = 0

function nowLabel(): string {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

export function useUploadTasks() {
  const activeCount = computed(
    () => tasks.value.filter((t) => t.phase === 'uploading' || t.phase === 'processing').length,
  )

  function create(filename: string, size: number, topic: string): string {
    counter += 1
    const id = `up_${counter}_${Date.now()}`
    tasks.value.unshift({
      id,
      filename,
      size,
      topic,
      phase: 'uploading',
      percent: 0,
      chunkCount: 0,
      error: '',
      startedAt: nowLabel(),
    })
    return id
  }

  function update(id: string, patch: Partial<UploadTask>) {
    const t = tasks.value.find((x) => x.id === id)
    if (t) Object.assign(t, patch)
  }

  function remove(id: string) {
    const idx = tasks.value.findIndex((x) => x.id === id)
    if (idx >= 0) tasks.value.splice(idx, 1)
  }

  function clearFinished() {
    tasks.value = tasks.value.filter(
      (t) => t.phase === 'uploading' || t.phase === 'processing',
    )
  }

  // 轮询后端文档状态，直到该文件「就绪 / 失败」或超时兜底。
  // 后端改为异步入库后，上传接口只返回「处理中」，真正的入库结果需要靠轮询感知。
  const POLL_INTERVAL_MS = 2000     // 每 2 秒查一次
  const POLL_MAX_MS = 10 * 60 * 1000 // 最多轮询 10 分钟，避免异常时无限轮询

  function sleep(ms: number): Promise<void> {
    return new Promise((resolve) => window.setTimeout(resolve, ms))
  }

  async function pollUntilDone(id: string, kbId: number, filename: string): Promise<void> {
    const deadline = Date.now() + POLL_MAX_MS
    while (Date.now() < deadline) {
      await sleep(POLL_INTERVAL_MS)
      let docs
      try {
        docs = await listDocuments(kbId)
      } catch {
        continue // 单次查询失败不终止，下一轮再试
      }
      const doc = docs.find((d) => d.filename === filename)
      if (!doc) continue // 列表里还没出现，继续等
      if (doc.status === '就绪') {
        update(id, { phase: 'success', percent: 100, chunkCount: doc.chunk_count ?? 0 })
        completedTick.value += 1
        return
      }
      if (doc.status === '失败') {
        update(id, { phase: 'error', error: doc.error || '入库失败' })
        return
      }
      // status === '处理中'：继续轮询
    }
    // 超时兜底：不代表一定失败，提示用户稍后刷新查看。
    update(id, { phase: 'error', error: '入库超时，请稍后在列表中查看最新状态' })
  }

  // 完整上传编排：传输(带真实百分比) → 处理中 → 轮询后端 → 成功/失败。
  // 上传到指定知识库 kbId；元数据（分类/描述）随请求提交，由后端落库。
  // 独立于任何组件生命周期，弹窗关闭后仍继续。
  async function runUpload(
    file: File,
    kbId: number,
    topic: string,
    description: string,
  ): Promise<void> {
    const id = create(file.name, file.size, topic)
    try {
      await uploadDocument(file, kbId, topic, description, (percent) => {
        update(id, {
          percent,
          phase: percent >= 100 ? 'processing' : 'uploading',
        })
      })
      // 上传接口已返回，但后端仍在后台入库 → 保持「处理中」并轮询真实结果。
      update(id, { phase: 'processing', percent: 100 })
      await pollUntilDone(id, kbId, file.name)
    } catch (e) {
      update(id, { phase: 'error', error: extractErrorMessage(e) })
    }
  }

  return { tasks, activeCount, completedTick, create, update, remove, clearFinished, runUpload }
}
