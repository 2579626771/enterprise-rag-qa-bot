import { describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'

const loginMock = vi.hoisted(() => vi.fn())
const registerMock = vi.hoisted(() => vi.fn())
const routerPushMock = vi.hoisted(() => vi.fn())
const currentRouteMock = vi.hoisted(() => ({ value: { name: 'chat' } }))

vi.mock('../api/client', () => ({
  login: loginMock,
  register: registerMock,
}))

vi.mock('../router', () => ({
  default: {
    currentRoute: currentRouteMock,
    push: routerPushMock,
  },
}))

const STORAGE_KEY = 'rag_auth_v1'

async function freshAuth() {
  vi.resetModules()
  const mod = await import('./useAuth')
  return mod.useAuth()
}

describe('useAuth', () => {
  it('login writes token and user to reactive state and localStorage', async () => {
    loginMock.mockResolvedValueOnce({
      access_token: 'token-1',
      token_type: 'bearer',
      user: { id: 1, username: 'alice', role: 'user', display_name: 'Alice' },
    })
    const auth = await freshAuth()

    await auth.login('alice', 'pass1234')

    expect(loginMock).toHaveBeenCalledWith('alice', 'pass1234')
    expect(auth.token.value).toBe('token-1')
    expect(auth.user.value?.username).toBe('alice')
    expect(auth.isLoggedIn.value).toBe(true)
    expect(JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}')).toMatchObject({
      token: 'token-1',
      user: { username: 'alice' },
    })
  })

  it('register persists the returned login state', async () => {
    const recoveryItems = [
      { question: 'q1', answer: 'a1' },
      { question: 'q2', answer: 'a2' },
      { question: 'q3', answer: 'a3' },
    ]
    registerMock.mockResolvedValueOnce({
      access_token: 'token-2',
      token_type: 'bearer',
      user: { id: 2, username: 'bob', role: 'user', display_name: 'Bob' },
    })
    const auth = await freshAuth()

    await auth.register('bob', 'pass1234', 'Bob', recoveryItems)

    expect(registerMock).toHaveBeenCalledWith('bob', 'pass1234', 'Bob', recoveryItems)
    expect(auth.token.value).toBe('token-2')
    expect(auth.user.value?.display_name).toBe('Bob')
  })

  it('loads persisted state and logout clears it', async () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      token: 'persisted-token',
      user: { id: 3, username: 'admin', role: 'admin', display_name: 'Admin' },
    }))
    const auth = await freshAuth()

    expect(auth.isLoggedIn.value).toBe(true)
    expect(auth.isAdmin.value).toBe(true)

    auth.logout()

    expect(auth.isLoggedIn.value).toBe(false)
    expect(auth.user.value).toBeNull()
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull()
  })

  it('auth:unauthorized clears state and redirects to login', async () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      token: 'expired-token',
      user: { id: 4, username: 'carol', role: 'user', display_name: 'Carol' },
    }))
    currentRouteMock.value = { name: 'chat' }
    const auth = await freshAuth()

    window.dispatchEvent(new CustomEvent('auth:unauthorized'))
    await nextTick()
    await vi.dynamicImportSettled()

    expect(auth.isLoggedIn.value).toBe(false)
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull()
    expect(routerPushMock).toHaveBeenCalledWith({ name: 'login' })
  })
})
