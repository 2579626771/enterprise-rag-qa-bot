<template>
  <div class="login-wrap">
    <div class="login-card forgot-card">
      <div class="login-brand">
        <i class="fa-solid fa-database"></i>
        <div>
          <strong>Enterprise RAG</strong>
          <span>企业知识库系统</span>
        </div>
      </div>

      <h2 class="login-title">找回密码</h2>
      <p class="login-sub">请输入登录用户名，通过注册时设置的 3 个问题自助重置密码</p>

      <form v-if="step === 1" class="login-form" @submit.prevent="onFetchQuestions">
        <label class="login-label">
          <i class="fa-solid fa-user"></i>
          <input v-model="username" type="text" placeholder="请输入登录用户名（不是显示名）" autocomplete="username" />
        </label>
        <p v-if="err" class="login-err">{{ err }}</p>
        <button class="login-btn" type="submit" :disabled="loading || !username.trim()">
          {{ loading ? '查询中…' : '下一步' }}
        </button>
      </form>

      <form v-else class="login-form" @submit.prevent="onResetPassword">
        <div class="question-box">
          <div v-for="(q, idx) in questions" :key="idx" class="question-item">
            <label>{{ idx + 1 }}. {{ q }}</label>
            <input v-model="answers[idx]" class="plain-input" :placeholder="`答案 ${idx + 1}`" />
          </div>
        </div>
        <label class="login-label">
          <i class="fa-solid fa-lock"></i>
          <input v-model="newPassword" type="password" placeholder="新密码（至少 8 位）" autocomplete="new-password" />
        </label>
        <label class="login-label">
          <i class="fa-solid fa-lock"></i>
          <input v-model="newPassword2" type="password" placeholder="再次输入新密码" autocomplete="new-password" />
        </label>
        <p v-if="err" class="login-err">{{ err }}</p>
        <p v-if="notice" class="login-ok">{{ notice }}</p>
        <button class="login-btn" type="submit" :disabled="loading">
          {{ loading ? '重置中…' : '重置密码' }}
        </button>
        <button class="back-btn" type="button" @click="backToStep1">返回上一步</button>
      </form>

      <p class="login-switch">
        想起密码了？<a href="javascript:void(0)" @click="goLogin">返回登录</a>
      </p>
    </div>
    <p class="login-foot">© Enterprise RAG · 企业知识服务</p>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { extractErrorMessage, fetchRecoveryQuestions, resetPasswordByRecovery } from '../api/client'

const router = useRouter()
const step = ref<1 | 2>(1)
const username = ref('')
const questions = ref<string[]>([])
const answers = ref(['', '', ''])
const newPassword = ref('')
const newPassword2 = ref('')
const loading = ref(false)
const err = ref('')
const notice = ref('')

async function onFetchQuestions() {
  if (loading.value || !username.value.trim()) return
  loading.value = true
  err.value = ''
  try {
    questions.value = await fetchRecoveryQuestions(username.value.trim())
    answers.value = ['', '', '']
    step.value = 2
  } catch (e) {
    err.value = extractErrorMessage(e)
  } finally {
    loading.value = false
  }
}

function validateReset(): string {
  for (let i = 0; i < answers.value.length; i += 1) {
    if (!answers.value[i].trim()) return `请填写第 ${i + 1} 个问题的答案`
  }
  if (newPassword.value.length < 8) return '新密码至少 8 位'
  if (newPassword.value !== newPassword2.value) return '两次输入的新密码不一致'
  return ''
}

async function onResetPassword() {
  if (loading.value) return
  const msg = validateReset()
  if (msg) {
    err.value = msg
    return
  }
  loading.value = true
  err.value = ''
  notice.value = ''
  try {
    await resetPasswordByRecovery(username.value.trim(), answers.value.map((a) => a.trim()), newPassword.value)
    notice.value = '密码已重置，请使用新密码登录'
    window.setTimeout(() => router.push({ name: 'login' }), 1200)
  } catch (e) {
    err.value = extractErrorMessage(e)
  } finally {
    loading.value = false
  }
}

function backToStep1() {
  step.value = 1
  err.value = ''
  notice.value = ''
}

function goLogin() {
  router.push({ name: 'login' })
}
</script>

<style scoped>
.login-wrap { min-height: 100vh; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 18px; background: linear-gradient(135deg, var(--blue) 0%, var(--blue-deep) 100%); }
.login-card { width: 420px; max-width: 90vw; background: #fff; border-radius: 14px; padding: 36px 34px 30px; box-shadow: 0 18px 50px rgba(0, 0, 0, 0.25); }
.login-brand { display: flex; align-items: center; gap: 12px; margin-bottom: 26px; }
.login-brand i { font-size: 30px; color: var(--blue); }
.login-brand strong { display: block; font-size: 18px; color: var(--blue); }
.login-brand span { font-size: 12px; color: var(--muted); }
.login-title { margin: 0 0 4px; font-size: 22px; color: #1f2a33; }
.login-sub { margin: 0 0 22px; font-size: 13px; color: var(--muted); }
.login-form { display: flex; flex-direction: column; gap: 14px; }
.login-label { display: flex; align-items: center; gap: 10px; border: 1px solid var(--line); border-radius: 9px; padding: 0 14px; height: 46px; transition: border-color 0.15s; }
.login-label:focus-within { border-color: var(--blue-2); }
.login-label i { color: var(--muted); width: 16px; text-align: center; }
.login-label input { flex: 1; border: 0; outline: none; background: transparent; font-size: 14px; }
.question-box { padding: 12px; border: 1px solid var(--line); border-radius: 9px; background: #f8fafc; }
.question-item { margin-bottom: 10px; }
.question-item:last-child { margin-bottom: 0; }
.question-item label { display: block; margin-bottom: 6px; color: #35433f; font-size: 13px; }
.plain-input { width: 100%; height: 38px; border: 1px solid var(--line); border-radius: 7px; padding: 0 10px; outline: none; background: #fff; }
.plain-input:focus { border-color: var(--blue-2); }
.login-err { margin: 0; color: #d9534f; font-size: 13px; }
.login-ok { margin: 0; color: #1d6f42; font-size: 13px; }
.login-btn { margin-top: 6px; height: 46px; border-radius: 9px; background: var(--blue); color: #fff; font-size: 15px; letter-spacing: 4px; transition: background 0.15s; }
.login-btn:hover:not(:disabled) { background: var(--blue-deep); }
.login-btn:disabled { opacity: 0.6; cursor: not-allowed; }
.back-btn { color: var(--muted); font-size: 13px; }
.back-btn:hover { color: var(--blue); text-decoration: underline; }
.login-switch { margin: 16px 0 0; text-align: center; font-size: 13px; color: var(--muted); }
.login-switch a { color: var(--blue); text-decoration: none; }
.login-switch a:hover { text-decoration: underline; }
.login-foot { color: rgba(255, 255, 255, 0.7); font-size: 12px; }
</style>
