<template>
  <main class="admin-kb">
    <!-- 面包屑 -->
    <div class="crumb">
      <button class="crumb-back" type="button" @click="goUsers">
        <i class="fa-solid fa-arrow-left"></i> 用户列表
      </button>
      <span class="crumb-sep">/</span>
      <button class="crumb-back" type="button" @click="goUserKbs">
        <i class="fa-solid fa-user"></i> {{ ownerLabel }} 的知识库
      </button>
      <span class="crumb-sep">/</span>
      <span class="crumb-cur">
        <i class="fa-solid fa-book"></i>
        {{ kb ? kb.name : '知识库' }} 的文档
      </span>
    </div>

    <div class="akb-head sub">
      <div>
        <h1>{{ kb ? kb.name : '加载中…' }}</h1>
        <p v-if="kb">
          ID #{{ kb.id }} · 属主 {{ ownerLabel }}
          <span v-if="kb.description"> · {{ kb.description }}</span>
        </p>
      </div>
      <button class="btn-ghost" type="button" :disabled="loading" @click="refresh">
        <i class="fa-solid fa-rotate" :class="{ spin: loading }"></i> 刷新
      </button>
    </div>

    <!-- 单行筛选栏：枚举下拉 + 一个综合搜索框 -->
    <div class="filter-toolbar">
      <el-select v-model="f.topic" class="ft-select" filterable clearable placeholder="全部主题">
        <el-option v-for="t in topicOptions" :key="t" :label="t" :value="t" />
      </el-select>
      <el-select v-model="f.status" class="ft-select" filterable clearable placeholder="全部状态">
        <el-option v-for="s in statusOptions" :key="s" :label="s" :value="s" />
      </el-select>
      <el-input v-model="f.kw" class="ft-search" clearable placeholder="搜索文件名 / 描述">
        <template #prefix><i class="fa-solid fa-magnifying-glass" /></template>
      </el-input>
      <span class="ft-spacer" />
      <span class="ft-count">共 {{ filteredDocs.length }} 个文档（全部 {{ docs.length }}）</span>
    </div>

    <div class="table-card">
      <table class="doc-table">
        <thead>
          <tr>
            <th class="c-idx">#</th>
            <th>文档名称</th>
            <th>知识主题</th>
            <th>状态</th>
            <th>上传时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="loading"><td colspan="5" class="table-empty">加载中…</td></tr>
          <tr v-else-if="filteredDocs.length === 0"><td colspan="5" class="table-empty">没有匹配的文档</td></tr>
          <tr v-for="(d, i) in filteredDocs" v-else :key="d.filename">
            <td class="c-idx">{{ i + 1 }}</td>
            <td>
              <div class="doc-cell">
                <span class="doc-type-ico"><i class="fa-regular fa-file-lines"></i></span>
                <div>
                  <strong :title="d.filename">{{ d.filename }}</strong>
                  <small v-if="d.description">{{ d.description }}</small>
                  <small v-else class="muted-cell">{{ fileExt(d.filename) }}</small>
                </div>
              </div>
            </td>
            <td><span class="topic-tag">{{ d.topic }}</span></td>
            <td><span :class="['status-badge', statusClass(d.status)]">{{ d.status }}</span></td>
            <td class="muted-cell">{{ d.uploaded_at }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <p v-if="error" class="msg error akb-msg">{{ error }}</p>
  </main>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  listKbs,
  listUsers,
  listDocuments,
  fileExt,
  extractErrorMessage,
  type KnowledgeBase,
  type DocumentItem,
  type AuthUser,
} from '../api/client'

const props = defineProps<{ userId: string; kbId: string }>()
const router = useRouter()
const kbIdNum = computed(() => Number(props.kbId))

const kb = ref<KnowledgeBase | null>(null)
const owner = ref<AuthUser | null>(null)
const docs = ref<DocumentItem[]>([])
const loading = ref(false)
const error = ref('')

const f = reactive({ kw: '', topic: '', status: '' })

const ownerLabel = computed(() =>
  owner.value ? owner.value.display_name || owner.value.username : `用户 #${props.userId}`,
)

// 主题/状态下拉项：从当前文档集合动态提取，避免出现库里没有的值
const topicOptions = computed(() => [...new Set(docs.value.map((d) => d.topic).filter(Boolean))])
const statusOptions = computed(() => [...new Set(docs.value.map((d) => d.status).filter(Boolean))])

const filteredDocs = computed(() => {
  const kw = f.kw.trim().toLowerCase()
  return docs.value.filter((d) => {
    if (f.topic && d.topic !== f.topic) return false
    if (f.status && d.status !== f.status) return false
    if (kw) {
      const hay = `${d.filename} ${d.description || ''}`.toLowerCase()
      if (!hay.includes(kw)) return false
    }
    return true
  })
})

function statusClass(status: string): string {
  if (status.includes('失败') || status.includes('错误')) return 'failed'
  if (status.includes('处理') || status.includes('入库')) return 'pending'
  return ''
}

async function refresh() {
  loading.value = true
  error.value = ''
  try {
    const [kbRes, users, docList] = await Promise.all([
      listKbs(true),
      listUsers(),
      listDocuments(kbIdNum.value),
    ])
    kb.value = kbRes.kbs.find((k) => k.id === kbIdNum.value) ?? null
    owner.value = users.find((u) => u.id === Number(props.userId)) ?? null
    docs.value = docList
    if (!kb.value) error.value = '知识库不存在或已被删除'
  } catch (e) {
    error.value = extractErrorMessage(e)
  } finally {
    loading.value = false
  }
}

function goUsers() {
  router.push({ name: 'adminkb' })
}
function goUserKbs() {
  router.push({ name: 'admin-user-kbs', params: { userId: props.userId } })
}

onMounted(refresh)
</script>

<style scoped>
.admin-kb { padding: 26px 30px; overflow-y: auto; }
.akb-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 14px; }
.akb-head.sub { margin-top: 6px; }
.akb-head h1 { margin: 0 0 4px; font-size: 22px; }
.akb-head p { margin: 0; color: var(--muted); font-size: 13px; }
.akb-msg { margin-top: 14px; }
.row-hint { color: var(--muted); font-size: 13px; margin-bottom: 12px; }

.crumb { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; font-size: 13px; flex-wrap: wrap; }
.crumb-back {
  display: inline-flex; align-items: center; gap: 6px;
  background: var(--blue-3); color: var(--blue);
  border: none; border-radius: 8px; padding: 6px 12px; cursor: pointer; transition: background .15s;
}
.crumb-back:hover { background: #dbe6f2; }
.crumb-sep { color: var(--muted); }
.crumb-cur { display: inline-flex; align-items: center; gap: 6px; color: #3a4147; font-weight: 600; }

.c-idx { width: 56px; text-align: center; color: var(--muted); }
</style>
