<template>
  <div class="app-shell">
    <!-- 左侧导航 -->
    <aside class="sidebar" aria-label="主导航">
      <div class="brand">
        <i class="fa-solid fa-database"></i>
        <div>
          <strong>Enterprise RAG</strong>
          <span>企业知识库系统</span>
        </div>
      </div>

      <nav class="main-nav">
        <router-link
          v-for="item in visibleNavItems"
          :key="item.name"
          :to="{ name: item.name }"
          class="nav-item"
          active-class="active"
        >
          <i :class="item.icon"></i>
          <span>{{ item.label }}</span>
        </router-link>
      </nav>

      <div class="admin-card">
        <div class="avatar"><i class="fa-solid fa-user-tie"></i></div>
        <span>{{ user?.display_name || user?.username }}</span>
        <b>{{ isAdmin ? '管理员' : '用户' }}</b>
      </div>
    </aside>

    <!-- 右侧工作区 -->
    <section class="workspace">
      <header class="topbar">
        <span>知识工作台 / <strong>{{ currentLabel }}</strong></span>
        <div class="top-actions">
          <span class="service"><i></i>企业知识服务</span>
          <div class="user-menu">
            <button type="button" @click="userMenuOpen = !userMenuOpen">
              {{ user?.display_name || user?.username }} <i class="fa-solid fa-chevron-down"></i>
            </button>
            <div v-if="userMenuOpen" class="dropdown">
              <button type="button">个人中心</button>
              <button type="button" @click="onLogout">退出登录</button>
            </div>
          </div>
        </div>
      </header>

      <!-- 页面出口：由路由决定渲染哪个页面 -->
      <router-view />
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuth } from '../composables/useAuth'

const route = useRoute()
const router = useRouter()
const { isAdmin, user, logout } = useAuth()

const userMenuOpen = ref(false)

// 侧栏导航项：name 对应路由名，与 router/index.ts 保持一致。
const navItems: Array<{ name: string; label: string; icon: string; adminOnly?: boolean }> = [
  { name: 'chat', label: '智能问答', icon: 'fa-solid fa-comments' },
  { name: 'archive', label: '资料档案库', icon: 'fa-solid fa-folder-open' },
  { name: 'kb', label: '我的知识库', icon: 'fa-solid fa-book' },
  { name: 'overview', label: '运行概览', icon: 'fa-solid fa-chart-pie' },
  { name: 'config', label: '检索配置', icon: 'fa-solid fa-sliders' },
  { name: 'adminkb', label: '知识库管理', icon: 'fa-solid fa-database', adminOnly: true },
  { name: 'account', label: '账户管理', icon: 'fa-solid fa-users-gear', adminOnly: true },
  { name: 'review', label: '申请审批', icon: 'fa-solid fa-clipboard-check', adminOnly: true },
]

// 普通用户看不到管理员专属项
const visibleNavItems = computed(() => navItems.filter((i) => !i.adminOnly || isAdmin.value))

// 顶栏标题：读当前路由 meta.label
const currentLabel = computed(() => (route.meta.label as string) ?? '')

function onLogout() {
  userMenuOpen.value = false
  logout()
  router.push({ name: 'login' })
}
</script>
