<template>
  <main class="admin-kb">
    <div class="akb-head">
      <div>
        <h1>知识库管理 <span class="pill">仅管理员</span></h1>
        <p>查看与管理全部用户的知识库及其文档</p>
      </div>
      <button class="btn-ghost" type="button" :disabled="loading" @click="refresh">
        <i class="fa-solid fa-rotate" :class="{ spin: loading }"></i> 刷新
      </button>
    </div>

    <div class="table-card">
      <div v-if="loading" class="table-empty">加载中…</div>
      <div v-else-if="kbs.length === 0" class="table-empty">暂无知识库</div>
      <table v-else class="doc-table">
        <thead>
          <tr>
            <th>知识库</th>
            <th>所属用户</th>
            <th>描述</th>
            <th>创建时间</th>
            <th class="col-op">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="kb in kbs" :key="kb.id">
            <td>
              <div class="doc-cell">
                <span class="doc-type-ico"><i class="fa-solid fa-book"></i></span>
                <div>
                  <strong>{{ kb.name }}</strong>
                  <small>ID #{{ kb.id }}</small>
                </div>
              </div>
            </td>
            <td><span class="owner-tag">{{ ownerName(kb.owner_id) }}</span></td>
            <td class="muted-cell">{{ kb.description || '—' }}</td>
            <td class="muted-cell">{{ kb.created_at || '—' }}</td>
            <td class="col-op">
              <button class="op-link" type="button" @click="viewDocs(kb)">
                <i class="fa-regular fa-eye"></i> 查看文档
              </button>
              <button class="op-link danger" type="button" @click="onDelete(kb)">
                <i class="fa-solid fa-trash-can"></i> 删除
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <p v-if="error" class="msg error akb-msg">{{ error }}</p>
    <p v-if="notice" class="msg notice akb-msg">{{ notice }}</p>

    <!-- 文档列表弹窗 -->
    <div v-if="detailKb" class="modal-mask" @click.self="detailKb = null">
      <div class="modal doc-list-modal">
        <div class="modal-head">
          <h3>
            <i class="fa-solid fa-book"></i>
            「{{ detailKb.name }}」的文档
            <span class="owner-inline">{{ ownerName(detailKb.owner_id) }}</span>
          </h3>
          <button class="modal-close" type="button" @click="detailKb = null"><i class="fa-solid fa-xmark"></i></button>
        </div>
        <div class="doc-list-body">
          <div v-if="docsLoading" class="table-empty">加载中…</div>
          <div v-else-if="docs.length === 0" class="table-empty">该知识库暂无文档</div>
          <template v-else>
            <div class="doc-list-summary">共 {{ docs.length }} 个文档</div>
            <table class="doc-list-table">
              <thead>
                <tr>
                  <th class="c-idx">#</th>
                  <th class="c-name">文档名称</th>
                  <th class="c-topic">知识主题</th>
                  <th class="c-status">状态</th>
                  <th class="c-time">上传时间</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(d, i) in docs" :key="d.filename">
                  <td class="c-idx">{{ i + 1 }}</td>
                  <td class="c-name">
                    <div class="doc-name-cell">
                      <span class="doc-ico"><i class="fa-regular fa-file-lines"></i></span>
                      <div class="doc-name-text">
                        <strong :title="d.filename">{{ d.filename }}</strong>
                        <small v-if="d.description">{{ d.description }}</small>
                      </div>
                    </div>
                  </td>
                  <td class="c-topic"><span class="topic-tag">{{ d.topic }}</span></td>
                  <td class="c-status"><span class="status-badge">{{ d.status }}</span></td>
                  <td class="c-time muted-cell">{{ d.uploaded_at }}</td>
                </tr>
              </tbody>
            </table>
          </template>
        </div>
      </div>
    </div>
  </main>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import {
  listKbs,
  listUsers,
  listDocuments,
  deleteKb,
  extractErrorMessage,
  type KnowledgeBase,
  type DocumentItem,
  type AuthUser,
} from '../api/client'

const kbs = ref<KnowledgeBase[]>([])
const usersMap = ref<Record<number, string>>({})
const loading = ref(false)
const error = ref('')
const notice = ref('')

const detailKb = ref<KnowledgeBase | null>(null)
const docs = ref<DocumentItem[]>([])
const docsLoading = ref(false)

function ownerName(ownerId: number): string {
  return usersMap.value[ownerId] || `用户 #${ownerId}`
}

async function refresh() {
  loading.value = true
  error.value = ''
  try {
    const [kbRes, users] = await Promise.all([listKbs(true), listUsers()])
    kbs.value = kbRes.kbs
    const map: Record<number, string> = {}
    users.forEach((u: AuthUser) => {
      map[u.id] = u.display_name || u.username
    })
    usersMap.value = map
  } catch (e) {
    error.value = extractErrorMessage(e)
  } finally {
    loading.value = false
  }
}

async function viewDocs(kb: KnowledgeBase) {
  detailKb.value = kb
  docs.value = []
  docsLoading.value = true
  try {
    docs.value = await listDocuments(kb.id)
  } catch (e) {
    error.value = extractErrorMessage(e)
  } finally {
    docsLoading.value = false
  }
}

async function onDelete(kb: KnowledgeBase) {
  if (!confirm(`确定删除「${kb.name}」（属主：${ownerName(kb.owner_id)}）？其中所有文档与向量都会被清除，不可恢复。`)) return
  error.value = ''
  try {
    await deleteKb(kb.id)
    notice.value = `已删除知识库「${kb.name}」`
    await refresh()
    window.setTimeout(() => (notice.value = ''), 2600)
  } catch (e) {
    error.value = extractErrorMessage(e)
  }
}

onMounted(refresh)
</script>

<style scoped>
.admin-kb { padding: 26px 30px; overflow-y: auto; }
.akb-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 20px; }
.akb-head h1 { margin: 0 0 4px; font-size: 22px; }
.akb-head p { margin: 0; color: var(--muted); font-size: 13px; }
.pill { font-size: 12px; padding: 2px 10px; border-radius: 10px; background: var(--blue-3); color: var(--blue); vertical-align: middle; }
.owner-tag { font-size: 12px; padding: 3px 10px; border-radius: 10px; background: var(--blue-3); color: var(--blue); }
.akb-msg { margin-top: 14px; }

/* 文档列表弹窗：加宽、规整的列表 */
.doc-list-modal {
  width: 720px;
  max-width: 92vw;
}
.doc-list-modal .modal-head h3 {
  display: flex;
  align-items: center;
  gap: 8px;
}
.doc-list-modal .modal-head h3 > i { color: var(--blue); }
.owner-inline {
  font-size: 12px;
  padding: 2px 10px;
  border-radius: 10px;
  background: var(--blue-3);
  color: var(--blue);
  font-weight: 400;
}
.doc-list-body { padding: 8px 4px 4px; max-height: 60vh; overflow-y: auto; }
.doc-list-summary { color: var(--muted); font-size: 13px; margin: 0 8px 10px; }
.doc-list-table {
  width: 100%;
  border-collapse: collapse;
}
.doc-list-table thead th {
  text-align: left;
  font-size: 12px;
  color: var(--muted);
  font-weight: 500;
  padding: 8px 10px;
  border-bottom: 1px solid var(--line);
  white-space: nowrap;
}
.doc-list-table tbody td {
  padding: 12px 10px;
  border-bottom: 1px solid #f0f2f4;
  vertical-align: middle;
  font-size: 13px;
}
.doc-list-table tbody tr:hover { background: #f7f9fb; }
.c-idx { width: 40px; color: var(--muted); text-align: center; }
.c-topic { width: 110px; }
.c-status { width: 80px; }
.c-time { width: 130px; }
.doc-name-cell { display: flex; align-items: center; gap: 10px; }
.doc-ico {
  width: 32px; height: 32px;
  flex: 0 0 32px;
  border-radius: 8px;
  background: var(--blue-3);
  color: var(--blue);
  display: flex; align-items: center; justify-content: center;
}
.doc-name-text { min-width: 0; }
.doc-name-text strong {
  display: block;
  font-size: 14px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.doc-name-text small { color: var(--muted); font-size: 12px; }
.topic-tag {
  font-size: 12px;
  padding: 3px 10px;
  border-radius: 10px;
  background: var(--blue-3);
  color: var(--blue);
  white-space: nowrap;
}
.status-badge {
  font-size: 12px;
  padding: 3px 10px;
  border-radius: 10px;
  background: #e3f5e8;
  color: #2e9e5b;
  white-space: nowrap;
}
</style>
