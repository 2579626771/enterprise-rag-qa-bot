<template>
  <main class="guide-page">
    <div class="guide-head">
      <div>
        <h1>使用指南 <span class="pill">新手必读</span></h1>
        <p>从注册到问答，几分钟带你上手企业知识库平台</p>
      </div>
    </div>

    <div class="guide-body">
      <!-- 左侧目录 -->
      <aside class="guide-toc">
        <div class="toc-title">目录</div>
        <a
          v-for="s in visibleSections"
          :key="s.id"
          :class="['toc-item', { active: activeId === s.id }]"
          href="javascript:void(0)"
          @click="scrollTo(s.id)"
        >
          <i :class="s.icon"></i><span>{{ s.title }}</span>
        </a>
      </aside>

      <!-- 右侧正文 -->
      <article ref="contentEl" class="guide-content" @scroll="onScroll">
        <section :id="ids.intro" class="doc-sec">
          <h2><i class="fa-solid fa-circle-info"></i> 平台是什么</h2>
          <p>
            这是一个「企业知识库 + 智能问答」平台：你把内部文档（技术手册、规章制度、常见问答等）
            上传到自己的知识库，系统会自动解析、切分、向量化；之后你用自然语言提问，
            平台会在<strong>你选定的知识库范围内</strong>检索最相关的片段，并据此生成答案、附上来源出处。
          </p>
          <div class="tip">
            <i class="fa-solid fa-lightbulb"></i>
            <span>核心理念：<strong>按知识库隔离</strong>。你的文档与问答只在你自己的知识库里，别人看不到、也问不到。</span>
          </div>
        </section>

        <section :id="ids.quickstart" class="doc-sec">
          <h2><i class="fa-solid fa-bolt"></i> 快速上手（四步）</h2>
          <ol class="steps">
            <li><strong>注册 / 登录</strong>：首次使用点登录页的「注册一个」，创建你的账号。</li>
            <li><strong>新建知识库</strong>：进入左侧「我的知识库」，点「新建知识库」，给它起个名字（如「产品手册」）。</li>
            <li><strong>上传文档</strong>：进入「资料档案库」，切到目标知识库，点「上传文档」，选择文件并填写主题分类。</li>
            <li><strong>开始问答</strong>：进入「智能问答」，选好知识库，直接用中文提问即可。</li>
          </ol>
        </section>

        <section :id="ids.account" class="doc-sec">
          <h2><i class="fa-solid fa-user"></i> 注册与登录</h2>
          <p>
            自助注册的用户默认为「普通用户」，注册成功会自动登录并获得一个默认知识库。
            用户名支持字母、数字及 <code>_ . - @</code>（3–32 位），密码至少 8 位。
          </p>
          <p>忘记退出？点右上角用户名 → 「退出登录」。令牌过期会自动跳回登录页，重新登录即可。</p>
        </section>

        <section :id="ids.kb" class="doc-sec">
          <h2><i class="fa-solid fa-book"></i> 管理你的知识库</h2>
          <p>在「我的知识库」页你可以：</p>
          <ul class="bullet">
            <li><strong>新建</strong>：不同用途的资料建议分库管理，问答更聚焦、更准。</li>
            <li><strong>编辑</strong>：点知识库卡片上的「铅笔」图标，可随时修改名称与描述。</li>
            <li><strong>删除</strong>：点「垃圾桶」图标，会连带清除其中所有文档与向量，<strong>不可恢复</strong>，请谨慎。</li>
          </ul>
          <div class="tip">
            <i class="fa-solid fa-lightbulb"></i>
            <span>页面标题旁的「已用 / 配额」表示你能创建的知识库数量上限。</span>
          </div>
        </section>

        <section :id="ids.upload" class="doc-sec">
          <h2><i class="fa-solid fa-file-arrow-up"></i> 上传文档</h2>
          <p>
            在「资料档案库」上传。目前支持 <strong>TXT / Markdown / PDF / Word(docx)</strong>。
            上传后文档会异步入库，状态从「处理中」变为「就绪」即可用于问答。
          </p>
          <ul class="bullet">
            <li>文档太大或格式复杂时，入库需要一点时间，可点「刷新」查看最新状态。</li>
            <li>若上传的文件无法解析（如空文件、加密 PDF），系统会提示失败并自动清理，不会留下坏数据。</li>
            <li>上传时填写「知识主题」便于后续按分类筛选查找。</li>
          </ul>
        </section>

        <section :id="ids.ask" class="doc-sec">
          <h2><i class="fa-solid fa-comments"></i> 智能问答与溯源</h2>
          <p>
            在「智能问答」页选好知识库后用自然语言提问。答案下方会列出<strong>来源片段</strong>，
            点开可查看原文出处，帮助你判断答案是否可信。
          </p>
          <div class="tip">
            <i class="fa-solid fa-triangle-exclamation"></i>
            <span>如果答「无法回答」，通常是知识库里没有相关内容，或该文档还没上传/入库。先确认文档已「就绪」。</span>
          </div>
        </section>

        <section :id="ids.quota" class="doc-sec">
          <h2><i class="fa-solid fa-paper-plane"></i> 申请更多配额</h2>
          <p>
            默认每个普通用户可创建的知识库数量有限。若不够用，在「我的知识库」点「申请更多配额」，
            填写数量与理由提交，等待管理员审批。审批通过后配额会自动增加。
          </p>
        </section>

        <section v-if="isAdmin" :id="ids.admin" class="doc-sec">
          <h2><i class="fa-solid fa-user-shield"></i> 管理员功能</h2>
          <p>管理员额外可见三个后台页面：</p>
          <ul class="bullet">
            <li><strong>知识库管理</strong>：按用户查看/搜索全部知识库，进入某用户可管理其知识库与文档，并<strong>调整该用户的配额</strong>。</li>
            <li><strong>账户管理</strong>：新建、查看、删除用户账号。</li>
            <li><strong>申请审批</strong>：处理用户提交的配额申请（通过 / 驳回）。</li>
          </ul>
        </section>

        <div class="guide-foot">遇到问题？联系你的系统管理员获取帮助。</div>
      </article>
    </div>
  </main>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { useAuth } from '../composables/useAuth'

const { isAdmin } = useAuth()

// 章节定义：id 用于锚点与滚动高亮，icon 用于目录图标。
const ids = {
  intro: 'g-intro',
  quickstart: 'g-quickstart',
  account: 'g-account',
  kb: 'g-kb',
  upload: 'g-upload',
  ask: 'g-ask',
  quota: 'g-quota',
  admin: 'g-admin',
} as const

// adminOnly 章节仅管理员可见（普通用户目录与正文都不出现）。
const sections = [
  { id: ids.intro, title: '平台是什么', icon: 'fa-solid fa-circle-info' },
  { id: ids.quickstart, title: '快速上手', icon: 'fa-solid fa-bolt' },
  { id: ids.account, title: '注册与登录', icon: 'fa-solid fa-user' },
  { id: ids.kb, title: '管理知识库', icon: 'fa-solid fa-book' },
  { id: ids.upload, title: '上传文档', icon: 'fa-solid fa-file-arrow-up' },
  { id: ids.ask, title: '智能问答', icon: 'fa-solid fa-comments' },
  { id: ids.quota, title: '申请配额', icon: 'fa-solid fa-paper-plane' },
  { id: ids.admin, title: '管理员功能', icon: 'fa-solid fa-user-shield', adminOnly: true },
]

const visibleSections = computed(() => sections.filter((s) => !s.adminOnly || isAdmin.value))

const contentEl = ref<HTMLElement | null>(null)
const activeId = ref<string>(sections[0].id)

function scrollTo(id: string) {
  const container = contentEl.value
  const el = document.getElementById(id)
  if (!container || !el) return
  container.scrollTo({ top: el.offsetTop - container.offsetTop - 8, behavior: 'smooth' })
  activeId.value = id
}

// 滚动时高亮当前可见章节。
function onScroll() {
  const container = contentEl.value
  if (!container) return
  const top = container.scrollTop + 20
  let current = visibleSections.value[0].id
  for (const s of visibleSections.value) {
    const el = document.getElementById(s.id)
    if (el && el.offsetTop - container.offsetTop <= top) current = s.id
  }
  activeId.value = current
}

onMounted(async () => {
  await nextTick()
  onScroll()
})
</script>

<style scoped>
.guide-page { padding: 26px 30px; height: 100%; display: flex; flex-direction: column; overflow: hidden; }
.guide-head { margin-bottom: 18px; flex: 0 0 auto; }
.guide-head h1 { margin: 0 0 4px; font-size: 22px; }
.guide-head p { margin: 0; color: var(--muted); font-size: 13px; }
.pill { font-size: 12px; padding: 2px 10px; border-radius: 10px; background: var(--blue-3); color: var(--blue); vertical-align: middle; }

.guide-body { display: flex; gap: 20px; flex: 1 1 auto; min-height: 0; }

/* 左侧目录 */
.guide-toc {
  flex: 0 0 200px;
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 14px 10px;
  align-self: flex-start;
  position: sticky;
  top: 0;
}
.toc-title { font-size: 12px; color: var(--muted); padding: 4px 10px 8px; }
.toc-item {
  display: flex; align-items: center; gap: 10px;
  padding: 9px 12px; margin-bottom: 2px;
  border-radius: 8px; font-size: 13px; color: #4a5157;
  text-decoration: none; cursor: pointer; transition: background .15s, color .15s;
}
.toc-item i { width: 16px; text-align: center; color: var(--muted); }
.toc-item:hover { background: var(--blue-3); }
.toc-item.active { background: var(--blue); color: #fff; }
.toc-item.active i { color: #fff; }

/* 右侧正文 */
.guide-content {
  flex: 1 1 auto;
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 8px 28px 28px;
  overflow-y: auto;
}
.doc-sec { padding: 20px 0 6px; border-bottom: 1px solid #f0f2f4; }
.doc-sec:last-of-type { border-bottom: none; }
.doc-sec h2 {
  font-size: 17px; margin: 0 0 12px;
  display: flex; align-items: center; gap: 10px; color: var(--blue);
}
.doc-sec h2 i { font-size: 15px; }
.doc-sec p { margin: 0 0 10px; line-height: 1.75; font-size: 14px; color: #3a4147; }
.steps, .bullet { margin: 0 0 10px; padding-left: 22px; line-height: 1.9; font-size: 14px; color: #3a4147; }
.steps li, .bullet li { margin-bottom: 4px; }
code {
  background: var(--blue-3); color: var(--blue);
  padding: 1px 6px; border-radius: 5px; font-size: 13px;
}
.tip {
  display: flex; align-items: flex-start; gap: 10px;
  background: #fff8ee; border: 1px solid #f6e2c4; border-radius: 10px;
  padding: 10px 14px; margin: 8px 0 4px; font-size: 13px; line-height: 1.7; color: #7a5a22;
}
.tip i { color: var(--orange); margin-top: 3px; }
.guide-foot { text-align: center; color: var(--muted); font-size: 13px; padding: 26px 0 6px; }
</style>
