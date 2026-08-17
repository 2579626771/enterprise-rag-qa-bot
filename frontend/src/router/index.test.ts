import { describe, expect, it, vi } from 'vitest'

function writeAuth(user: Record<string, unknown> | null, token = 'token') {
  if (!user) {
    localStorage.removeItem('rag_auth_v1')
    return
  }
  localStorage.setItem('rag_auth_v1', JSON.stringify({ token, user }))
}

async function freshRouter() {
  vi.resetModules()
  const { default: router } = await import('./index')
  return router
}

async function routeTo(path: string) {
  const router = await freshRouter()
  router.push(path)
  await router.isReady()
  return router.currentRoute.value
}

describe('router guards', () => {
  it('redirects anonymous users to login for protected pages', async () => {
    writeAuth(null)

    const route = await routeTo('/chat')

    expect(route.name).toBe('login')
  })

  it('keeps public pages accessible before login', async () => {
    writeAuth(null)

    const route = await routeTo('/forgot-password')

    expect(route.name).toBe('forgot-password')
  })

  it('redirects logged-in users away from public auth pages', async () => {
    writeAuth({ id: 1, username: 'alice', role: 'user', display_name: 'Alice' })

    const route = await routeTo('/login')

    expect(route.name).toBe('chat')
  })

  it('blocks non-admin users from admin routes', async () => {
    writeAuth({ id: 1, username: 'alice', role: 'user', display_name: 'Alice' })

    const route = await routeTo('/account')

    expect(route.name).toBe('chat')
  })

  it('allows admin users to enter admin routes', async () => {
    writeAuth({ id: 2, username: 'admin', role: 'admin', display_name: 'Admin' })

    const route = await routeTo('/account')

    expect(route.name).toBe('account')
  })

  it('forces temporary-password users to profile first', async () => {
    writeAuth({
      id: 3,
      username: 'temp',
      role: 'user',
      display_name: 'Temp',
      force_password_change: true,
    })

    const route = await routeTo('/chat')

    expect(route.name).toBe('profile')
  })
})
