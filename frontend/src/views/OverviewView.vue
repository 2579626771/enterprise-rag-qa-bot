<template>
  <main class="overview-page">
    <div class="archive-head">
      <div>
        <h1>运行概览 <span class="pill">全局知识分布</span></h1>
        <p>汇总你名下全部知识库的内容与解析入库统计</p>
      </div>
      <button class="btn-ghost" type="button" :disabled="loading" @click="refresh">
        <i class="fa-solid fa-rotate" :class="{ spin: loading }"></i> 刷新
      </button>
    </div>

    <!-- 统计徽章（全局汇总）-->
    <div class="stat-cards">
      <div class="stat-card">
        <div class="stat-icon"><i class="fa-solid fa-book"></i></div>
        <div><strong>{{ kbCount }}</strong><span>知识库总数</span></div>
      </div>
      <div class="stat-card">
        <div class="stat-icon"><i class="fa-regular fa-file-lines"></i></div>
        <div><strong>{{ totalDocs }}</strong><span>文档总数</span></div>
      </div>
      <div class="stat-card">
        <div class="stat-icon"><i class="fa-solid fa-layer-group"></i></div>
        <div><strong>{{ totalChunks }}</strong><span>知识片段</span></div>
      </div>
      <div class="stat-card">
        <div class="stat-icon"><i class="fa-solid fa-chart-simple"></i></div>
        <div><strong>{{ avgChunks }}</strong><span>平均片段/文档</span></div>
      </div>
    </div>

    <!-- 图表区（两张：环形按库占比 + 柱状按库文档数）-->
    <div class="chart-grid two-lg">
      <div v-for="(title, idx) in chartTitles" :key="title" class="chart-box tall">
        <h3>{{ title }}</h3>
        <div v-if="loading" class="chart-fallback">加载中…</div>
        <div v-else-if="chartError" class="chart-fallback">图表加载失败</div>
        <div v-else-if="!hasData" class="chart-fallback">暂无数据，请先到「我的知识库」上传文档</div>
        <div v-else :ref="(el) => setChartEl(el, idx)" class="chart big"></div>
      </div>
    </div>

    <p v-if="error" class="msg error archive-msg">{{ error }}</p>
  </main>
</template>

<script setup lang="ts">
import {
  computed, nextTick, onBeforeUnmount, onMounted, ref,
  type ComponentPublicInstance,
} from 'vue'
import { listKbs, fetchStats, extractErrorMessage } from '../api/client'

type EChartsInstance = { dispose(): void; resize(): void; setOption(o: unknown): void }

// 每个知识库的聚合行
interface KbAgg {
  id: number
  name: string
  documentCount: number
  totalChunks: number
}

const chartTitles = ['各知识库片段占比', '各知识库文档数']

const aggs = ref<KbAgg[]>([])
const loading = ref(false)
const error = ref('')
const chartError = ref(false)
const chartEls = ref<(HTMLElement | null)[]>([])
let echartsApi: null | { init(el: HTMLElement): EChartsInstance } = null
let charts: EChartsInstance[] = []

// ---- 全局汇总指标 ----
const kbCount = computed(() => aggs.value.length)
const totalDocs = computed(() => aggs.value.reduce((s, a) => s + a.documentCount, 0))
const totalChunks = computed(() => aggs.value.reduce((s, a) => s + a.totalChunks, 0))
const avgChunks = computed(() => {
  if (totalDocs.value === 0) return 0
  return Math.round((totalChunks.value / totalDocs.value) * 10) / 10
})
const hasData = computed(() => totalChunks.value > 0 || totalDocs.value > 0)

function setChartEl(el: Element | ComponentPublicInstance | null, idx: number) {
  chartEls.value[idx] = (el as HTMLElement | null) ?? null
}

function buildOptions() {
  // 环形图：各知识库片段占比（只取有片段的库，避免空库塞进图例）
  const pieData = aggs.value
    .filter((a) => a.totalChunks > 0)
    .map((a) => ({ value: a.totalChunks, name: a.name }))
  // 柱状图：各知识库文档数（按文档数降序，全部展示）
  const barRows = [...aggs.value].sort((a, b) => b.documentCount - a.documentCount)
  const barNames = barRows.map((a) => a.name)
  const barValues = barRows.map((a) => a.documentCount)
  const blue = '#1e3a5f'
  return [
    {
      tooltip: { trigger: 'item', formatter: '{b}: {c} 片段 ({d}%)' },
      legend: { bottom: 0, itemWidth: 8, itemHeight: 8, textStyle: { fontSize: 10 } },
      series: [
        {
          type: 'pie',
          radius: ['46%', '68%'],
          center: ['50%', '44%'],
          data: pieData,
          label: { fontSize: 10 },
        },
      ],
    },
    {
      tooltip: { trigger: 'axis', formatter: '{b}: {c} 篇文档' },
      grid: { left: 34, right: 14, top: 20, bottom: 56 },
      xAxis: {
        type: 'category', data: barNames, axisTick: { show: false },
        axisLabel: { fontSize: 10, interval: 0, rotate: barNames.length > 4 ? 32 : 0 },
      },
      yAxis: { type: 'value', minInterval: 1, splitLine: { lineStyle: { color: '#edf1f6' } } },
      series: [{ type: 'bar', barWidth: 28, itemStyle: { color: blue, borderRadius: [4, 4, 0, 0] }, data: barValues }],
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
  loading.value = true
  error.value = ''
  chartError.value = false
  try {
    // 1) 拉当前用户的知识库列表
    const { kbs } = await listKbs(false)
    // 2) 并发取每个库的统计，单个库失败不影响整体（降级为 0）
    const results = await Promise.all(
      kbs.map(async (kb) => {
        try {
          const s = await fetchStats(kb.id)
          return {
            id: kb.id,
            name: kb.name,
            documentCount: s.document_count,
            totalChunks: s.total_chunks,
          } as KbAgg
        } catch {
          return { id: kb.id, name: kb.name, documentCount: 0, totalChunks: 0 } as KbAgg
        }
      }),
    )
    aggs.value = results
  } catch (e) {
    error.value = extractErrorMessage(e)
    chartError.value = true
    loading.value = false
    return
  }
  // 先结束 loading 让图表容器渲染进 DOM，再等一个 tick 初始化 ECharts
  loading.value = false
  await nextTick()
  await renderCharts()
}

const resizeCharts = () => charts.forEach((c) => c.resize())

onMounted(async () => {
  await refresh()
  window.addEventListener('resize', resizeCharts)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', resizeCharts)
  charts.forEach((c) => c.dispose())
})
</script>
