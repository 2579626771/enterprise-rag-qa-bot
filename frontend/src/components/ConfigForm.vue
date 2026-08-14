<template>
  <div class="cfg-form">
    <div class="form-row">
      <label class="form-label">Top-K（检索片段数）</label>
      <input v-model.number="model.top_k" type="number" min="1" max="20" class="text-input" />
      <p class="hint">每次提问检索的最相关片段数，1~20。</p>
    </div>
    <div class="form-row">
      <label class="form-label">相似度距离阈值</label>
      <input v-model.number="model.max_distance" type="number" min="0" max="1" step="0.05" class="text-input" />
      <p class="hint">余弦距离，0~1。越小越严格；大于该值的片段判为不相关丢弃。</p>
    </div>
    <div class="form-row">
      <label class="form-label">研判防幻觉</label>
      <label class="switch-line">
        <input v-model="model.judge_enabled" type="checkbox" />
        <span>开启（作答前先判断资料是否真能回答，不能答则拒答）</span>
      </label>
    </div>
    <div class="form-row">
      <label class="form-label">作答提示词</label>
      <textarea v-model="model.answer_prompt" class="text-input area" rows="6"
                placeholder="留空则使用系统默认作答提示词"></textarea>
      <p class="hint">指令前言（资料与问题由系统自动拼接，无需在此写占位符）。</p>
    </div>

    <slot />

    <div class="form-foot">
      <button class="primary" type="button" :disabled="saving" @click="$emit('save')">
        {{ saving ? '保存中…' : '保存' }}
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { RetrievalConfig } from '../api/client'

defineProps<{
  model: RetrievalConfig
  saving: boolean
}>()

defineEmits<{ (e: 'save'): void }>()
</script>

<style scoped>
.cfg-form {
  max-width: 640px;
}
.form-row {
  margin-bottom: 16px;
}
.form-label {
  display: block;
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 6px;
}
.text-input {
  width: 100%;
  height: 40px;
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 0 12px;
  outline: none;
  box-sizing: border-box;
}
.text-input:focus {
  border-color: var(--blue-2);
}
.text-input.area {
  height: auto;
  padding: 10px 12px;
  line-height: 1.5;
  resize: vertical;
  font-family: inherit;
}
.switch-line {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--muted);
}
.switch-line input {
  width: 16px;
  height: 16px;
}
.hint {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--muted);
}
.form-foot {
  margin-top: 8px;
}
</style>
