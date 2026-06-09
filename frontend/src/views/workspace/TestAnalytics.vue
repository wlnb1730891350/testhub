<template>
  <div class="analytics-page">
    <div class="analytics-header">
      <div>
        <h2>Test Analytics</h2>
        <p>Cross-module execution trends and coverage insights</p>
      </div>
      <div class="header-actions">
        <el-select v-model="timeRange" size="default" style="width: 140px">
          <el-option label="Last 7 days" value="7d" />
          <el-option label="Last 30 days" value="30d" />
          <el-option label="Last 90 days" value="90d" />
        </el-select>
        <el-button @click="refresh" :loading="loading">
          <el-icon><Refresh /></el-icon>
          Refresh
        </el-button>
      </div>
    </div>

    <!-- Summary Cards -->
    <div class="summary-row">
      <div class="summary-card" v-for="card in summaryCards" :key="card.label">
        <div class="summary-icon" :style="{ background: card.bg }">
          <el-icon :style="{ color: card.color }"><component :is="card.icon" /></el-icon>
        </div>
        <div>
          <span class="summary-value">{{ card.value }}</span>
          <span class="summary-label">{{ card.label }}</span>
        </div>
      </div>
    </div>

    <!-- Execution Distribution -->
    <div class="analytics-grid">
      <div class="chart-card">
        <h3>Execution Distribution by Module</h3>
        <div class="bar-chart">
          <div v-for="bar in moduleBars" :key="bar.label" class="bar-row">
            <span class="bar-label">{{ bar.label }}</span>
            <div class="bar-track">
              <div class="bar-fill" :style="{ width: bar.pct + '%', background: bar.color }"></div>
            </div>
            <span class="bar-value">{{ bar.value }}</span>
          </div>
        </div>
      </div>

      <div class="chart-card">
        <h3>Health Status Breakdown</h3>
        <div class="donut-container">
          <svg viewBox="0 0 120 120" class="donut">
            <circle cx="60" cy="60" r="50" fill="none" stroke="#e2e8f0" stroke-width="12" />
            <circle
              v-for="(seg, i) in donutSegments"
              :key="i"
              cx="60" cy="60" r="50"
              fill="none"
              :stroke="seg.color"
              stroke-width="12"
              :stroke-dasharray="seg.dashArray"
              :stroke-dashoffset="seg.offset"
              stroke-linecap="round"
            />
          </svg>
          <div class="donut-center">
            <span class="donut-total">{{ totalExecutions }}</span>
            <span class="donut-label">Total</span>
          </div>
        </div>
        <div class="legend">
          <div v-for="item in donutLegend" :key="item.label" class="legend-item">
            <span class="legend-dot" :style="{ background: item.color }"></span>
            <span>{{ item.label }}</span>
            <span class="legend-val">{{ item.value }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Recent Activity Timeline -->
    <div class="chart-card timeline-card">
      <h3>Activity Timeline</h3>
      <div v-if="activities.length" class="timeline">
        <div v-for="(act, i) in activities" :key="i" class="timeline-item" @click="navigate(act.route)">
          <div class="timeline-dot" :class="'dot-' + act.statusClass"></div>
          <div class="timeline-line" v-if="i < activities.length - 1"></div>
          <div class="timeline-content">
            <span class="timeline-title">{{ act.title }}</span>
            <span class="timeline-meta">{{ act.module }} &middot; {{ act.status }} &middot; {{ act.timeAgo }}</span>
          </div>
        </div>
      </div>
      <el-empty v-else description="No recent activity" :image-size="80" />
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { Refresh, Document, VideoPlay, DataLine, Monitor } from '@element-plus/icons-vue'
import { getWorkspaceDashboard } from '@/api/core'

const router = useRouter()
const loading = ref(false)
const timeRange = ref('7d')
const metrics = ref({})
const focus = ref({})
const activities = ref([])

const summaryCards = computed(() => [
  { label: 'API Executions', value: focus.value.api_execution_count ?? '--', icon: VideoPlay, color: '#1d4ed8', bg: 'rgba(29,78,216,0.1)' },
  { label: 'UI Executions', value: focus.value.ui_execution_count ?? '--', icon: Monitor, color: '#b45309', bg: 'rgba(180,83,9,0.1)' },
  { label: 'APP Executions', value: focus.value.app_execution_count ?? '--', icon: DataLine, color: '#0f766e', bg: 'rgba(15,118,110,0.1)' },
  { label: 'Manual Runs', value: focus.value.manual_run_count ?? '--', icon: Document, color: '#7c3aed', bg: 'rgba(124,58,237,0.1)' },
])

const moduleBars = computed(() => {
  const api = focus.value.api_execution_count || 0
  const ui = focus.value.ui_execution_count || 0
  const app = focus.value.app_execution_count || 0
  const manual = focus.value.manual_run_count || 0
  const max = Math.max(api, ui, app, manual, 1)
  return [
    { label: 'API Testing', value: api, pct: (api / max) * 100, color: '#3b82f6' },
    { label: 'UI Automation', value: ui, pct: (ui / max) * 100, color: '#f59e0b' },
    { label: 'APP Automation', value: app, pct: (app / max) * 100, color: '#10b981' },
    { label: 'Manual Execution', value: manual, pct: (manual / max) * 100, color: '#8b5cf6' },
  ]
})

const totalExecutions = computed(() => {
  return (focus.value.api_execution_count || 0) + (focus.value.ui_execution_count || 0) +
    (focus.value.app_execution_count || 0) + (focus.value.manual_run_count || 0)
})

const donutLegend = computed(() => [
  { label: 'API', value: focus.value.api_execution_count || 0, color: '#3b82f6' },
  { label: 'UI', value: focus.value.ui_execution_count || 0, color: '#f59e0b' },
  { label: 'APP', value: focus.value.app_execution_count || 0, color: '#10b981' },
  { label: 'Manual', value: focus.value.manual_run_count || 0, color: '#8b5cf6' },
])

const donutSegments = computed(() => {
  const total = totalExecutions.value || 1
  const circumference = 2 * Math.PI * 50
  const items = donutLegend.value
  let accumulated = 0
  return items.map(item => {
    const pct = item.value / total
    const segLen = pct * circumference
    const offset = -accumulated * circumference + circumference * 0.25
    accumulated += pct
    return {
      color: item.color,
      dashArray: `${segLen} ${circumference - segLen}`,
      offset: -offset,
    }
  })
})

function timeAgo(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  const diffMin = Math.floor((Date.now() - d) / 60000)
  if (diffMin < 1) return 'just now'
  if (diffMin < 60) return diffMin + 'm ago'
  const h = Math.floor(diffMin / 60)
  if (h < 24) return h + 'h ago'
  return Math.floor(h / 24) + 'd ago'
}

function statusClass(s) {
  if (!s) return 'default'
  const v = String(s).toLowerCase()
  if (['completed', 'passed', 'active'].includes(v)) return 'success'
  if (['failed', 'error'].includes(v)) return 'error'
  if (['in_progress', 'generating', 'writing'].includes(v)) return 'running'
  return 'pending'
}

function navigate(route) { if (route) router.push(route) }

async function refresh() {
  loading.value = true
  try {
    const res = await getWorkspaceDashboard()
    metrics.value = res.data.metrics || {}
    focus.value = res.data.focus || {}
    activities.value = (res.data.recent_activities || []).map(a => ({
      ...a,
      timeAgo: timeAgo(a.time),
      statusClass: statusClass(a.status),
    }))
  } catch {} finally { loading.value = false }
}

onMounted(refresh)
</script>

<style scoped>
.analytics-page {
  max-width: 1200px;
  margin: 0 auto;
  padding: 24px;
}
.analytics-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 24px;
}
.analytics-header h2 {
  margin: 0;
  font-size: 1.6rem;
  color: #0f172a;
}
.analytics-header p {
  margin: 6px 0 0;
  color: #64748b;
}
.header-actions {
  display: flex;
  gap: 10px;
  align-items: center;
}
.summary-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 24px;
}
.summary-card {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 20px;
  border-radius: 18px;
  background: rgba(255,255,255,0.9);
  border: 1px solid rgba(148,163,184,0.15);
  box-shadow: 0 4px 16px rgba(15,23,42,0.04);
}
.summary-icon {
  width: 48px;
  height: 48px;
  border-radius: 14px;
  display: grid;
  place-items: center;
  font-size: 1.3rem;
  flex-shrink: 0;
}
.summary-value {
  display: block;
  font-size: 1.8rem;
  font-weight: 800;
  color: #0f172a;
  line-height: 1.1;
}
.summary-label {
  font-size: 0.82rem;
  color: #64748b;
}
.analytics-grid {
  display: grid;
  grid-template-columns: 1.2fr 0.8fr;
  gap: 20px;
  margin-bottom: 24px;
}
.chart-card {
  padding: 24px;
  border-radius: 20px;
  background: rgba(255,255,255,0.9);
  border: 1px solid rgba(148,163,184,0.15);
  box-shadow: 0 4px 16px rgba(15,23,42,0.04);
}
.chart-card h3 {
  margin: 0 0 20px;
  font-size: 1rem;
  color: #334155;
}
.bar-chart {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.bar-row {
  display: flex;
  align-items: center;
  gap: 14px;
}
.bar-label {
  width: 130px;
  font-size: 0.88rem;
  color: #475569;
  font-weight: 500;
  flex-shrink: 0;
}
.bar-track {
  flex: 1;
  height: 24px;
  border-radius: 12px;
  background: #f1f5f9;
  overflow: hidden;
}
.bar-fill {
  height: 100%;
  border-radius: 12px;
  transition: width 0.6s ease;
  min-width: 4px;
}
.bar-value {
  width: 50px;
  text-align: right;
  font-size: 0.9rem;
  font-weight: 700;
  color: #334155;
}
.donut-container {
  position: relative;
  width: 160px;
  height: 160px;
  margin: 0 auto 20px;
}
.donut {
  width: 100%;
  height: 100%;
  transform: rotate(-90deg);
}
.donut-center {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  text-align: center;
}
.donut-total {
  display: block;
  font-size: 1.6rem;
  font-weight: 800;
  color: #0f172a;
}
.donut-label {
  font-size: 0.78rem;
  color: #94a3b8;
}
.legend {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  justify-content: center;
}
.legend-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.82rem;
  color: #475569;
}
.legend-dot {
  width: 10px;
  height: 10px;
  border-radius: 3px;
}
.legend-val {
  font-weight: 700;
  color: #334155;
}
.timeline-card {
  margin-bottom: 24px;
}
.timeline {
  display: flex;
  flex-direction: column;
  gap: 0;
}
.timeline-item {
  position: relative;
  display: flex;
  align-items: flex-start;
  gap: 16px;
  padding: 14px 0;
  cursor: pointer;
}
.timeline-item:hover { background: rgba(248,250,252,0.5); border-radius: 8px; }
.timeline-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  flex-shrink: 0;
  margin-top: 4px;
  z-index: 1;
}
.dot-success { background: #22c55e; }
.dot-error { background: #ef4444; }
.dot-running { background: #3b82f6; animation: pulse 1.5s infinite; }
.dot-pending { background: #f59e0b; }
.dot-default { background: #94a3b8; }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }
.timeline-line {
  position: absolute;
  left: 5px;
  top: 26px;
  bottom: -14px;
  width: 2px;
  background: #e2e8f0;
}
.timeline-content {
  display: flex;
  flex-direction: column;
}
.timeline-title {
  font-size: 0.9rem;
  color: #334155;
  font-weight: 500;
}
.timeline-meta {
  font-size: 0.78rem;
  color: #94a3b8;
  margin-top: 4px;
}
@media (max-width: 900px) {
  .summary-row { grid-template-columns: repeat(2, 1fr); }
  .analytics-grid { grid-template-columns: 1fr; }
}
@media (max-width: 640px) {
  .summary-row { grid-template-columns: 1fr; }
  .analytics-header { flex-direction: column; gap: 12px; }
}
</style>