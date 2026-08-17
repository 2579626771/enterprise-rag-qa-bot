<template>
  <div class="login-wrap">
    <div class="login-card">
      <div class="login-brand">
        <i class="fa-solid fa-database"></i>
        <div>
          <strong>Enterprise RAG</strong>
          <span>企业知识库系统</span>
        </div>
      </div>

      <h2 class="login-title">注册账户</h2>
      <p class="login-sub">创建一个普通用户账户，注册后自动登录</p>

      <form class="login-form" @submit.prevent="onSubmit">
        <label class="login-label">
          <i class="fa-solid fa-user"></i>
          <input v-model="username" type="text" placeholder="用户名（字母/数字/_.-@，3-32位）" autocomplete="username" />
        </label>
        <label class="login-label">
          <i class="fa-solid fa-id-badge"></i>
          <input v-model="displayName" type="text" placeholder="显示名（选填，默认同用户名）" />
        </label>
        <label class="login-label">
          <i class="fa-solid fa-lock"></i>
          <input v-model="password" type="password" placeholder="密码（至少 8 位）" autocomplete="new-password" />
        </label>
        <label class="login-label">
          <i class="fa-solid fa-lock"></i>
          <input v-model="password2" type="password" placeholder="再次输入密码" autocomplete="new-password" />
        </label>

        <div class="recovery-box">
          <h3>找回密码问题</h3>
          <p>忘记密码时用于自助重置，请设置只有你知道的答案。</p>
          <div v-for="(item, idx) in recoveryItems" :key="idx" class="recovery-item">
            <input v-model="item.question" class="recovery-input" :placeholder="`问题 ${idx + 1}`" />
            <input v-model="item.answer" class="recovery-input" :placeholder="`答案 ${idx + 1}`" />
          </div>
        </div>

        <p v-if="err" class="login-err">{{ err }}</p>

        <button class="login-btn" type="submit" :disabled="submitting">
          {{ submitting ? '注册中…' : '注 册' }}
        </button>
      </form>

      <p class="login-switch">
        已有账户？<a href="javascript:void(0)" @click="goLogin">返回登录</a>
      </p>
    </div>
    <p class="login-foot">© Enterprise RAG · 企业知识服务</p>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuth } from '../composables/useAuth'
import { extractErrorMessage } from '../api/client'

const router = useRouter()
const { register } = useAuth()

const username = ref('')
const displayName = ref('')
const password = ref('')
const password2 = ref('')
const recoveryItems = ref([
  { question: '', answer: '' },
  { question: '', answer: '' },
  { question: '', answer: '' },
])
const submitting = ref(false)
const err = ref('')

// 与后端一致的前端预校验，提前拦截、减少无效请求
const USERNAME_RE = /^[A-Za-z0-9_.\-@]{3,32}$/

function validate(): string {
  const u = username.value.trim()
  if (!USERNAME_RE.test(u)) return '用户名只能包含字母、数字及 _ . - @，长度 3-32 位'
  if (password.value.length < 8) return '密码至少 8 位'
  if (password.value !== password2.value) return '两次输入的密码不一致'
  for (let i = 0; i < recoveryItems.value.length; i += 1) {
    if (!recoveryItems.value[i].question.trim()) return `请填写第 ${i + 1} 个找回密码问题`
    if (!recoveryItems.value[i].answer.trim()) return `请填写第 ${i + 1} 个找回密码答案`
  }
  return ''
}

async function onSubmit() {
  if (submitting.value) return
  const msg = validate()
  if (msg) {
    err.value = msg
    return
  }
  submitting.value = true
  err.value = ''
  try {
    await register(
      username.value.trim(),
      password.value,
      displayName.value.trim(),
      recoveryItems.value.map((item) => ({ question: item.question.trim(), answer: item.answer.trim() })),
    )
    // 注册成功即自动登录，进入工作台
    router.push({ name: 'chat' })
  } catch (e) {
    err.value = extractErrorMessage(e)
  } finally {
    submitting.value = false
  }
}

function goLogin() {
  router.push({ name: 'login' })
}
</script>

<style scoped>
.login-wrap {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 18px;
  background: linear-gradient(135deg, var(--blue) 0%, var(--blue-deep) 100%);
}
.login-card {
  width: 460px;
  max-width: 90vw;
  background: #fff;
  border-radius: 14px;
  padding: 36px 34px 30px;
  box-shadow: 0 18px 50px rgba(0, 0, 0, 0.25);
}
.login-brand {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 26px;
}
.login-brand i { font-size: 30px; color: var(--blue); }
.login-brand strong { display: block; font-size: 18px; color: var(--blue); }
.login-brand span { font-size: 12px; color: var(--muted); }
.login-title { margin: 0 0 4px; font-size: 22px; color: #1f2a33; }
.login-sub { margin: 0 0 22px; font-size: 13px; color: var(--muted); }
.login-form { display: flex; flex-direction: column; gap: 14px; }
.login-label {
  display: flex;
  align-items: center;
  gap: 10px;
  border: 1px solid var(--line);
  border-radius: 9px;
  padding: 0 14px;
  height: 46px;
  transition: border-color 0.15s;
}
.login-label:focus-within { border-color: var(--blue-2); }
.login-label i { color: var(--muted); width: 16px; text-align: center; }
.login-label input { flex: 1; border: 0; outline: none; background: transparent; font-size: 14px; }
.login-err { margin: 0; color: #d9534f; font-size: 13px; }
.recovery-box { padding: 12px; border: 1px solid var(--line); border-radius: 9px; background: #f8fafc; }
.recovery-box h3 { margin: 0 0 4px; font-size: 14px; color: #1f2a33; }
.recovery-box p { margin: 0 0 10px; color: var(--muted); font-size: 12px; }
.recovery-item { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 8px; }
.recovery-item:last-child { margin-bottom: 0; }
.recovery-input { min-width: 0; height: 36px; border: 1px solid var(--line); border-radius: 7px; padding: 0 10px; outline: none; font-size: 13px; background: #fff; }
.recovery-input:focus { border-color: var(--blue-2); }
.login-btn {
  margin-top: 6px;
  height: 46px;
  border-radius: 9px;
  background: var(--blue);
  color: #fff;
  font-size: 15px;
  letter-spacing: 4px;
  transition: background 0.15s;
}
.login-btn:hover:not(:disabled) { background: var(--blue-deep); }
.login-btn:disabled { opacity: 0.6; cursor: not-allowed; }
.login-switch { margin: 16px 0 0; text-align: center; font-size: 13px; color: var(--muted); }
.login-switch a { color: var(--blue); text-decoration: none; }
.login-switch a:hover { text-decoration: underline; }
.login-foot { color: rgba(255, 255, 255, 0.7); font-size: 12px; }
</style>
