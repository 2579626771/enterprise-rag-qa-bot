import { createRouter, createWebHashHistory, type RouteRecordRaw } from 'vue-router'
import { useAuth } from '../composables/useAuth'

import AppLayout from '../layouts/AppLayout.vue'
import LoginView from '../views/LoginView.vue'
import RegisterView from '../views/RegisterView.vue'
import ChatView from '../views/ChatView.vue'
import ArchiveView from '../views/ArchiveView.vue'
import KbView from '../views/KbView.vue'
import OverviewView from '../views/OverviewView.vue'
import AdminKbView from '../views/AdminKbView.vue'
import AccountView from '../views/AccountView.vue'
import ReviewView from '../views/ReviewView.vue'
import ConfigPlaceholder from '../views/ConfigPlaceholder.vue'

// meta.label 供顶栏标题使用；meta.adminOnly 供守卫与侧栏过滤使用。
const routes: RouteRecordRaw[] = [
  { path: '/login', name: 'login', component: LoginView, meta: { public: true } },
  { path: '/register', name: 'register', component: RegisterView, meta: { public: true } },
  {
    path: '/',
    component: AppLayout,
    children: [
      { path: '', redirect: '/chat' },
      { path: 'chat', name: 'chat', component: ChatView, meta: { label: '智能问答' } },
      { path: 'archive', name: 'archive', component: ArchiveView, meta: { label: '资料档案库' } },
      { path: 'kb', name: 'kb', component: KbView, meta: { label: '我的知识库' } },
      { path: 'overview', name: 'overview', component: OverviewView, meta: { label: '运行概览' } },
      { path: 'config', name: 'config', component: ConfigPlaceholder, meta: { label: '检索配置' } },
      { path: 'adminkb', name: 'adminkb', component: AdminKbView, meta: { label: '知识库管理', adminOnly: true } },
      { path: 'account', name: 'account', component: AccountView, meta: { label: '账户管理', adminOnly: true } },
      { path: 'review', name: 'review', component: ReviewView, meta: { label: '申请审批', adminOnly: true } },
    ],
  },
  // 兜底：未知路径回到问答页
  { path: '/:pathMatch(.*)*', redirect: '/chat' },
]

const router = createRouter({
  // hash 模式：纯静态 SPA 下任意路径刷新都不会 404，无需服务端 rewrite。
  history: createWebHashHistory(),
  routes,
})

// 全局前置守卫：登录态与管理员权限。
router.beforeEach((to) => {
  const { isLoggedIn, isAdmin } = useAuth()

  // 未登录：只放行公开页（登录页），其余一律去登录页。
  if (!isLoggedIn.value) {
    return to.meta.public ? true : { name: 'login' }
  }

  // 已登录却访问登录/注册页：回到首页。
  if (to.name === 'login' || to.name === 'register') {
    return { name: 'chat' }
  }

  // 管理员专属页：非管理员回到问答页。
  if (to.meta.adminOnly && !isAdmin.value) {
    return { name: 'chat' }
  }

  return true
})

export default router
