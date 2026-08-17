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

      <h2 class="login-title">登录</h2>
      <p class="login-sub">请输入账号密码进入知识工作台</p>

      <form class="login-form" @submit.prevent="onSubmit">
        <label class="login-label">
          <i class="fa-solid fa-user"></i>
          <input v-model="username" type="text" placeholder="用户名" autocomplete="username" />
        </label>
        <label class="login-label">
          <i class="fa-solid fa-lock"></i>
          <input v-model="password" type="password" placeholder="密码" autocomplete="current-password" />
        </label>

        <p v-if="err" class="login-err">{{ err }}</p>

        <button class="login-btn" type="submit" :disabled="submitting || !username || !password">
          {{ submitting ? '登录中…' : '登 录' }}
        </button>
      </form>

      <p class="login-help">
        <a href="javascript:void(0)" @click="goForgotPassword">忘记密码？</a>
        可用登录用户名和注册时设置的问题自助重置
      </p>
      <p class="login-switch">
        还没有账户？<a href="javascript:void(0)" @click="goRegister">注册一个</a>
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
const { login } = useAuth()

const username = ref('')
const password = ref('')
const submitting = ref(false)
const err = ref('')

function goRegister() {
  router.push({ name: 'register' })
}

function goForgotPassword() {
  router.push({ name: 'forgot-password' })
}

async function onSubmit() {
  if (submitting.value || !username.value || !password.value) return
  submitting.value = true
  err.value = ''
  try {
    await login(username.value.trim(), password.value)
    // 登录成功：跳转到工作台首页（智能问答）
    router.push({ name: 'chat' })
  } catch (e) {
    err.value = extractErrorMessage(e)
  } finally {
    submitting.value = false
  }
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
  width: 380px;
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
.login-brand i {
  font-size: 30px;
  color: var(--blue);
}
.login-brand strong {
  display: block;
  font-size: 18px;
  color: var(--blue);
}
.login-brand span {
  font-size: 12px;
  color: var(--muted);
}

.login-title {
  margin: 0 0 4px;
  font-size: 22px;
  color: #1f2a33;
}
.login-sub {
  margin: 0 0 22px;
  font-size: 13px;
  color: var(--muted);
}

.login-form {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
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
.login-label:focus-within {
  border-color: var(--blue-2);
}
.login-label i {
  color: var(--muted);
  width: 16px;
  text-align: center;
}
.login-label input {
  flex: 1;
  border: 0;
  outline: none;
  background: transparent;
  font-size: 14px;
}

.login-err {
  margin: 0;
  color: #d9534f;
  font-size: 13px;
}

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
.login-btn:hover:not(:disabled) {
  background: var(--blue-deep);
}
.login-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.login-foot {
  color: rgba(255, 255, 255, 0.7);
  font-size: 12px;
}

.login-help {
  margin: 14px 0 0;
  text-align: center;
  font-size: 12px;
  color: var(--muted);
}
.login-switch {
  margin: 8px 0 0;
  text-align: center;
  font-size: 13px;
  color: var(--muted);
}
.login-help a, .login-switch a {
  color: var(--blue);
  text-decoration: none;
}
.login-help a:hover, .login-switch a:hover {
  text-decoration: underline;
}
</style>
