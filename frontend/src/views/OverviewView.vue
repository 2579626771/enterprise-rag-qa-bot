<template>
  <main class="overview-page">
    <div class="archive-head">
      <div>
        <h1>运行概览 <span class="pill">知识分布</span></h1>
        <p>知识库内容与解析入库状态的实时统计</p>
      </div>
      <button class="btn-ghost" type="button" :disabled="loading" @click="refresh">
        <i class="fa-solid fa-rotate"></i> 刷新
      </button>
    </div>

    <!-- 统计徽章 -->
    <div class="stat-cards">
      <div class="stat-card">
        <div class="stat-icon"><i class="fa-regular fa-file-lines"></i></div>
        <div><strong>{{ stats?.document_count ?? 0 }}</strong><span>文档总数</span></div>
      </div>
      <div class="stat-card">
        <div class="stat-icon"><i class="fa-solid fa-layer-group"></i></div>
        <div><strong>{{ stats?.total_chunks ?? 0 }}</strong><span>知识片段</span></div>
      </div>
      <div class="stat-card">
        <div class="stat-icon"><i class="fa-solid fa-chart-simple"></i></div>
        <div><strong>{{ avgChunks }}</strong><span>平均片段/文档</span></div>
      </div>
      <div class="stat-card">
        <div class="stat-icon"><i class="fa-solid fa-crown"></i></div>
        <div><strong>{{ topDocChunks }}</strong><span>最大文档片段</span></div>
      </div>
    </div>

    <!-- 图表区 -->
    <div class="chart-grid three">
      <div v-for="(title, idx) in chartTitles" :key="title" class="chart-box tall">
        <h3>{{ title }}</h3>
        <div v-if="loading" class="chart-fallback">加载中…</div>
        <div v-else-if="chartError" class="chart-fallback">图表加载失败</div>
        <div v-else-if="!hasData" class="chart-fallback">暂无数据，请先在「资料档案库」上传文档</div>
        <div v-else :ref="(el) => setChartEl(el, idx)" class="chart big"></div>
      </div>
    </div>

    <p v-if="error" class="msg error archive-msg">{{ error }}</p>
  </main>
</template>

<script setup lang="ts">
import {
  computed, nextTick, onBeforeUnmount, onMounted, ref, watch,
  type ComponentPublicInstance,
} from 'vue'
import { fetchStats, extractErrorMessage, type StatsResponse } from '../api/client'
import { useKnowledgeBase } from '../composables/useKnowledgeBase'

type EChartsInstance = { dispose(): void; resize(): void; setOption(o: unknown): void }

const { currentKbId } = useKnowledgeBase()

const chartTitles = ['各文档片段占比', '片段分布', '片段数排名']

const stats = ref<StatsResponse | null>(null)
const loading = ref(false)
const error = ref('')
const chartError = ref(false)
const chartEls = ref<(HTMLElement | null)[]>([])
let echartsApi: null | { init(el: HTMLElement): EChartsInstance } = null
let charts: EChartsInstance[] = []

const hasData = computed(() => !!stats.value && stats.value.total_chunks > 0)
const avgChunks = computed(() => {
  const s = stats.value
  if (!s || s.document_count === 0) return 0
  return Math.round((s.total_chunks / s.document_count) * 10) / 10
})
const topDocChunks = computed(() => stats.value?.per_document[0]?.chunk_count ?? 0)

function setChartEl(el: Element | ComponentPublicInstance | null, idx: number) {
  chartEls.value[idx] = (el as HTMLElement | null) ?? null
}

function buildOptions() {
  const perDoc = stats.value?.per_document ?? []
  const pieData = perDoc.map((d) => ({ value: d.chunk_count, name: d.filename }))
  const names = perDoc.map((d) => d.filename)
  const values = perDoc.map((d) => d.chunk_count)
  const blue = '#1e3a5f'
  return [
    {
      tooltip: { trigger: 'item' },
      legend: { bottom: 0, itemWidth: 8, itemHeight: 8, textStyle: { fontSize: 10 } },
      series: [{ type: 'pie', radius: ['46%', '68%'], center: ['50%', '44%'], data: pieData }],
    },
    {
      tooltip: { trigger: 'item' },
      legend: { bottom: 0, itemWidth: 8, itemHeight: 8, textStyle: { fontSize: 10 } },
      series: [{ type: 'pie', radius: '62%', center: ['50%', '44%'], data: pieData }],
    },
    {
      tooltip: { trigger: 'axis' },
      grid: { left: 34, right: 14, top: 20, bottom: 56 },
      xAxis: {
        type: 'category', data: names, axisTick: { show: false },
        axisLabel: { fontSize: 9, interval: 0, rotate: 32 },
      },
      yAxis: { type: 'value', splitLine: { lineStyle: { color: '#edf1f6' } } },
      series: [{ type: 'bar', barWidth: 22, itemStyle: { color: blue, borderRadius: [4, 4, 0, 0] }, data: values }],
    },
  ]
}

async function renderCharts() {
  charts.forEach((c) => c.dispose())
  charts = []
  if (!hasData.value) return
  try {
    echartsApi ??= await import('../charts')
    chartError.value = false
    await nextTick()
    const options = buildOptions()
    charts = chartEls.value
      .filter((el): el is HTMLElement => !!el)
      .map((el, i) => {
        const c = echartsApi!.init(el)
        c.setOption(options[i])
        return c
      })
  } catch {
    chartError.value = true
  }
}

async function refresh() {
  if (!currentKbId.value) {
    stats.value = null
    return
  }
  loading.value = true
  error.value = ''
  chartError.value = false
  try {
    stats.value = await fetchStats(currentKbId.value)
  } catch (e) {
    error.value = extractErrorMessage(e)
    chartError.value = true
    loading.value = false
    return
  }
  // 关键：先结束 loading，让图表容器 <div> 真正渲染进 DOM，
  // 再等一个 tick 后初始化 ECharts，否则容器还不存在、图表画不出来。
  loading.value = false
  await nextTick()
  await renderCharts()
}

const resizeCharts = () => charts.forEach((c) => c.resize())

// 切换知识库后重新拉取该库的统计
watch(currentKbId, () => {
  refresh()
})

onMounted(async () => {
  await refresh()
  window.addEventListener('resize', resizeCharts)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', resizeCharts)
  charts.forEach((c) => c.dispose())
})
</script>
