<template>
  <div class="modal-mask" @click.self="close">
    <div class="modal progress-modal">
      <div class="modal-head">
        <h3>文档上传进度</h3>
        <button class="modal-close" type="button" @click="close"><i class="fa-solid fa-xmark"></i></button>
      </div>

      <div class="progress-body">
        <div v-if="tasks.length === 0" class="table-empty">
          暂无上传任务
        </div>

        <ul v-else class="task-list">
          <li v-for="t in tasks" :key="t.id" class="task-item">
            <div class="task-top">
              <span class="task-type-ico"><i :class="iconFor(t.filename)"></i></span>
              <div class="task-copy">
                <strong :title="t.filename">{{ t.filename }}</strong>
                <small>{{ formatSize(t.size) }} · {{ t.topic }} · {{ t.startedAt }}</small>
              </div>
              <span :class="['phase-badge', t.phase]">{{ phaseText(t) }}</span>
              <button
                v-if="t.phase === 'success' || t.phase === 'error'"
                class="icon-button"
                type="button"
                aria-label="移除"
                @click="remove(t.id)"
              >
                <i class="fa-solid fa-xmark"></i>
              </button>
            </div>

            <!-- 进度条 -->
            <div class="track">
              <div
                :class="['bar', t.phase]"
                :style="{ width: barWidth(t) }"
              ></div>
            </div>

            <div class="task-foot">
              <span v-if="t.phase === 'uploading'">传输中 {{ t.percent }}%</span>
              <span v-else-if="t.phase === 'processing'">已传输完成，正在解析并写入知识库…</span>
              <span v-else-if="t.phase === 'success'" class="ok">✓ 入库成功，共 {{ t.chunkCount }} 个知识片段</span>
              <span v-else class="fail">✗ {{ t.error }}</span>
            </div>
          </li>
        </ul>
      </div>

      <div class="modal-foot">
        <button class="btn-ghost" type="button" :disabled="!hasFinished" @click="clearFinished">清除已完成</button>
        <button class="primary" type="button" @click="close">关闭</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { fileExt } from '../api/client'
import { useUploadTasks, type UploadTask } from '../composables/useUploadTasks'

const emit = defineEmits<{ (e: 'close'): void }>()

const { tasks, remove, clearFinished } = useUploadTasks()

const hasFinished = computed(() =>
  tasks.value.some((t) => t.phase === 'success' || t.phase === 'error'),
)

function close() {
  emit('close')
}

function phaseText(t: UploadTask): string {
  return { uploading: '传输中', processing: '处理中', success: '已完成', error: '失败' }[t.phase]
}

function barWidth(t: UploadTask): string {
  if (t.phase === 'uploading') return `${t.percent}%`
  return '100%' // processing/success/error 都占满，用颜色/动画区分
}

function iconFor(filename: string): string {
  const ext = fileExt(filename).toLowerCase()
  if (ext === 'pdf') return 'fa-regular fa-file-pdf'
  if (ext === 'docx') return 'fa-regular fa-file-word'
  return 'fa-regular fa-file-lines'
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}
</script>
