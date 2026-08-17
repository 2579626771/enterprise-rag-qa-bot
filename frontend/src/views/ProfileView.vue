<template>
  <main class="profile-page">
    <div class="profile-head">
      <div>
        <h1>个人中心</h1>
        <p>查看账号信息，维护显示名与登录密码</p>
      </div>
    </div>

    <div v-if="user?.force_password_change" class="force-alert">
      <i class="fa-solid fa-triangle-exclamation"></i>
      <div>
        <strong>当前密码由管理员重置</strong>
        <span>请先修改密码，再继续使用其它功能。</span>
      </div>
    </div>

    <section class="profile-grid">
      <div class="profile-card account-card">
        <div class="profile-avatar"><i class="fa-solid fa-user"></i></div>
        <div class="profile-main">
          <h2>{{ user?.display_name || user?.username }}</h2>
          <p>@{{ user?.username }}</p>
          <span :class="['role-tag', user?.role === 'admin' ? 'admin' : 'user']">
            {{ user?.role === 'admin' ? '管理员' : '普通用户' }}
          </span>
        </div>
        <div class="info-list">
          <div><label>知识库配额</label><span>{{ user?.role === 'admin' ? '∞' : (user?.kb_quota ?? 0) }}</span></div>
          <div><label>创建时间</label><span>{{ user?.created_at || '—' }}</span></div>
          <div><label>上次登录</label><span>{{ user?.last_login_at || '—' }}</span></div>
          <div><label>密码更新</label><span>{{ user?.password_changed_at || '—' }}</span></div>
          <div><label>找回问题</label><span>{{ user?.has_recovery_questions ? '已设置' : '未设置' }}</span></div>
        </div>
      </div>

      <div class="profile-card form-card">
        <h2>基本资料</h2>
        <p class="card-sub">用户名不可修改，可维护工作台显示名。</p>
        <div class="form-row">
          <label class="form-label req">显示名</label>
          <input v-model="profileForm.displayName" class="text-input" placeholder="请输入显示名" />
        </div>
        <p v-if="profileErr" class="msg error">{{ profileErr }}</p>
        <p v-if="profileNotice" class="msg notice">{{ profileNotice }}</p>
        <button class="primary" type="button" :disabled="savingProfile || !profileForm.displayName.trim()" @click="onSaveProfile">
          {{ savingProfile ? '保存中…' : '保存资料' }}
        </button>
      </div>

      <div class="profile-card form-card recovery-card">
        <h2>找回密码问题</h2>
        <p class="card-sub">用于忘记密码时自助重置。旧答案不可查看，保存会覆盖原设置。</p>
        <div v-for="(item, idx) in recoveryItems" :key="idx" class="recovery-item">
          <label class="form-label req">问题 {{ idx + 1 }}</label>
          <input v-model="item.question" class="text-input" :placeholder="`问题 ${idx + 1}`" />
          <label class="form-label req answer-label">答案 {{ idx + 1 }}</label>
          <input v-model="item.answer" class="text-input" :placeholder="`答案 ${idx + 1}`" />
        </div>
        <p v-if="recoveryErr" class="msg error">{{ recoveryErr }}</p>
        <p v-if="recoveryNotice" class="msg notice">{{ recoveryNotice }}</p>
        <button class="primary" type="button" :disabled="savingRecovery" @click="onSaveRecovery">
          {{ savingRecovery ? '保存中…' : '保存找回问题' }}
        </button>
      </div>

      <div class="profile-card form-card password-card">
        <h2>修改密码</h2>
        <p class="card-sub">密码至少 8 位。修改成功后需要使用新密码登录。</p>
        <div class="form-row">
          <label class="form-label req">原密码</label>
          <input v-model="passwordForm.oldPassword" type="password" class="text-input" autocomplete="current-password" />
        </div>
        <div class="form-row">
          <label class="form-label req">新密码</label>
          <input v-model="passwordForm.newPassword" type="password" class="text-input" autocomplete="new-password" />
        </div>
        <div class="form-row">
          <label class="form-label req">确认新密码</label>
          <input v-model="passwordForm.confirmPassword" type="password" class="text-input" autocomplete="new-password" />
        </div>
        <p v-if="passwordErr" class="msg error">{{ passwordErr }}</p>
        <p v-if="passwordNotice" class="msg notice">{{ passwordNotice }}</p>
        <button class="primary" type="button" :disabled="changingPassword" @click="onChangePassword">
          {{ changingPassword ? '修改中…' : '修改密码' }}
        </button>
      </div>
    </section>
  </main>
</template>

<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { changeMyPassword, extractErrorMessage, setRecoveryQuestions, updateMyProfile } from '../api/client'
import { useAuth } from '../composables/useAuth'

const { user, setUser } = useAuth()

const profileForm = reactive({ displayName: user.value?.display_name || '' })
const savingProfile = ref(false)
const profileErr = ref('')
const profileNotice = ref('')

const passwordForm = reactive({ oldPassword: '', newPassword: '', confirmPassword: '' })
const changingPassword = ref(false)
const passwordErr = ref('')
const passwordNotice = ref('')

const recoveryItems = ref([
  { question: '', answer: '' },
  { question: '', answer: '' },
  { question: '', answer: '' },
])
const savingRecovery = ref(false)
const recoveryErr = ref('')
const recoveryNotice = ref('')

watch(
  () => user.value?.display_name,
  (name) => {
    profileForm.displayName = name || user.value?.username || ''
  },
)

async function onSaveProfile() {
  if (savingProfile.value || !profileForm.displayName.trim()) return
  savingProfile.value = true
  profileErr.value = ''
  profileNotice.value = ''
  try {
    const nextUser = await updateMyProfile(profileForm.displayName.trim())
    setUser(nextUser)
    profileNotice.value = '资料已保存'
    window.setTimeout(() => (profileNotice.value = ''), 2600)
  } catch (e) {
    profileErr.value = extractErrorMessage(e)
  } finally {
    savingProfile.value = false
  }
}

function validatePassword(): string {
  if (!passwordForm.oldPassword) return '请输入原密码'
  if (passwordForm.newPassword.length < 8) return '新密码至少 8 位'
  if (passwordForm.newPassword !== passwordForm.confirmPassword) return '两次输入的新密码不一致'
  return ''
}

function validateRecovery(): string {
  for (let i = 0; i < recoveryItems.value.length; i += 1) {
    if (!recoveryItems.value[i].question.trim()) return `请填写第 ${i + 1} 个找回密码问题`
    if (!recoveryItems.value[i].answer.trim()) return `请填写第 ${i + 1} 个找回密码答案`
  }
  return ''
}

async function onSaveRecovery() {
  if (savingRecovery.value) return
  const msg = validateRecovery()
  if (msg) {
    recoveryErr.value = msg
    return
  }
  savingRecovery.value = true
  recoveryErr.value = ''
  recoveryNotice.value = ''
  try {
    const nextUser = await setRecoveryQuestions(
      recoveryItems.value.map((item) => ({ question: item.question.trim(), answer: item.answer.trim() })),
    )
    setUser(nextUser)
    recoveryItems.value = [
      { question: '', answer: '' },
      { question: '', answer: '' },
      { question: '', answer: '' },
    ]
    recoveryNotice.value = '找回密码问题已保存'
    window.setTimeout(() => (recoveryNotice.value = ''), 2600)
  } catch (e) {
    recoveryErr.value = extractErrorMessage(e)
  } finally {
    savingRecovery.value = false
  }
}

async function onChangePassword() {
  if (changingPassword.value) return
  const msg = validatePassword()
  if (msg) {
    passwordErr.value = msg
    return
  }
  changingPassword.value = true
  passwordErr.value = ''
  passwordNotice.value = ''
  try {
    const nextUser = await changeMyPassword(passwordForm.oldPassword, passwordForm.newPassword)
    setUser(nextUser)
    passwordForm.oldPassword = ''
    passwordForm.newPassword = ''
    passwordForm.confirmPassword = ''
    passwordNotice.value = '密码已修改'
    window.setTimeout(() => (passwordNotice.value = ''), 2600)
  } catch (e) {
    passwordErr.value = extractErrorMessage(e)
  } finally {
    changingPassword.value = false
  }
}
</script>

<style scoped>
.profile-page { flex: 1; min-height: 0; overflow-y: auto; padding: 26px 30px; background: #f5f7fa; }
.profile-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 18px; }
.profile-head h1 { margin: 0 0 4px; font-size: 22px; }
.profile-head p { margin: 0; color: var(--muted); font-size: 13px; }
.force-alert {
  display: flex; gap: 12px; align-items: flex-start; max-width: 960px;
  margin-bottom: 16px; padding: 12px 14px; border: 1px solid #f2dca6; border-radius: 10px;
  background: #fff6e5; color: #9a640f;
}
.force-alert i { margin-top: 2px; }
.force-alert strong { display: block; font-size: 14px; }
.force-alert span { display: block; margin-top: 2px; font-size: 13px; }
.profile-grid { display: grid; grid-template-columns: minmax(280px, 360px) minmax(320px, 1fr); gap: 16px; align-items: start; }
.profile-card { border: 1px solid var(--line); border-radius: 12px; background: #fff; padding: 20px; box-shadow: 0 1px 3px rgb(0 0 0 / 4%); }
.account-card { grid-row: span 3; }
.profile-avatar { width: 58px; height: 58px; display: grid; place-items: center; border-radius: 16px; background: var(--blue-3); color: var(--blue); font-size: 24px; }
.profile-main { margin-top: 14px; }
.profile-main h2 { margin: 0 0 4px; font-size: 20px; }
.profile-main p { margin: 0 0 10px; color: var(--muted); font-size: 13px; }
.role-tag { display: inline-flex; font-size: 12px; padding: 3px 10px; border-radius: 10px; }
.role-tag.admin { background: #fdeede; color: var(--orange); }
.role-tag.user { background: var(--blue-3); color: var(--blue); }
.info-list { margin-top: 18px; border-top: 1px solid #f0f2f5; }
.info-list div { display: flex; justify-content: space-between; gap: 14px; padding: 12px 0; border-bottom: 1px solid #f0f2f5; font-size: 13px; }
.info-list label { color: var(--muted); }
.info-list span { color: #26333f; text-align: right; }
.form-card h2 { margin: 0 0 4px; font-size: 17px; }
.card-sub { margin: 0 0 18px; color: var(--muted); font-size: 13px; }
.text-input { width: 100%; height: 40px; border: 1px solid var(--line); border-radius: 8px; padding: 0 12px; outline: none; }
.text-input:focus { border-color: var(--blue-2); }
.form-card .msg { margin: 0 0 12px; padding: 8px 10px; border-radius: 8px; font-size: 13px; }
.password-card, .recovery-card { max-width: 640px; }
.recovery-item { padding: 10px 0; border-bottom: 1px solid #f0f2f5; }
.recovery-item:last-of-type { border-bottom: 0; }
.answer-label { margin-top: 10px; }
@media (max-width: 960px) { .profile-grid { grid-template-columns: 1fr; } .account-card { grid-row: auto; } }
</style>
