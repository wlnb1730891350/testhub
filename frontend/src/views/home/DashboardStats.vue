<template>
  <div class="dashboard-stats">
    <div class="stats-header">
      <h3>Platform Overview</h3>
      <el-button size="small" text @click="refresh" :loading="loading">
        <el-icon><Refresh /></el-icon>
      </el-button>
    </div>
    <div class="stats-grid">
      <div class="stat-card" v-for="item in statCards" :key="item.label">
        <div class="stat-icon" :style="{ background: item.bgColor }">
          <el-icon :style="{ color: item.color }"><component :is="item.icon" /></el-icon>
        </div>
        <div class="stat-info">
          <span class="stat-value">{{ item.value }}</span>
          <span class="stat-label">{{ item.label }}</span>
        </div>
      </div>
    </div>
    <div v-if="recentActivities.length" class="activity-section">
      <h4>Recent Activity</h4>
      <div class="activity-list">
        <div v-for="(act, i) in recentActivities" :key="i" class="activity-item" @click="navigateTo(act.route)">
          <span class="activity-dot" :class="'status-' + normalizeStatus(act.status)"></span>
          <div class="activity-content">
            <span class="activity-title">{{ act.title }}</span>
            <span class="activity-meta">{{ act.module }} &middot; {{ formatTime(act.time) }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { Refresh, Document, MagicStick, VideoPlay, DataLine, Reading, Monitor } from '@element-plus/icons-vue'
import { getWorkspaceDashboard } from '@/api/core'

const router = useRouter()
const loading = ref(false)
const metrics = ref({})
const focus = ref({})
const activities = ref([])

const statCards = computed(() => [
  { label: 'Projects', value: metrics.value.project_count ?? '--', icon: Monitor, color: '#1d4ed8', bgColor: 'rgba(29,78,216,0.1)' },
  { label: 'Test Cases', value: metrics.value.generated_case_count ?? '--', icon: Document, color: '#0f766e', bgColor: 'rgba(15,118,110,0.1)' },
  { label: 'Pending Reviews', value: metrics.value.pending_review_count ?? '--', icon: Reading, color: '#b45309', bgColor: 'rgba(180,83,9,0.1)' },
  { label: 'Reports', value: metrics.value.report_count ?? '--', icon: DataLine, color: '#7c3aed', bgColor: 'rgba(124,58,237,0.1)' },
  { label: 'Active Schedules', value: metrics.value.active_schedule_count ?? '--', icon: VideoPlay, color: '#c2410c', bgColor: 'rgba(194,65,12,0.1)' },
  { label: 'AI Tasks (7d)', value: focus.value.recent_generation_count ?? '--', icon: MagicStick, color: '#0f766e', bgColor: 'rgba(15,118,110,0.1)' },
])

const recentActivities = computed(() => activities.value.slice(0, 6))

function normalizeStatus(status) {
  if (!status) return 'default'
  const s = String(status).toLowerCase()
  if (['completed', 'passed', 'active', 'healthy'].includes(s)) return 'success'
  if (['failed', 'error', 'deprecated'].includes(s)) return 'error'
  if (['in_progress', 'generating', 'writing', 'reviewing', 'revising'].includes(s)) return 'running'
  if (['pending', 'pending_clarification', 'clarified', 'not_started'].includes(s)) return 'pending'
  return 'default'
}

function formatTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  const now = new Date()
  const diffMs = now - d
  const diffMin = Math.floor(diffMs / 60000)
  if (diffMin < 1) return 'just now'
  if (diffMin < 60) return diffMin + 'm ago'
  const diffH = Math.floor(diffMin / 60)
  if (diffH < 24) return diffH + 'h ago'
  const diffD = Math.floor(diffH / 24)
  return diffD + 'd ago'
}

function navigateTo(route) {
  if (route) router.push(route)
}

async function refresh() {
  loading.value = true
  try {
    const res = await getWorkspaceDashboard()
    metrics.value = res.data.metrics || {}
    focus.value = res.data.focus || {}
    activities.value = res.data.recent_activities || []
  } catch {
    // silently fail
  } finally {
    loading.value = false
  }
}

onMounted(refresh)
</script>

<style scoped>
.dashboard-stats {
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 24px;
  background: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(12px);
  padding: 24px;
}
.stats-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
}
.stats-header h3 {
  margin: 0;
  font-size: 1.1rem;
  color: #0f172a;
}
.stats-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
  margin-bottom: 24px;
}
.stat-card {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 16px;
  border-radius: 16px;
  background: rgba(248, 250, 252, 0.8);
  border: 1px solid rgba(148, 163, 184, 0.1);
  transition: transform 0.2s, box-shadow 0.2s;
}
.stat-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 20px rgba(15, 23, 42, 0.06);
}
.stat-icon {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  font-size: 1.2rem;
  flex-shrink: 0;
}
.stat-info {
  display: flex;
  flex-direction: column;
}
.stat-value {
  font-size: 1.5rem;
  font-weight: 800;
  color: #0f172a;
  line-height: 1.2;
}
.stat-label {
  font-size: 0.82rem;
  color: #64748b;
  margin-top: 2px;
}
.activity-section h4 {
  margin: 0 0 12px;
  font-size: 0.95rem;
  color: #334155;
}
.activity-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.activity-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 10px;
  cursor: pointer;
  transition: background 0.15s;
}
.activity-item:hover {
  background: rgba(248, 250, 252, 0.8);
}
.activity-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.status-success { background: #22c55e; }
.status-error { background: #ef4444; }
.status-running { background: #3b82f6; animation: pulse 1.5s infinite; }
.status-pending { background: #f59e0b; }
.status-default { background: #94a3b8; }
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}
.activity-content {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.activity-title {
  font-size: 0.88rem;
  color: #334155;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.activity-meta {
  font-size: 0.78rem;
  color: #94a3b8;
  margin-top: 2px;
}
@media (max-width: 900px) {
  .stats-grid { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 640px) {
  .stats-grid { grid-template-columns: 1fr; }
}
</style>