<template>
  <main class="archive">
    <!-- 页头 -->
    <div class="archive-head">
      <div>
        <h1>资料档案库 <span class="pill">文献资产工作区</span></h1>
        <p>统一管理企业知识文档，跟踪解析入库状态</p>
      </div>
      <div class="head-actions">
        <button class="btn-ghost" type="button" :disabled="loading" @click="refresh" title="刷新文档列表与片段统计">
          <i class="fa-solid fa-rotate" :class="{ spin: loading }"></i> 刷新
        </button>
        <button class="primary lg" type="button" @click="showUpload = true">
          <i class="fa-solid fa-upload"></i> 上传文档
        </button>
      </div>
    </div>

    <!-- 统计卡片 -->
    <div class="stat-cards">
      <div v-for="c in statCards" :key="c.label" class="stat-card">
        <div class="stat-icon"><i :class="c.icon"></i></div>
        <div>
          <strong>{{ c.value }}</strong>
          <span>{{ c.label }}</span>
        </div>
      </div>
    </div>

    <!-- 文档上传进度入口 -->
    <button class="progress-entry" type="button" @click="showProgress = true">
      <span class="pe-left">
        <i class="fa-solid fa-arrows-rotate" :class="{ spin: activeCount > 0 }"></i>
        文档上传进度
      </span>
      <span class="pe-right">
        <span v-if="activeCount > 0" class="pe-badge">{{ activeCount }} 个进行中</span>
        <span v-else class="pe-idle">查看上传记录</span>
        <i class="fa-solid fa-chevron-right"></i>
      </span>
    </button>

    <!-- 筛选栏 -->
    <div class="filter-bar">
      <select
        :value="currentKbId"
        class="select"
        title="当前知识库"
        @change="onSelectKb(Number(($event.target as HTMLSelectElement).value))"
      >
        <option v-for="kb in kbList" :key="kb.id" :value="kb.id">📚 {{ kb.name }}</option>
      </select>
      <select v-model="topicFilter" class="select">
        <option value="">全部分类</option>
        <option v-for="t in topics" :key="t" :value="t">{{ t }}</option>
      </select>
      <div class="search-box">
        <i class="fa-solid fa-magnifying-glass"></i>
        <input v-model="keyword" type="text" placeholder="搜索文档名…" />
      </div>
      <button class="btn-reconcile" type="button" :disabled="reconciling" @click="onReconcile" title="清理已删除文件残留的向量片段">
        <i class="fa-solid fa-broom" :class="{ spin: reconciling }"></i>
        {{ reconciling ? '对账中…' : '数据对账' }}
      </button>
      <button class="btn-reconcile" type="button" :disabled="reloading" @click="onReload" title="重新加载向量库最新数据（外部改动后无需重启后端）">
        <i class="fa-solid fa-arrows-rotate" :class="{ spin: reloading }"></i>
        {{ reloading ? '重载中…' : '重载知识库' }}
      </button>
    </div>

    <!-- 表格 -->
    <div class="table-card">
      <div v-if="loading" class="table-empty">加载中…</div>
      <div v-else-if="filteredRows.length === 0" class="table-empty">
        暂无文档，点击右上角「上传文档」
      </div>
      <table v-else class="doc-table">
        <thead>
          <tr>
            <th class="col-info">文档信息</th>
            <th>知识主题</th>
            <th>状态</th>
            <th>上传时间</th>
            <th class="col-op">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in pagedRows" :key="row.filename">
            <td class="col-info">
              <div class="doc-cell">
                <span class="doc-type-ico"><i class="fa-regular fa-file-lines"></i></span>
                <div>
                  <strong :title="row.filename">{{ row.filename }}</strong>
                  <small>{{ row.chunk_count }} 片段 · {{ row.ext }}</small>
                </div>
              </div>
            </td>
            <td><span class="topic-tag">{{ row.topic }}</span></td>
            <td><span :class="['status-badge', { pending: row.status === '处理中', failed: row.status === '失败' }]" :title="row.status === '失败' ? row.error : ''">{{ row.status }}</span></td>
            <td class="muted-cell">{{ row.uploadedAt }}</td>
            <td class="col-op">
              <button class="op-link" type="button" @click="openDetail(row)"><i class="fa-regular fa-eye"></i> 详情</button>
              <button class="op-link" type="button" @click="onRename(row)"><i class="fa-solid fa-pen"></i> 重命名</button>
              <button class="op-link danger" type="button" @click="onDelete(row)"><i class="fa-solid fa-trash-can"></i> 删除</button>
            </td>
          </tr>
        </tbody>
      </table>

      <!-- 分页 -->
      <div v-if="filteredRows.length > 0" class="pager">
        <span>共 {{ filteredRows.length }} 条</span>
        <div class="pager-ctrl">
          <button type="button" :disabled="page === 1" @click="page--"><i class="fa-solid fa-chevron-left"></i></button>
          <span>{{ page }} / {{ totalPages }}</span>
          <button type="button" :disabled="page === totalPages" @click="page++"><i class="fa-solid fa-chevron-right"></i></button>
        </div>
      </div>
    </div>

    <p v-if="error" class="msg error archive-msg">{{ error }}</p>
    <p v-if="notice" class="msg notice archive-msg">{{ notice }}</p>

    <!-- 上传弹窗 -->
    <UploadModal
      v-if="showUpload"
      @close="showUpload = false"
      @uploaded="onUploaded"
    />

    <!-- 上传进度面板 -->
    <UploadProgressModal
      v-if="showProgress"
      @close="showProgress = false"
    />

    <!-- 详情弹窗 -->
    <div v-if="detailRow" class="modal-mask" @click.self="detailRow = null">
      <div class="modal detail-modal">
        <div class="modal-head">
          <h3>文档详情</h3>
          <button class="modal-close" type="button" @click="detailRow = null"><i class="fa-solid fa-xmark"></i></button>
        </div>
        <div class="detail-body">
          <div class="detail-row"><label>文件名</label><span>{{ detailRow.filename }}</span></div>
          <div class="detail-row"><label>类型</label><span>{{ detailRow.ext }}</span></div>
          <div class="detail-row"><label>片段数</label><span>{{ detailRow.chunk_count }}</span></div>
          <div class="detail-row"><label>知识主题</label><span>{{ detailRow.topic }}</span></div>
          <div class="detail-row"><label>状态</label><span>{{ detailRow.status }}</span></div>
          <div class="detail-row"><label>上传时间</label><span>{{ detailRow.uploadedAt }}</span></div>
          <div class="detail-row"><label>描述</label><span>{{ detailRow.description || '（无）' }}</span></div>
        </div>
      </div>
    </div>
  </main>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import {
  listDocuments,
  deleteDocument,
  fetchStats,
  fileExt,
  extractErrorMessage,
  reconcile,
  reloadKnowledgeBase,
  KNOWLEDGE_TOPICS,
  type StatsResponse,
  type DocumentItem,
} from '../api/client'
import { useUploadTasks } from '../composables/useUploadTasks'
import { useKnowledgeBase } from '../composables/useKnowledgeBase'
import UploadModal from '../components/UploadModal.vue'
import UploadProgressModal from '../components/UploadProgressModal.vue'

interface DocRow {
  filename: string
  ext: string
  chunk_count: number
  topic: string
  description: string
  status: string
  error: string
  uploadedAt: string
}

const topics = KNOWLEDGE_TOPICS
const { activeCount, completedTick } = useUploadTasks()
const { kbList, currentKbId, selectKb, refreshKbs } = useKnowledgeBase()

const docs = ref<DocumentItem[]>([])
const stats = ref<StatsResponse | null>(null)
const loading = ref(false)
const error = ref('')
const notice = ref('')

const showUpload = ref(false)
const showProgress = ref(false)
const reconciling = ref(false)
const reloading = ref(false)
const detailRow = ref<DocRow | null>(null)

const topicFilter = ref('')
const keyword = ref('')
const page = ref(1)
const pageSize = 10

const statCards = computed(() => [
  { label: '文档总数', value: stats.value?.document_count ?? 0, icon: 'fa-regular fa-file-lines' },
  { label: '知识片段', value: stats.value?.total_chunks ?? 0, icon: 'fa-solid fa-layer-group' },
  { label: '分类数', value: distinctTopics.value, icon: 'fa-solid fa-tags' },
  { label: '就绪文档', value: stats.value?.document_count ?? 0, icon: 'fa-solid fa-circle-check' },
])

const rows = computed<DocRow[]>(() => {
  const perDoc = stats.value?.per_document ?? []
  const chunkOf = (name: string) => perDoc.find((d) => d.filename === name)?.chunk_count ?? 0
  return docs.value.map((doc) => {
    // 片段数优先用向量库统计（真实入库结果），回退到元数据里的 chunk_count。
    const chunks = chunkOf(doc.filename) || doc.chunk_count || 0
    return {
      filename: doc.filename,
      ext: fileExt(doc.filename),
      chunk_count: chunks,
      topic: doc.topic,
      description: doc.description,
      // 直接采用后端权威状态（处理中 / 就绪 / 失败），异步入库后由后台任务实时更新。
      status: doc.status,
      error: doc.error ?? '',
      uploadedAt: doc.uploaded_at,
    }
  })
})

const distinctTopics = computed(
  () => new Set(rows.value.map((r) => r.topic).filter((t) => t && t !== '未分类')).size,
)

const filteredRows = computed(() =>
  rows.value.filter((r) => {
    const okTopic = !topicFilter.value || r.topic === topicFilter.value
    const okKw = !keyword.value || r.filename.toLowerCase().includes(keyword.value.toLowerCase())
    return okTopic && okKw
  }),
)

const totalPages = computed(() => Math.max(1, Math.ceil(filteredRows.value.length / pageSize)))
const pagedRows = computed(() => {
  const start = (page.value - 1) * pageSize
  return filteredRows.value.slice(start, start + pageSize)
})

async function refresh() {
  if (!currentKbId.value) {
    docs.value = []
    stats.value = null
    return
  }
  loading.value = true
  error.value = ''
  try {
    const [rawDocs, s] = await Promise.all([
      listDocuments(currentKbId.value),
      fetchStats(currentKbId.value),
    ])
    docs.value = rawDocs
    stats.value = s
  } catch (e) {
    error.value = extractErrorMessage(e)
  } finally {
    loading.value = false
  }
}

function openDetail(row: DocRow) {
  detailRow.value = row
}

function onRename(_row: DocRow) {
  notice.value = '重命名功能将在接入后端元数据（下一轮 MySQL）后开放'
  window.setTimeout(() => (notice.value = ''), 2600)
}

async function onDelete(row: DocRow) {
  if (!confirm(`确定删除「${row.filename}」？知识库中的片段也会一并删除。`)) return
  error.value = ''
  try {
    await deleteDocument(row.filename, currentKbId.value)
    notice.value = `已删除「${row.filename}」`
    await refresh()
  } catch (e) {
    error.value = extractErrorMessage(e)
  }
}

async function onReload() {
  if (reloading.value) return
  reloading.value = true
  error.value = ''
  try {
    const res = await reloadKnowledgeBase(currentKbId.value)
    notice.value = `已重载知识库，当前共 ${res.total_chunks} 个片段`
    await refresh()
  } catch (e) {
    error.value = extractErrorMessage(e)
  } finally {
    reloading.value = false
    window.setTimeout(() => (notice.value = ''), 3000)
  }
}

function onUploaded(_filename: string) {
  // 上传已交给后台任务，这里关闭上传弹窗并打开进度面板
  showUpload.value = false
  showProgress.value = true
}

async function onReconcile() {
  if (reconciling.value) return
  reconciling.value = true
  error.value = ''
  try {
    const res = await reconcile(currentKbId.value)
    if (res.removed_chunks > 0) {
      const names = res.removed_files.map((f) => f.filename).join('、')
      notice.value = `已清理 ${res.removed_files.length} 个已删除文件的残留（${res.removed_chunks} 个片段）：${names}`
    } else {
      notice.value = '数据一致，无需清理'
    }
    await refresh()
  } catch (e) {
    error.value = extractErrorMessage(e)
  } finally {
    reconciling.value = false
    window.setTimeout(() => (notice.value = ''), 4000)
  }
}

// 任何上传任务成功入库后，自动刷新文档列表与统计
watch(completedTick, () => {
  refresh()
})

// 切换知识库后：重置分页并刷新
watch(currentKbId, () => {
  page.value = 1
  refresh()
})

function onSelectKb(id: number) {
  selectKb(id)
}

onMounted(async () => {
  // 确保知识库列表已加载（App 可能已加载，这里兜底），再拉当前库的文档
  if (kbList.value.length === 0) {
    try {
      await refreshKbs()
    } catch (e) {
      error.value = extractErrorMessage(e)
    }
  }
  await refresh()
})
</script>
