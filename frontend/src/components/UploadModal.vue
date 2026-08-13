<template>
  <div class="modal-mask" @click.self="close">
    <div class="modal upload-modal">
      <div class="modal-head">
        <h3>上传文档</h3>
        <button class="modal-close" type="button" @click="close"><i class="fa-solid fa-xmark"></i></button>
      </div>

      <div class="upload-body">
        <!-- 文件拖拽区 -->
        <div class="form-row">
          <label class="form-label">文件</label>
          <div
            :class="['drop-zone', { dragover: dragging, 'has-file': !!file }]"
            @click="pick"
            @dragover.prevent="dragging = true"
            @dragleave.prevent="dragging = false"
            @drop.prevent="onDrop"
          >
            <input ref="fileInput" type="file" :accept="acceptAttr" style="display: none" @change="onPick" />
            <template v-if="file">
              <i class="fa-regular fa-file-lines drop-ico"></i>
              <p class="drop-main">{{ file.name }}</p>
              <p class="drop-sub">{{ formatSize(file.size) }} · 点击可重新选择</p>
            </template>
            <template v-else>
              <i class="fa-solid fa-cloud-arrow-up drop-ico"></i>
              <p class="drop-main">点击或拖拽文件到此区域上传</p>
              <p class="drop-sub">支持文本与文档格式，最大 100MB</p>
              <div class="fmt-grid">
                <span>文本：TXT、Markdown(MD)</span>
                <span>文档：PDF、Word(DOCX)</span>
              </div>
            </template>
          </div>
          <p class="fmt-note"><i class="fa-solid fa-circle-info"></i> 已支持 TXT / MD / PDF / DOCX 解析入库（旧版 .doc 请另存为 .docx）</p>
        </div>

        <!-- 知识主题 -->
        <div class="form-row">
          <label class="form-label req">知识主题</label>
          <select v-model="topic" class="select full">
            <option value="" disabled>请选择知识主题</option>
            <option v-for="t in topics" :key="t" :value="t">{{ t }}</option>
          </select>
        </div>

        <!-- 文档描述 -->
        <div class="form-row">
          <label class="form-label">文档描述</label>
          <textarea
            v-model="description"
            class="textarea"
            rows="3"
            placeholder="选填：简要描述该文档的内容、用途或适用范围…"
          ></textarea>
        </div>

        <p v-if="err" class="msg error">{{ err }}</p>
      </div>

      <div class="modal-foot">
        <button class="btn-ghost" type="button" @click="close">取消</button>
        <button class="primary" type="button" :disabled="!canSubmit || submitting" @click="submit">
          {{ submitting ? '上传中…' : '确定上传' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { KNOWLEDGE_TOPICS } from '../api/client'
import { useUploadTasks } from '../composables/useUploadTasks'
import { useKnowledgeBase } from '../composables/useKnowledgeBase'

const emit = defineEmits<{ (e: 'close'): void; (e: 'uploaded', filename: string): void }>()

const topics = KNOWLEDGE_TOPICS
const { runUpload } = useUploadTasks()
const { currentKbId } = useKnowledgeBase()

const SUPPORTED = ['.txt', '.md', '.pdf', '.docx']
const acceptAttr = SUPPORTED.join(',')

const fileInput = ref<HTMLInputElement | null>(null)
const file = ref<File | null>(null)
const topic = ref('')
const description = ref('')
const dragging = ref(false)
const submitting = ref(false)
const err = ref('')

const canSubmit = computed(() => !!file.value && !!topic.value)

function pick() {
  fileInput.value?.click()
}

function setFile(f: File | undefined) {
  if (!f) return
  const ext = '.' + (f.name.split('.').pop()?.toLowerCase() ?? '')
  if (!SUPPORTED.includes(ext)) {
    err.value = `不支持的格式，仅支持：${SUPPORTED.join('、')}`
    return
  }
  err.value = ''
  file.value = f
}

function onPick(e: Event) {
  setFile((e.target as HTMLInputElement).files?.[0])
}

function onDrop(e: DragEvent) {
  dragging.value = false
  setFile(e.dataTransfer?.files?.[0])
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function close() {
  emit('close')
}

async function submit() {
  if (!file.value || !topic.value || submitting.value) return
  // 交给全局上传任务（后台执行，弹窗关闭也继续），上传到当前知识库
  runUpload(file.value, currentKbId.value, topic.value, description.value)
  emit('uploaded', file.value.name)
}
</script>
