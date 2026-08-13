<template>
  <main class="account">
    <div class="account-head">
      <div>
        <h1>账户管理 <span class="pill">仅管理员</span></h1>
        <p>创建与管理系统用户账号</p>
      </div>
      <button class="primary lg" type="button" @click="showCreate = true">
        <i class="fa-solid fa-user-plus"></i> 新建用户
      </button>
    </div>

    <div class="table-card">
      <div v-if="loading" class="table-empty">加载中…</div>
      <table v-else class="doc-table">
        <thead>
          <tr>
            <th>用户名</th>
            <th>显示名</th>
            <th>角色</th>
            <th>创建时间</th>
            <th class="col-op">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="u in users" :key="u.id">
            <td><strong>{{ u.username }}</strong></td>
            <td>{{ u.display_name }}</td>
            <td>
              <span :class="['role-tag', u.role === 'admin' ? 'admin' : 'user']">
                {{ u.role === 'admin' ? '管理员' : '普通用户' }}
              </span>
            </td>
            <td class="muted-cell">{{ u.created_at || '—' }}</td>
            <td class="col-op">
              <button
                class="op-link danger"
                type="button"
                :disabled="u.id === currentUser?.id"
                :title="u.id === currentUser?.id ? '不能删除自己' : '删除用户'"
                @click="onDelete(u)"
              >
                <i class="fa-solid fa-trash-can"></i> 删除
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <p v-if="error" class="msg error account-msg">{{ error }}</p>
    <p v-if="notice" class="msg notice account-msg">{{ notice }}</p>

    <!-- 新建用户弹窗 -->
    <div v-if="showCreate" class="modal-mask" @click.self="showCreate = false">
      <div class="modal">
        <div class="modal-head">
          <h3>新建用户</h3>
          <button class="modal-close" type="button" @click="showCreate = false">
            <i class="fa-solid fa-xmark"></i>
          </button>
        </div>
        <div class="detail-body">
          <div class="form-row">
            <label class="form-label req">用户名</label>
            <input v-model="form.username" class="text-input" placeholder="登录用户名" />
          </div>
          <div class="form-row">
            <label class="form-label">显示名</label>
            <input v-model="form.display_name" class="text-input" placeholder="选填，默认同用户名" />
          </div>
          <div class="form-row">
            <label class="form-label req">密码</label>
            <input v-model="form.password" type="password" class="text-input" placeholder="登录密码" />
          </div>
          <div class="form-row">
            <label class="form-label req">角色</label>
            <select v-model="form.role" class="select full">
              <option value="user">普通用户</option>
              <option value="admin">管理员</option>
            </select>
          </div>
          <p v-if="createErr" class="msg error">{{ createErr }}</p>
        </div>
        <div class="modal-foot">
          <button class="btn-ghost" type="button" @click="showCreate = false">取消</button>
          <button class="primary" type="button" :disabled="creating || !canCreate" @click="onCreate">
            {{ creating ? '创建中…' : '确定创建' }}
          </button>
        </div>
      </div>
    </div>
  </main>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import {
  listUsers,
  createUser,
  deleteUser,
  extractErrorMessage,
  type AuthUser,
} from '../api/client'
import { useAuth } from '../composables/useAuth'

const { user: currentUser } = useAuth()

const users = ref<AuthUser[]>([])
const loading = ref(false)
const error = ref('')
const notice = ref('')

const showCreate = ref(false)
const creating = ref(false)
const createErr = ref('')
const form = reactive({ username: '', password: '', display_name: '', role: 'user' })

const canCreate = computed(() => !!form.username.trim() && !!form.password)

async function refresh() {
  loading.value = true
  error.value = ''
  try {
    users.value = await listUsers()
  } catch (e) {
    error.value = extractErrorMessage(e)
  } finally {
    loading.value = false
  }
}

async function onCreate() {
  if (creating.value || !canCreate.value) return
  creating.value = true
  createErr.value = ''
  try {
    await createUser({
      username: form.username.trim(),
      password: form.password,
      role: form.role,
      display_name: form.display_name.trim(),
    })
    showCreate.value = false
    form.username = ''
    form.password = ''
    form.display_name = ''
    form.role = 'user'
    notice.value = '用户创建成功'
    await refresh()
    window.setTimeout(() => (notice.value = ''), 2600)
  } catch (e) {
    createErr.value = extractErrorMessage(e)
  } finally {
    creating.value = false
  }
}

async function onDelete(u: AuthUser) {
  if (u.id === currentUser.value?.id) return
  if (!confirm(`确定删除用户「${u.username}」？`)) return
  error.value = ''
  try {
    await deleteUser(u.id)
    notice.value = `已删除用户「${u.username}」`
    await refresh()
    window.setTimeout(() => (notice.value = ''), 2600)
  } catch (e) {
    error.value = extractErrorMessage(e)
  }
}

onMounted(refresh)
</script>

<style scoped>
.account {
  padding: 26px 30px;
  overflow-y: auto;
}
.account-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 20px;
}
.account-head h1 {
  margin: 0 0 4px;
  font-size: 22px;
}
.account-head p {
  margin: 0;
  color: var(--muted);
  font-size: 13px;
}
.pill {
  font-size: 12px;
  padding: 2px 10px;
  border-radius: 10px;
  background: var(--blue-3);
  color: var(--blue);
  vertical-align: middle;
}
.role-tag {
  font-size: 12px;
  padding: 3px 10px;
  border-radius: 10px;
}
.role-tag.admin {
  background: #fdeede;
  color: var(--orange);
}
.role-tag.user {
  background: var(--blue-3);
  color: var(--blue);
}
.text-input {
  width: 100%;
  height: 40px;
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 0 12px;
  outline: none;
}
.text-input:focus {
  border-color: var(--blue-2);
}
.account-msg {
  margin-top: 14px;
}
</style>
