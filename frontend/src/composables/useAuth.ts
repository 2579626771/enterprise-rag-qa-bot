import { ref, computed } from 'vue'
import { login as apiLogin, register as apiRegister, type AuthUser } from '../api/client'

// 登录态持久化：token + user 存 localStorage（key 与 client.ts 的 TOKEN_KEY 一致）。
// 刷新页面后仍保持登录，直到 token 过期或主动退出。
const STORAGE_KEY = 'rag_auth_v1'

interface AuthState {
  token: string
  user: AuthUser | null
}

function load(): AuthState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) {
      const parsed = JSON.parse(raw) as AuthState
      return { token: parsed.token || '', user: parsed.user ?? null }
    }
  } catch {
    // ignore
  }
  return { token: '', user: null }
}

const initial = load()
// 模块级单例：全应用共享同一份登录态
const token = ref<string>(initial.token)
const user = ref<AuthUser | null>(initial.user)

function persist() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ token: token.value, user: user.value }))
  } catch {
    // ignore
  }
}

function clear() {
  token.value = ''
  user.value = null
  try {
    localStorage.removeItem(STORAGE_KEY)
  } catch {
    // ignore
  }
}

// client.ts 的响应拦截器在 401 时派发此事件：清登录态并跳回登录页。
window.addEventListener('auth:unauthorized', () => {
  clear()
  // 动态引入 router，避免与 router 的 useAuth 形成循环依赖。
  import('../router').then(({ default: router }) => {
    if (router.currentRoute.value.name !== 'login') {
      router.push({ name: 'login' })
    }
  }).catch(() => {})
})

export function useAuth() {
  const isLoggedIn = computed(() => !!token.value && !!user.value)
  const isAdmin = computed(() => user.value?.role === 'admin')

  async function login(username: string, password: string): Promise<void> {
    const res = await apiLogin(username, password)
    token.value = res.access_token
    user.value = res.user
    persist()
  }

  async function register(username: string, password: string, displayName = ''): Promise<void> {
    const res = await apiRegister(username, password, displayName)
    // 注册成功即自动登录：写入令牌与用户信息
    token.value = res.access_token
    user.value = res.user
    persist()
  }

  function logout(): void {
    clear()
  }

  return { token, user, isLoggedIn, isAdmin, login, register, logout }
}
