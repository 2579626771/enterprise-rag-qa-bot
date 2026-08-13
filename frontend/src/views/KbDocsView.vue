<template>
  <main class="archive">
    <!-- 面包屑：返回知识库列表 -->
    <div class="crumb">
      <button class="crumb-back" type="button" @click="goList">
        <i class="fa-solid fa-arrow-left"></i> 我的知识库
      </button>
      <span class="crumb-sep">/</span>
      <span class="crumb-cur">
        <i class="fa-solid fa-book"></i>
        {{ currentKb ? currentKb.name : '知识库' }}
      </span>
    </div>

    <!-- 页头：当前知识库名称 + 操作 -->
    <div class="archive-head">
      <div>
        <h1>{{ currentKb ? currentKb.name : '加载中…' }} <span class="pill">文档工作区</span></h1>
        <p>
          {{ currentKb?.description || '（无描述）' }}
          <span class="head-count"> · 共 {{ rows.length }} 篇文档</span>
        </p>
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

    <!-- 筛选栏（已去掉知识库下拉：进来即锁定当前库）-->
    <div class="filter-bar">
      <select v-model="topicFilter" class="select">
        <option value="">全部分类</option>
        <option v-for="t in topics" :key="t" :value="t">{{ t }}</option>
      </select>
      <button class="btn-reconcile" type="button" @click="openTopicManager" title="管理当前知识库的主题分类">
        <i class="fa-solid fa-tags"></i>
        管理分类
      </button>
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

    <!-- 主题分类管理弹窗（针对当前知识库）-->
    <div v-if="showTopicManager" class="modal-mask" @click.self="showTopicManager = false">
      <div class="modal">
        <div class="modal-head">
          <h3>管理分类 · {{ currentKb?.name || '当前知识库' }}</h3>
          <button class="modal-close" type="button" @click="showTopicManager = false"><i class="fa-solid fa-xmark"></i></button>
        </div>
        <div class="detail-body">
          <!-- 新增 -->
          <div class="topic-add">
            <input
              v-model="newTopic"
              class="text-input"
              placeholder="输入新分类名称，回车或点新增"
              @keydown.enter="onAddTopic"
            />
            <button class="primary" type="button" :disabled="topicBusy || !newTopic.trim()" @click="onAddTopic">新增</button>
          </div>

          <!-- 列表 + 行内改名/删除 -->
          <ul class="topic-list">
            <li v-for="t in items" :key="t.id" class="topic-row">
              <template v-if="editingTopicId === t.id">
                <input v-model="editingTopicName" class="text-input" @keydown.enter="onSaveTopic(t.id)" />
                <div class="topic-ops">
                  <button class="op-link" type="button" :disabled="topicBusy || !editingTopicName.trim()" @click="onSaveTopic(t.id)">保存</button>
                  <button class="op-link" type="button" @click="cancelEditTopic">取消</button>
                </div>
              </template>
              <template v-else>
                <span class="topic-name">{{ t.name }}</span>
                <div class="topic-ops">
                  <button class="op-link" type="button" title="重命名" @click="startEditTopic(t.id, t.name)"><i class="fa-solid fa-pen"></i></button>
                  <button class="op-link danger" type="button" title="删除" @click="onDeleteTopic(t)"><i class="fa-solid fa-trash-can"></i></button>
                </div>
              </template>
            </li>
            <li v-if="items.length === 0" class="topic-empty">该知识库暂无分类，添加一个吧</li>
          </ul>

          <p class="topic-hint"><i class="fa-solid fa-circle-info"></i> 重命名会同步更新本库下使用该分类的文档；删除仅移除候选，已上传文档保留原分类标签。</p>
          <p v-if="topicErr" class="msg error">{{ topicErr }}</p>
        </div>
        <div class="modal-foot">
          <button class="btn-ghost" type="button" @click="showTopicManager = false">关闭</button>
        </div>
      </div>
    </div>
  </main>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  listDocuments,
  deleteDocument,
  fetchStats,
  fileExt,
  extractErrorMessage,
  reconcile,
  reloadKnowledgeBase,
  type StatsResponse,
  type DocumentItem,
} from '../api/client'
import { useUploadTasks } from '../composables/useUploadTasks'
import { useKnowledgeBase } from '../composables/useKnowledgeBase'
import { useTopics } from '../composables/useTopics'
import UploadModal from '../components/UploadModal.vue'
import UploadProgressModal from '../components/UploadProgressModal.vue'

// 库详情：kbId 由路由参数传入（props: true）
const props = defineProps<{ kbId: string }>()
const router = useRouter()

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

const { topics, items, ensureLoaded: ensureTopics, addTopic, editTopic, removeTopic } = useTopics()
const { activeCount, completedTick } = useUploadTasks()
const { kbList, currentKbId, currentKb, selectKb, refreshKbs } = useKnowledgeBase()

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

// 主题分类管理弹窗状态
const showTopicManager = ref(false)
const newTopic = ref('')
const editingTopicId = ref<number | null>(null)
const editingTopicName = ref('')
const topicBusy = ref(false)
const topicErr = ref('')

const topicFilter = ref('')
const keyword = ref('')
const page = ref(1)
const pageSize = 10

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
      status: doc.status,
      error: doc.error ?? '',
      uploadedAt: doc.uploaded_at,
    }
  })
})

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

function goList() {
  router.push({ name: 'kb' })
}

function openDetail(row: DocRow) {
  detailRow.value = row
}

// ---- 主题分类管理 ----
function openTopicManager() {
  if (!currentKbId.value) {
    notice.value = '请先选择一个知识库'
    window.setTimeout(() => (notice.value = ''), 2600)
    return
  }
  topicErr.value = ''
  newTopic.value = ''
  cancelEditTopic()
  showTopicManager.value = true
  void ensureTopics()
}

async function onAddTopic() {
  const name = newTopic.value.trim()
  if (!name || topicBusy.value) return
  topicBusy.value = true
  topicErr.value = ''
  try {
    await addTopic(name)
    newTopic.value = ''
    await refresh()
  } catch (e) {
    topicErr.value = extractErrorMessage(e)
  } finally {
    topicBusy.value = false
  }
}

function startEditTopic(id: number, name: string) {
  editingTopicId.value = id
  editingTopicName.value = name
  topicErr.value = ''
}

function cancelEditTopic() {
  editingTopicId.value = null
  editingTopicName.value = ''
}

async function onSaveTopic(id: number) {
  const name = editingTopicName.value.trim()
  if (!name || topicBusy.value) return
  topicBusy.value = true
  topicErr.value = ''
  try {
    await editTopic(id, name)
    cancelEditTopic()
    await refresh()
  } catch (e) {
    topicErr.value = extractErrorMessage(e)
  } finally {
    topicBusy.value = false
  }
}

async function onDeleteTopic(t: { id: number; name: string }) {
  if (!confirm(`确定删除分类「${t.name}」？已上传文档会保留原分类标签，仅从候选中移除。`)) return
  topicBusy.value = true
  topicErr.value = ''
  try {
    await removeTopic(t.id)
  } catch (e) {
    topicErr.value = extractErrorMessage(e)
  } finally {
    topicBusy.value = false
  }
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

// 切换库（含路由参数变化）后：重置分页、对齐全局当前库、刷新
watch(
  () => props.kbId,
  async (val) => {
    const id = Number(val)
    if (!id) return
    page.value = 1
    if (kbList.value.length === 0) {
      try {
        await refreshKbs()
      } catch (e) {
        error.value = extractErrorMessage(e)
      }
    }
    // 校验归属：库不存在（无权限/已删除）则退回列表
    if (!kbList.value.some((k) => k.id === id)) {
      error.value = '知识库不存在或无权访问'
      router.replace({ name: 'kb' })
      return
    }
    // 对齐全局当前库：上传弹窗 / 分类 / 上传任务都依赖 currentKbId
    selectKb(id)
    await refresh()
  },
  { immediate: true },
)

onMounted(() => {
  void ensureTopics()
})
</script>

<style scoped>
.crumb { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; font-size: 13px; flex-wrap: wrap; }
.crumb-back {
  display: inline-flex; align-items: center; gap: 6px;
  background: var(--blue-3); color: var(--blue);
  border: none; border-radius: 8px; padding: 6px 12px; cursor: pointer; transition: background .15s;
}
.crumb-back:hover { background: #dbe6f2; }
.crumb-sep { color: var(--muted); }
.crumb-cur { display: inline-flex; align-items: center; gap: 6px; color: #3a4147; font-weight: 600; }
.head-count { color: var(--muted); }
</style>
