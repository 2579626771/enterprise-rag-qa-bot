<template>
  <main class="content">
    <!-- 左侧：问答会话 -->
    <section class="sessions" aria-label="问答会话">
      <div class="section-head sess-head">
        <div>
          <h2>问答会话</h2>
          <small>{{ sessions.length }} 个历史会话 · {{ favoriteCount }} 个收藏</small>
        </div>
        <button class="primary" type="button" @click="onNew">
          <i class="fa-solid fa-plus"></i> 新对话
        </button>
      </div>

      <div class="tabs">
        <button :class="{ active: filter === 'all' }" type="button" @click="filter = 'all'">
          全部 {{ sessions.length }}
        </button>
        <button :class="{ active: filter === 'favorite' }" type="button" @click="filter = 'favorite'">
          已收藏 {{ favoriteCount }}
        </button>
      </div>

      <div class="session-list">
        <div v-if="visibleSessions.length === 0" class="list-empty">
          {{ filter === 'favorite' ? '暂无收藏会话' : '暂无会话，点击"新对话"开始' }}
        </div>
        <article
          v-for="s in visibleSessions"
          :key="s.sessionId"
          :class="['session-item', { selected: currentSessionId === s.sessionId }]"
          @click="selectSession(s.sessionId)"
        >
          <i class="fa-regular fa-comment-dots session-icon"></i>
          <div class="session-copy">
            <strong :title="s.sessionTitle">{{ s.sessionTitle }}</strong>
            <span>{{ s.lastTime }} · {{ s.messages.length }}条</span>
          </div>
          <button
            class="icon-button"
            type="button"
            aria-label="收藏"
            @click.stop="toggleFavorite(s.sessionId)"
          >
            <i :class="s.isFavorite ? 'fa-solid fa-star favorite' : 'fa-regular fa-star'"></i>
          </button>
          <details class="more" @click.stop>
            <summary aria-label="更多"><i class="fa-solid fa-ellipsis-vertical"></i></summary>
            <div>
              <button type="button" @click="onRename(s.sessionId)">重命名</button>
              <button type="button" @click="deleteSession(s.sessionId)">删除</button>
            </div>
          </details>
        </article>
      </div>
    </section>

    <!-- 右侧：对话 + 引导 -->
    <section class="answer-area" aria-label="对话">
      <div v-if="currentMessages.length" class="chat-panel">
        <div v-for="msg in currentMessages" :key="msg.id" :class="['bubble', msg.role]">
          <p>{{ msg.content }}</p>
          <div v-if="msg.sources?.length" class="sources">
            <details v-for="(s, i) in msg.sources" :key="i" class="source-chip">
              <summary>📄 {{ s.filename }} · 第 {{ s.chunk_index }} 段</summary>
              <div class="src-body">{{ s.content }}</div>
            </details>
          </div>
        </div>
        <div v-if="asking" class="bubble assistant loading"><span></span><span></span><span></span></div>
      </div>

      <div v-else class="hero-card">
        <h1>基于企业知识库 · 开始一次可追溯的智能问答</h1>
        <p>检索增强生成，回答均标注来源片段，溯源可信</p>
        <div class="feature-tags">
          <span>原文片段引用</span>
          <span>全库语义检索</span>
          <span>来源可追溯</span>
        </div>
      </div>

      <section class="questions card">
        <div class="section-head">
          <h2>常用问题</h2>
          <small>选择一个示例快速开始</small>
        </div>
        <div class="question-grid">
          <button v-for="q in quickQuestions" :key="q" type="button" @click="draft = q">
            <span>{{ q }}</span>
            <i class="fa-solid fa-arrow-right"></i>
          </button>
        </div>
      </section>
    </section>
  </main>

  <!-- 底部输入 -->
  <footer class="composer">
    <div class="input-wrap">
      <input
        v-model="draft"
        type="text"
        :placeholder="currentKb ? `向「${currentKb.name}」提问…` : '输入问题，向知识库提问…'"
        @keydown.enter="send"
      />
      <button class="plain-icon" type="button" aria-label="附件"><i class="fa-solid fa-paperclip"></i></button>
      <button class="send" type="button" aria-label="发送" :disabled="asking" @click="send">
        <i class="fa-solid fa-paper-plane"></i>
      </button>
    </div>
    <p>回答由大模型基于知识库检索生成，请结合原文来源核实</p>
  </footer>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { askQuestion, extractErrorMessage } from '../api/client'
import { useSessions } from '../composables/useSessions'
import { useKnowledgeBase } from '../composables/useKnowledgeBase'

const {
  sessions,
  currentSessionId,
  currentMessages,
  newConversation,
  selectSession,
  toggleFavorite,
  deleteSession,
  renameSession,
  appendMessage,
  ensureCurrent,
} = useSessions()

const quickQuestions = [
  '这个知识库里都有哪些内容？',
  '怎么读取文档内容？',
  '总结一下核心要点',
]

const { currentKbId, currentKb } = useKnowledgeBase()

const filter = ref<'all' | 'favorite'>('all')
const draft = ref('')
const asking = ref(false)

const favoriteCount = computed(() => sessions.value.filter((s) => s.isFavorite).length)
const visibleSessions = computed(() =>
  filter.value === 'favorite' ? sessions.value.filter((s) => s.isFavorite) : sessions.value,
)

function onNew() {
  newConversation()
  draft.value = ''
}

function onRename(sessionId: string) {
  const s = sessions.value.find((x) => x.sessionId === sessionId)
  const next = window.prompt('重命名会话', s?.sessionTitle ?? '')
  if (next) renameSession(sessionId, next)
}

async function send() {
  const question = draft.value.trim()
  if (!question || asking.value) return
  if (!currentKbId.value) {
    appendMessage(ensureCurrent(), { role: 'assistant', content: '请先在「资料档案库」选择或创建一个知识库。' })
    return
  }

  const sid = ensureCurrent()
  appendMessage(sid, { role: 'user', content: question })
  draft.value = ''
  asking.value = true
  try {
    const res = await askQuestion(question, currentKbId.value)
    appendMessage(sid, { role: 'assistant', content: res.answer, sources: res.sources })
  } catch (e) {
    appendMessage(sid, { role: 'assistant', content: `出错了：${extractErrorMessage(e)}` })
  } finally {
    asking.value = false
  }
}
</script>
