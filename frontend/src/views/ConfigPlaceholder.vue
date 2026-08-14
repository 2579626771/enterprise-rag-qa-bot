<template>
  <main class="config">
    <div class="config-head">
      <h1>检索配置</h1>
      <p>在线调整检索与作答参数，保存后立即生效（无需重启后端 / 改 .env）。</p>
    </div>

    <!-- 系统默认（仅管理员） -->
    <section v-if="isAdmin" class="cfg-card">
      <div class="cfg-card-head">
        <h2>系统默认 <span class="pill">仅管理员</span></h2>
        <p>全系统兜底默认，未设置租户/知识库配置时生效。</p>
      </div>
      <ConfigForm
        :model="sys"
        :saving="savingSys"
        @save="onSaveSystem"
      />
    </section>

    <!-- 我的默认（租户） -->
    <section class="cfg-card">
      <div class="cfg-card-head">
        <h2>我的默认</h2>
        <p>
          作用于我所有知识库的默认参数。
          <span v-if="tenant.inherited" class="muted">（当前继承自系统默认）</span>
        </p>
      </div>
      <ConfigForm :model="tenant" :saving="savingTenant" @save="onSaveTenant">
        <div class="form-row">
          <label class="form-label">多库/全库查询使用</label>
          <select v-model="tenant.multi_scope" class="select full">
            <option value="system">系统默认配置</option>
            <option value="tenant">我的默认配置</option>
          </select>
          <p class="hint">选择“全部知识库”提问时，采用哪一份参数。</p>
        </div>
      </ConfigForm>
    </section>

    <!-- 按知识库 -->
    <section class="cfg-card">
      <div class="cfg-card-head">
        <h2>按知识库</h2>
        <p>为单个知识库设置独立参数，优先级高于我的默认。</p>
      </div>
      <div class="form-row">
        <label class="form-label">选择知识库</label>
        <select v-model.number="selectedKbId" class="select full" @change="loadKb">
          <option :value="0" disabled>请选择一个知识库…</option>
          <option v-for="kb in kbList" :key="kb.id" :value="kb.id">{{ kb.name }}</option>
        </select>
      </div>
      <template v-if="selectedKbId">
        <p v-if="kb.inherited" class="muted kb-inherit">
          该库暂无独立配置，下方为继承值；保存后即成为该库专属配置。
        </p>
        <ConfigForm :model="kb" :saving="savingKb" @save="onSaveKb">
          <div v-if="!kb.inherited" class="form-row">
            <button class="op-link danger" type="button" @click="onResetKb">
              <i class="fa-solid fa-rotate-left"></i> 重置为继承
            </button>
          </div>
        </ConfigForm>
      </template>
    </section>

    <!-- 保存结果弹窗：成功/失败都明确提示 -->
    <div v-if="dialog.show" class="modal-mask" @click.self="closeDialog">
      <div class="modal result-modal">
        <div class="modal-head">
          <h3>
            <i
              :class="dialog.ok ? 'fa-solid fa-circle-check ok' : 'fa-solid fa-circle-exclamation fail'"
            ></i>
            {{ dialog.title }}
          </h3>
          <button class="modal-close" type="button" @click="closeDialog">
            <i class="fa-solid fa-xmark"></i>
          </button>
        </div>
        <div class="result-body">
          <p class="result-msg">{{ dialog.message }}</p>
          <p v-if="dialog.ok && dialog.sub" class="result-sub">
            {{ dialog.sub }}
          </p>
        </div>
        <div class="modal-foot">
          <button class="primary" type="button" @click="closeDialog">知道了</button>
        </div>
      </div>
    </div>
  </main>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import {
  getRetrievalConfig,
  saveRetrievalConfig,
  resetKbRetrievalConfig,
  extractErrorMessage,
  type RetrievalConfig,
} from '../api/client'
import { useAuth } from '../composables/useAuth'
import { useKnowledgeBase } from '../composables/useKnowledgeBase'
import ConfigForm from '../components/ConfigForm.vue'

const { isAdmin } = useAuth()
const { kbList, refreshKbs } = useKnowledgeBase()

// 保存结果弹窗（成功/失败都弹，给用户明确反馈）
const dialog = reactive({ show: false, ok: true, title: '', message: '', sub: '' })
function ok(message: string, sub = '') {
  dialog.ok = true
  dialog.title = '保存成功'
  dialog.message = message
  dialog.sub = sub
  dialog.show = true
}
function fail(message: string) {
  dialog.ok = false
  dialog.title = '保存失败'
  dialog.message = message
  dialog.sub = ''
  dialog.show = true
}
function closeDialog() {
  dialog.show = false
}

const sys = reactive<RetrievalConfig>(blank())
const tenant = reactive<RetrievalConfig>(blank())
const kb = reactive<RetrievalConfig>(blank())

const savingSys = ref(false)
const savingTenant = ref(false)
const savingKb = ref(false)
const selectedKbId = ref(0)

function blank(): RetrievalConfig {
  return { top_k: 5, max_distance: 0.5, judge_enabled: false, answer_prompt: '', multi_scope: 'system', inherited: false }
}

function fill(target: RetrievalConfig, src: RetrievalConfig) {
  target.top_k = src.top_k
  target.max_distance = src.max_distance
  target.judge_enabled = src.judge_enabled
  target.answer_prompt = src.answer_prompt
  target.multi_scope = src.multi_scope ?? 'system'
  target.inherited = src.inherited ?? false
}

async function loadSystem() {
  if (!isAdmin.value) return
  try {
    fill(sys, await getRetrievalConfig('system'))
  } catch (e) {
    fail(extractErrorMessage(e))
  }
}

async function loadTenant() {
  try {
    fill(tenant, await getRetrievalConfig('tenant'))
  } catch (e) {
    fail(extractErrorMessage(e))
  }
}

async function loadKb() {
  if (!selectedKbId.value) return
  try {
    fill(kb, await getRetrievalConfig('kb', selectedKbId.value))
  } catch (e) {
    fail(extractErrorMessage(e))
  }
}

async function onSaveSystem() {
  savingSys.value = true
  try {
    fill(sys, await saveRetrievalConfig('system', payload(sys)))
    ok('系统默认配置已保存', '已写入数据库。所有用户下次提问即按新参数生效（未设置自己的租户/知识库配置时）。')
  } catch (e) {
    fail(extractErrorMessage(e))
  } finally {
    savingSys.value = false
  }
}

async function onSaveTenant() {
  savingTenant.value = true
  try {
    fill(tenant, await saveRetrievalConfig('tenant', { ...payload(tenant), multi_scope: tenant.multi_scope }))
    ok('我的默认配置已保存', '已写入数据库。仅作用于你自己的所有知识库，下次提问即生效，不影响其他用户。')
  } catch (e) {
    fail(extractErrorMessage(e))
  } finally {
    savingTenant.value = false
  }
}

async function onSaveKb() {
  if (!selectedKbId.value) return
  savingKb.value = true
  try {
    fill(kb, await saveRetrievalConfig('kb', payload(kb), selectedKbId.value))
    ok('该知识库配置已保存', '已写入数据库。仅作用于所选知识库，优先级高于你的默认，下次在该库提问即生效。')
  } catch (e) {
    fail(extractErrorMessage(e))
  } finally {
    savingKb.value = false
  }
}

async function onResetKb() {
  if (!selectedKbId.value) return
  if (!confirm('确定清除该知识库的独立配置、回落为继承？')) return
  try {
    fill(kb, await resetKbRetrievalConfig(selectedKbId.value))
    ok('已重置为继承', '该知识库的独立配置已清除，将回落使用你的默认 / 系统默认。')
  } catch (e) {
    fail(extractErrorMessage(e))
  }
}

function payload(m: RetrievalConfig) {
  return {
    top_k: m.top_k,
    max_distance: m.max_distance,
    judge_enabled: m.judge_enabled,
    answer_prompt: m.answer_prompt,
  }
}

onMounted(async () => {
  await refreshKbs()
  await loadSystem()
  await loadTenant()
})
</script>

<style scoped>
.config {
  padding: 26px 30px;
  overflow-y: auto;
}
.config-head h1 {
  margin: 0 0 4px;
  font-size: 22px;
}
.config-head p {
  margin: 0 0 20px;
  color: var(--muted);
  font-size: 13px;
}
.cfg-card {
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 20px 22px;
  margin-bottom: 18px;
  background: var(--card, #fff);
}
.cfg-card-head h2 {
  margin: 0 0 4px;
  font-size: 16px;
}
.cfg-card-head p {
  margin: 0 0 16px;
  color: var(--muted);
  font-size: 12px;
}
.pill {
  font-size: 12px;
  padding: 2px 10px;
  border-radius: 10px;
  background: var(--blue-3);
  color: var(--blue);
  vertical-align: middle;
}
.muted {
  color: var(--muted);
}
.kb-inherit {
  font-size: 12px;
  margin: 0 0 12px;
}
.hint {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--muted);
}
.config-msg {
  margin-top: 14px;
}
.result-modal {
  width: 440px;
}
.result-body {
  padding: 22px 24px;
}
.result-msg {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
}
.result-sub {
  margin: 10px 0 0;
  font-size: 13px;
  color: var(--muted);
  line-height: 1.6;
}
.modal-head h3 .ok {
  color: #1d6f42;
  margin-right: 6px;
}
.modal-head h3 .fail {
  color: #b91c1c;
  margin-right: 6px;
}
</style>
