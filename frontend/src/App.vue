<template>
  <router-view />
</template>

<script setup lang="ts">
import { watch } from 'vue'
import { useAuth } from './composables/useAuth'
import { useKnowledgeBase } from './composables/useKnowledgeBase'

// App 是常驻根组件：在这里管理「登录态 → 加载/清空知识库」的全局副作用，
// 页面切换（router-view 内组件换来换去）不会影响它。
const { isLoggedIn } = useAuth()
const { refreshKbs, resetKbs } = useKnowledgeBase()

watch(
  isLoggedIn,
  (loggedIn) => {
    if (loggedIn) {
      refreshKbs().catch(() => {})
    } else {
      resetKbs()
    }
  },
  { immediate: true },
)
</script>
