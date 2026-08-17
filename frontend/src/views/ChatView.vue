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
            <span>{{ s.lastTime }} · {{ s.messageCount }}条</span>
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
          <!-- 研判徽标（仅助手消息）：拒答 → 资料不足；低可信 → 谨慎参考 -->
          <div
            v-if="msg.role === 'assistant' && msg.verdict && msg.verdict.answerable === false"
            class="verdict-badge refuse"
          >
            <i class="fa-solid fa-triangle-exclamation"></i>
            <span>资料不足，未作答<template v-if="msg.verdict.reason"> · {{ msg.verdict.reason }}</template></span>
          </div>
          <div
            v-else-if="msg.role === 'assistant' && msg.verdict && msg.verdict.confidence === 'low'"
            class="verdict-badge low"
          >
            <i class="fa-solid fa-circle-info"></i>
            <span>资料有限，回答仅供参考</span>
          </div>
          <p>{{ msg.content }}</p>
          <div v-if="msg.sources?.length" class="sources">
            <details v-for="(s, i) in msg.sources" :key="i" class="source-chip">
              <summary>📄 {{ s.filename }} · 第 {{ s.chunk_index }} 段</summary>
              <div class="src-body">{{ s.content }}</div>
            </details>
          </div>
        </div>
        <div v-if="asking" class="bubble assistant loading"><span></span><span></span><span></span></div>
        <div v-if="typingAssistant" class="bubble assistant typing-bubble">
          <div
            v-if="typingAssistant.verdict && typingAssistant.verdict.answerable === false"
            class="verdict-badge refuse"
          >
            <i class="fa-solid fa-triangle-exclamation"></i>
            <span>资料不足，未作答<template v-if="typingAssistant.verdict.reason"> · {{ typingAssistant.verdict.reason }}</template></span>
          </div>
          <div
            v-else-if="typingAssistant.verdict && typingAssistant.verdict.confidence === 'low'"
            class="verdict-badge low"
          >
            <i class="fa-solid fa-circle-info"></i>
            <span>资料有限，回答仅供参考</span>
          </div>
          <p>{{ typingAssistant.content }}<span v-if="typing" class="typing-cursor"></span></p>
          <div v-if="!typing && typingAssistant.sources?.length" class="sources">
            <details v-for="(s, i) in typingAssistant.sources" :key="i" class="source-chip">
              <summary>📄 {{ s.filename }} · 第 {{ s.chunk_index }} 段</summary>
              <div class="src-body">{{ s.content }}</div>
            </details>
          </div>
        </div>
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
      <!-- 知识库范围选择器：默认「全部」，可选具体某个库 -->
      <details class="kb-picker" ref="kbPicker">
        <summary :title="scopeLabel">
          <i class="fa-solid fa-database"></i>
          <span class="kb-picker-label">{{ scopeLabel }}</span>
          <i class="fa-solid fa-chevron-down kb-picker-caret"></i>
        </summary>
        <div class="kb-picker-menu">
          <button
            type="button"
            :class="{ active: currentKbId === ALL_KB_ID }"
            @click="pickKb(ALL_KB_ID)"
          >
            <i class="fa-solid fa-layer-group"></i> 全部知识库
          </button>
          <div class="kb-picker-divider"></div>
          <button
            v-for="kb in kbList"
            :key="kb.id"
            type="button"
            :class="{ active: currentKbId === kb.id }"
            @click="pickKb(kb.id)"
          >
            <i class="fa-solid fa-book"></i> {{ kb.name }}
          </button>
          <div v-if="kbList.length === 0" class="kb-picker-empty">还没有知识库</div>
        </div>
      </details>

      <input
        v-model="draft"
        type="text"
        :placeholder="`向「${scopeLabel}」提问…`"
        @keydown.enter="send"
      />
      <button class="plain-icon" type="button" aria-label="附件"><i class="fa-solid fa-paperclip"></i></button>
      <button class="send" type="button" aria-label="发送" :disabled="asking || typing" @click="send">
        <i class="fa-solid fa-paper-plane"></i>
      </button>
    </div>
    <p>回答由大模型基于知识库检索生成，请结合原文来源核实</p>
  </footer>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { askQuestion, extractErrorMessage, type Source, type Verdict } from '../api/client'
import { useSessions } from '../composables/useSessions'
import { useKnowledgeBase } from '../composables/useKnowledgeBase'

const {
  sessions,
  currentSessionId,
  currentMessages,
  init,
  newConversation,
  selectSession,
  toggleFavorite,
  deleteSession,
  renameSession,
  appendMessage,
  ensureCurrent,
} = useSessions()

onMounted(() => {
  void init()
})

const quickQuestions = [
  '这个知识库里都有哪些内容？',
  '怎么读取文档内容？',
  '总结一下核心要点',
]

const { ALL_KB_ID, kbList, currentKbId, currentKb, selectKb } = useKnowledgeBase()

const filter = ref<'all' | 'favorite'>('all')
const draft = ref('')
const asking = ref(false)
const typing = ref(false)
const typingAssistant = ref<{ content: string; sources: Source[]; verdict: Verdict | null } | null>(null)
const kbPicker = ref<HTMLDetailsElement | null>(null)

// 当前检索范围的显示名：全部 → 「全部知识库」；否则为库名。
const scopeLabel = computed(() => (currentKbId.value === ALL_KB_ID ? '全部知识库' : currentKb.value?.name ?? '全部知识库'))

function pickKb(id: number) {
  selectKb(id)
  // 选完收起下拉
  if (kbPicker.value) kbPicker.value.open = false
}

const favoriteCount = computed(() => sessions.value.filter((s) => s.isFavorite).length)
const visibleSessions = computed(() =>
  filter.value === 'favorite' ? sessions.value.filter((s) => s.isFavorite) : sessions.value,
)

async function onNew() {
  await newConversation()
  draft.value = ''
}

async function onRename(sessionId: number) {
  const s = sessions.value.find((x) => x.sessionId === sessionId)
  const next = window.prompt('重命名会话', s?.sessionTitle ?? '')
  if (next) await renameSession(sessionId, next)
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

async function typeAnswer(fullText: string, sources: Source[], verdict: Verdict | null) {
  typingAssistant.value = { content: '', sources, verdict }
  typing.value = true
  let index = 0
  while (index < fullText.length) {
    const remaining = fullText.length - index
    const step = fullText.length > 600 ? 8 : fullText.length > 240 ? 5 : 3
    index += Math.min(step, remaining)
    typingAssistant.value.content = fullText.slice(0, index)
    await sleep(fullText.length > 600 ? 10 : 18)
  }
  typing.value = false
}

async function persistTypedAssistant(
  sid: number,
  content: string,
  sources: Source[] = [],
  verdict: Verdict | null = null,
) {
  await appendMessage(sid, { role: 'assistant', content, sources, verdict })
  typingAssistant.value = null
}

async function send() {
  const question = draft.value.trim()
  if (!question || asking.value || typing.value) return

  const sid = await ensureCurrent()
  await appendMessage(sid, { role: 'user', content: question })
  draft.value = ''
  asking.value = true
  try {
    // currentKbId 为 0（全部）时传 null，后端按角色限定范围（普通用户=自己所有库）。
    const res = await askQuestion(question, currentKbId.value || null)
    // 研判结果（防幻觉）：随消息存库，刷新会话后仍能显示徽标。
    const verdict =
      res.answerable === undefined
        ? null
        : { answerable: res.answerable, reason: res.reason ?? '', confidence: res.confidence ?? 'high' }
    asking.value = false
    await typeAnswer(res.answer, res.sources, verdict)
    await persistTypedAssistant(sid, res.answer, res.sources, verdict)
  } catch (e) {
    const errorText = `出错了：${extractErrorMessage(e)}`
    asking.value = false
    await typeAnswer(errorText, [], null)
    await persistTypedAssistant(sid, errorText)
  } finally {
    asking.value = false
    typing.value = false
  }
}
</script>
