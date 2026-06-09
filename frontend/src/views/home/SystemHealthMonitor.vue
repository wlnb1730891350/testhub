<template>
  <div class="health-monitor">
    <div class="health-header" @click="expanded = !expanded">
      <div class="health-badge" :class="overallClass">
        <span class="health-dot"></span>
        <span>{{ overallLabel }}</span>
      </div>
      <el-icon class="health-chevron" :class="{ rotated: expanded }"><ArrowDown /></el-icon>
    </div>
    <transition name="slide">
      <div v-if="expanded" class="health-details">
        <div v-for="svc in services" :key="svc.name" class="health-row">
          <span class="health-dot" :class="'dot-' + svc.status"></span>
          <span class="svc-name">{{ svc.name }}</span>
          <span class="svc-msg">{{ svc.message }}</span>
          <span v-if="svc.latency_ms" class="svc-latency">{{ svc.latency_ms }}ms</span>
        </div>
        <div class="health-footer">
          <span>Updated: {{ lastUpdated }}</span>
          <el-button size="small" text @click="refresh" :loading="loading">Refresh</el-button>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { ArrowDown } from '@element-plus/icons-vue'
import { getSystemHealth } from '@/api/core'

const expanded = ref(false)
const loading = ref(false)
const services = ref([])
const overall = ref('unknown')
const timestamp = ref('')
let timer = null

const overallClass = computed(() => 'badge-' + overall.value)
const overallLabel = computed(() => {
  const map = { healthy: 'All Systems OK', warning: 'Partial Issues', error: 'Service Down', unknown: 'Checking...' }
  return map[overall.value] || 'Unknown'
})
const lastUpdated = computed(() => {
  if (!timestamp.value) return '--'
  return new Date(timestamp.value).toLocaleTimeString()
})

async function refresh() {
  loading.value = true
  try {
    const res = await getSystemHealth()
    overall.value = res.data.overall || 'unknown'
    services.value = res.data.services || []
    timestamp.value = res.data.timestamp || ''
  } catch {
    overall.value = 'error'
    services.value = [{ name: 'Backend API', status: 'error', latency_ms: 0, message: 'Cannot reach server' }]
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  refresh()
  timer = setInterval(refresh, 30000)
})
onUnmounted(() => { if (timer) clearInterval(timer) })
</script>

<style scoped>
.health-monitor {
  border: 1px solid rgba(148, 163, 184, 0.2);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(12px);
  overflow: hidden;
}
.health-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 18px;
  cursor: pointer;
  user-select: none;
}
.health-badge {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 700;
  font-size: 0.9rem;
}
.health-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  display: inline-block;
  flex-shrink: 0;
}
.badge-healthy .health-dot, .dot-healthy { background: #22c55e; box-shadow: 0 0 6px rgba(34,197,94,0.5); }
.badge-warning .health-dot, .dot-warning { background: #f59e0b; box-shadow: 0 0 6px rgba(245,158,11,0.5); }
.badge-error .health-dot, .dot-error { background: #ef4444; box-shadow: 0 0 6px rgba(239,68,68,0.5); }
.badge-unknown .health-dot, .dot-unknown { background: #94a3b8; }
.badge-healthy { color: #16a34a; }
.badge-warning { color: #d97706; }
.badge-error { color: #dc2626; }
.badge-unknown { color: #64748b; }
.health-chevron {
  transition: transform 0.3s;
  color: #94a3b8;
}
.health-chevron.rotated { transform: rotate(180deg); }
.health-details {
  padding: 0 18px 14px;
  border-top: 1px solid rgba(148, 163, 184, 0.12);
}
.health-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 0;
  border-bottom: 1px solid rgba(148, 163, 184, 0.08);
  font-size: 0.88rem;
}
.health-row:last-child { border-bottom: none; }
.svc-name {
  font-weight: 600;
  color: #334155;
  min-width: 120px;
}
.svc-msg {
  color: #64748b;
  flex: 1;
}
.svc-latency {
  color: #94a3b8;
  font-size: 0.8rem;
  font-family: monospace;
}
.health-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: 10px;
  font-size: 0.78rem;
  color: #94a3b8;
}
.slide-enter-active, .slide-leave-active {
  transition: all 0.3s ease;
}
.slide-enter-from, .slide-leave-to {
  opacity: 0;
  max-height: 0;
}
.slide-enter-to, .slide-leave-from {
  max-height: 400px;
}
</style>