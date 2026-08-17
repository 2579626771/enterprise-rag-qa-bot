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
          <div class="notice-menu">
            <button type="button" class="notice-trigger" @click="toggleNoticePanel">
              <i class="fa-solid fa-bell"></i>通知
              <b v-if="unreadCount" class="notice-badge">{{ badgeText }}</b>
            </button>
            <div v-if="noticePanelOpen" class="notice-dropdown">
              <div class="notice-drop-head">
                <strong>消息中心</strong>
                <button type="button" :disabled="noticeLoading" @click="loadNotifications">
                  <i class="fa-solid fa-rotate" :class="{ spin: noticeLoading }"></i>
                </button>
              </div>
              <div v-if="noticeLoading" class="notice-empty">加载中…</div>
              <div v-else-if="notifications.length === 0" class="notice-empty">暂无通知</div>
              <div v-else class="notice-list">
                <article v-for="n in notifications" :key="n.id" :class="['notice-item', n.status]">
                  <div class="notice-title">
                    <strong>{{ n.title }}</strong>
                    <span>{{ notificationStatusLabel(n.status) }}</span>
                  </div>
                  <p>{{ n.content || '—' }}</p>
                  <small>{{ n.created_at || '—' }}</small>
                  <div class="notice-actions">
                    <button v-if="n.status === 'unread'" type="button" @click="markRead(n.id)">确认已读</button>
                    <button type="button" @click="closeNotice(n.id)">关闭</button>
                  </div>
                </article>
              </div>
            </div>
          </div>
          <router-link :to="{ name: 'guide' }" class="service service-link">
            <i class="fa-solid fa-circle-question"></i>使用指南
          </router-link>
          <div class="user-menu">
            <button type="button" @click="userMenuOpen = !userMenuOpen">
              {{ user?.display_name || user?.username }} <i class="fa-solid fa-chevron-down"></i>
            </button>
            <div v-if="userMenuOpen" class="dropdown">
              <button type="button" @click="goProfile">个人中心</button>
              <button type="button" @click="onLogout">退出登录</button>
            </div>
          </div>
        </div>
      </header>

      <!-- 页面出口：由路由决定渲染哪个页面 -->
      <router-view />
    </section>

    <div v-if="popupNotice" class="modal-mask" @click.self="dismissPopup">
      <div class="modal notice-modal">
        <div class="modal-head">
          <h3><i class="fa-solid fa-bell"></i> {{ popupNotice.title }}</h3>
          <button class="modal-close" type="button" @click="dismissPopup"><i class="fa-solid fa-xmark"></i></button>
        </div>
        <div class="detail-body">
          <p class="notice-popup-content">{{ popupNotice.content || '—' }}</p>
          <p class="muted-cell">发布时间：{{ popupNotice.created_at || '—' }}</p>
        </div>
        <div class="modal-foot">
          <button class="btn-ghost" type="button" @click="closeNotice(popupNotice.id)">关闭通知</button>
          <button class="primary" type="button" @click="markRead(popupNotice.id)">确认已读</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  closeNotification,
  getUnreadNotificationCount,
  listMyNotifications,
  markNotificationRead,
  type NotificationStatus,
  type UserNotification,
} from '../api/client'
import { useAuth } from '../composables/useAuth'

const route = useRoute()
const router = useRouter()
const { isAdmin, isLoggedIn, user, logout } = useAuth()

const userMenuOpen = ref(false)
const noticePanelOpen = ref(false)
const noticeLoading = ref(false)
const notifications = ref<UserNotification[]>([])
const unreadCount = ref(0)
const popupDismissedId = ref<number | null>(null)

// 侧栏导航项：name 对应路由名，与 router/index.ts 保持一致。
const navItems: Array<{ name: string; label: string; icon: string; adminOnly?: boolean }> = [
  { name: 'chat', label: '智能问答', icon: 'fa-solid fa-comments' },
  { name: 'kb', label: '我的知识库', icon: 'fa-solid fa-book' },
  { name: 'overview', label: '运行概览', icon: 'fa-solid fa-chart-pie' },
  { name: 'feedback', label: '问题反馈', icon: 'fa-solid fa-message' },
  { name: 'config', label: '检索配置', icon: 'fa-solid fa-sliders' },
  { name: 'adminkb', label: '知识库管理', icon: 'fa-solid fa-database', adminOnly: true },
  { name: 'account', label: '账户管理', icon: 'fa-solid fa-users-gear', adminOnly: true },
  { name: 'review', label: '申请审批', icon: 'fa-solid fa-clipboard-check', adminOnly: true },
  { name: 'feedback-admin', label: '反馈处理', icon: 'fa-solid fa-headset', adminOnly: true },
  { name: 'notifications-admin', label: '通知下发', icon: 'fa-solid fa-bullhorn', adminOnly: true },
  { name: 'model-usage', label: '模型监控', icon: 'fa-solid fa-gauge-high', adminOnly: true },
]

// 普通用户看不到管理员专属项
const visibleNavItems = computed(() => navItems.filter((i) => !i.adminOnly || isAdmin.value))

// 顶栏标题：读当前路由 meta.label
const currentLabel = computed(() => (route.meta.label as string) ?? '')
const badgeText = computed(() => (unreadCount.value > 99 ? '99+' : String(unreadCount.value)))
const popupNotice = computed(() => notifications.value.find((n) => n.status === 'unread' && n.id !== popupDismissedId.value) ?? null)

function notificationStatusLabel(status: NotificationStatus): string {
  return status === 'unread' ? '未读' : status === 'read' ? '已读' : '已关闭'
}

async function loadNotifications() {
  if (!isLoggedIn.value) return
  noticeLoading.value = true
  try {
    notifications.value = await listMyNotifications(false)
    unreadCount.value = await getUnreadNotificationCount()
  } catch {
    // 通知失败不影响主工作台
  } finally {
    noticeLoading.value = false
  }
}

async function toggleNoticePanel() {
  noticePanelOpen.value = !noticePanelOpen.value
  if (noticePanelOpen.value) await loadNotifications()
}

async function markRead(id: number) {
  try {
    await markNotificationRead(id)
    popupDismissedId.value = id
    await loadNotifications()
  } catch {
    // ignore
  }
}

async function closeNotice(id: number) {
  try {
    await closeNotification(id)
    popupDismissedId.value = id
    await loadNotifications()
  } catch {
    // ignore
  }
}

function dismissPopup() {
  if (popupNotice.value) popupDismissedId.value = popupNotice.value.id
}

function goProfile() {
  userMenuOpen.value = false
  router.push({ name: 'profile' })
}

function onLogout() {
  userMenuOpen.value = false
  noticePanelOpen.value = false
  notifications.value = []
  unreadCount.value = 0
  logout()
  router.push({ name: 'login' })
}

onMounted(loadNotifications)
watch(isLoggedIn, (loggedIn) => {
  if (loggedIn) void loadNotifications()
  else {
    notifications.value = []
    unreadCount.value = 0
  }
})
</script>

<style scoped>
/* 顶栏「使用指南」入口：由原「企业知识服务」装饰文字改造为可点击链接。
   覆盖全局 .service i 的绿点样式，让书本/问号图标正常显示。 */
.service-link {
  text-decoration: none;
  color: var(--blue);
  cursor: pointer;
  padding: 5px 12px;
  border-radius: 16px;
  background: var(--blue-3);
  font-size: 13px;
  transition: background 0.15s, color 0.15s;
}
.service-link i {
  width: auto;
  height: auto;
  border-radius: 0;
  background: none;
  box-shadow: none;
  font-size: 13px;
  color: var(--blue);
}
.service-link:hover {
  background: var(--blue);
  color: #fff;
}
.service-link:hover i {
  color: #fff;
}
.notice-menu { position: relative; }
.notice-trigger {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  border-radius: 16px;
  background: #fff7ed;
  color: #b4761d;
  font-size: 13px;
}
.notice-trigger i { color: #b4761d; }
.notice-badge {
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  display: inline-grid;
  place-items: center;
  border-radius: 999px;
  background: #dc2626;
  color: #fff;
  font-size: 11px;
}
.notice-dropdown {
  position: absolute;
  z-index: 20;
  top: 32px;
  right: 0;
  width: 360px;
  max-height: 520px;
  display: flex;
  flex-direction: column;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: #fff;
  box-shadow: 0 18px 48px rgb(0 0 0 / 16%);
  overflow: hidden;
}
.notice-drop-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 14px;
  border-bottom: 1px solid var(--line);
}
.notice-drop-head button { color: var(--blue); }
.notice-empty { padding: 24px; text-align: center; color: var(--muted); font-size: 13px; }
.notice-list { overflow-y: auto; padding: 8px; }
.notice-item { padding: 10px; border: 1px solid var(--line); border-radius: 10px; margin-bottom: 8px; }
.notice-item.unread { border-color: #f6d7a8; background: #fffaf3; }
.notice-title { display: flex; justify-content: space-between; gap: 8px; }
.notice-title strong { font-size: 14px; }
.notice-title span { color: var(--muted); font-size: 12px; }
.notice-item p { margin: 8px 0; white-space: pre-wrap; line-height: 1.6; color: #3a4147; }
.notice-item small { color: var(--muted); }
.notice-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 8px; }
.notice-actions button { color: var(--blue); font-size: 12px; }
.notice-actions button:hover { text-decoration: underline; }
.notice-modal { width: 520px; max-width: calc(100vw - 32px); }
.notice-modal h3 i { color: #b4761d; }
.notice-popup-content { margin: 0 0 14px; white-space: pre-wrap; line-height: 1.8; color: #3a4147; }
</style>
