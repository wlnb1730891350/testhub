<template>
  <div class="report-center page-container">
    <header class="page-header">
      <h1>{{ copy.title }}</h1>
      <el-button :loading="loading" @click="loadReports">{{ copy.refresh }}</el-button>
    </header>

    <section class="report-summary card-container">
      <div class="section-header">
        <div>
          <h2>{{ copy.summaryTitle }}</h2>
        </div>
        <span v-if="loading">{{ copy.loading }}</span>
        <span v-else-if="loadError">{{ copy.loadError }}</span>
      </div>

      <div class="summary-grid">
        <article v-for="item in channels" :key="item.key" class="summary-card" @click="go(item.route)">
          <span>{{ item.label }}</span>
          <strong>{{ item.count }}</strong>
        </article>
      </div>
    </section>

    <section class="report-activity card-container">
      <div class="section-header">
        <div>
          <h2>{{ copy.activityTitle }}</h2>
        </div>
      </div>

      <div v-if="recentReports.length" class="activity-grid">
        <article v-for="item in recentReports" :key="`${item.type}-${item.id}`" class="activity-card">
          <div class="activity-card__meta">
            <span>{{ item.module }}</span>
            <el-tag size="small" :type="statusType(item.status)">{{ formatStatus(item.status) }}</el-tag>
          </div>
          <h3>{{ item.title }}</h3>
          <p>{{ formatTime(item.created_at) }}</p>
          <div class="activity-card__stats" v-if="item.total !== undefined">
            <span>{{ copy.totalLabel }} {{ item.total }}</span>
            <span>{{ copy.passLabel }} {{ item.passed ?? 0 }}</span>
            <span>{{ copy.failLabel }} {{ item.failed ?? 0 }}</span>
          </div>
          <el-button text type="primary" @click="go(item.route)">{{ copy.openChannel }}</el-button>
        </article>
      </div>

      <div v-else class="empty-state">{{ copy.empty }}</div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import dayjs from 'dayjs'
import { useAppStore } from '@/stores/app'
import { getUnifiedReportCenter } from '@/api/core'

const router = useRouter()
const appStore = useAppStore()
const loading = ref(false)
const loadError = ref(false)
const reportData = ref(null)

const isChinese = computed(() => appStore.language === 'zh-cn')

const copy = computed(() =>
  isChinese.value
    ? {
        title: '统一报告中心',
        refresh: '刷新',
        summaryTitle: '报告通道总览',
        activityTitle: '最近结果与执行动态',
        loading: '正在加载报告汇总',
        loadError: '汇总加载失败，稍后重试',
        totalLabel: '总数',
        passLabel: '通过',
        failLabel: '失败',
        openChannel: '进入对应模块',
        empty: '当前暂无可展示的报告动态。'
      }
    : {
        title: 'Unified Report Center',
        refresh: 'Refresh',
        summaryTitle: 'Reporting channels overview',
        activityTitle: 'Latest results and execution activity',
        loading: 'Loading report aggregation',
        loadError: 'Aggregation failed to load',
        totalLabel: 'Total',
        passLabel: 'Passed',
        failLabel: 'Failed',
        openChannel: 'Open channel',
        empty: 'No reporting activity is available yet.'
      }
)

const channels = computed(() => reportData.value?.channels ?? [])
const recentReports = computed(() => reportData.value?.recent_reports ?? [])

const loadReports = async () => {
  loading.value = true
  loadError.value = false
  try {
    const response = await getUnifiedReportCenter()
    reportData.value = response.data
  } catch (error) {
    console.error('Failed to load unified report center:', error)
    loadError.value = true
  } finally {
    loading.value = false
  }
}

const formatTime = (value) => (value ? dayjs(value).format('YYYY-MM-DD HH:mm') : '')

const formatStatus = (value) => {
  const map = isChinese.value
    ? {
        execution: '执行报告',
        summary: '汇总报告',
        trend: '趋势报告',
        completed: '已完成',
        failed: '失败',
        in_progress: '进行中',
        PENDING: '待执行',
        RUNNING: '执行中',
        COMPLETED: '已完成',
        FAILED: '失败',
        pending: '待处理',
        reviewing: '评审中'
      }
    : {
        execution: 'Execution report',
        summary: 'Summary report',
        trend: 'Trend report',
        completed: 'Completed',
        failed: 'Failed',
        in_progress: 'In Progress',
        PENDING: 'Pending',
        RUNNING: 'Running',
        COMPLETED: 'Completed',
        FAILED: 'Failed',
        pending: 'Pending',
        reviewing: 'Reviewing'
      }
  return map[value] || value
}

const statusType = (value) => {
  if (['COMPLETED', 'completed', 'execution', 'summary', 'trend'].includes(value)) return 'success'
  if (['FAILED', 'failed'].includes(value)) return 'danger'
  if (['RUNNING', 'in_progress', 'reviewing'].includes(value)) return 'warning'
  return 'info'
}

const go = (path) => {
  router.push(path)
}

onMounted(() => {
  loadReports()
})
</script>

<style scoped lang="scss">
.report-center {
  gap: 16px;
}

.card-container {
  border: 1px solid #dfe3e8;
  border-radius: 6px;
  background: #ffffff;
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 2px 0;
}

.page-header h1,
.section-header h2,
.activity-card h3 {
  margin: 0;
  color: #0f172a;
}

.activity-card p {
  margin: 14px 0 0;
  color: #475569;
  line-height: 1.7;
}

.card-container {
  padding: 18px;
}

.section-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}

.section-header span {
  color: #64748b;
}

.summary-grid,
.activity-grid {
  display: grid;
  gap: 10px;
}

.summary-grid {
  grid-template-columns: repeat(5, minmax(0, 1fr));
}

.activity-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.summary-card,
.activity-card {
  border: 1px solid #e5e7eb;
  border-radius: 4px;
  background: #ffffff;
}

.summary-card {
  padding: 20px;
  cursor: pointer;
  transition: background 0.15s ease;
}

.summary-card:hover,
.activity-card:hover {
  background: #f8fafc;
}

.summary-card span,
.activity-card__meta span {
  color: #64748b;
  font-size: 0.84rem;
}

.summary-card strong {
  display: block;
  margin-top: 10px;
  color: #0f172a;
  font-size: 1.6rem;
}

.activity-card {
  padding: 18px;
}

.activity-card__meta,
.activity-card__stats {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.activity-card__stats {
  margin-top: 14px;
  color: #334155;
  font-size: 0.88rem;
}

.empty-state {
  padding: 18px;
  border-radius: 4px;
  background: #f8fafc;
  color: #64748b;
}

@media (max-width: 1200px) {
  .summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 900px) {
  .activity-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .card-container {
    padding: 14px;
  }

  .summary-grid,
  .activity-grid {
    grid-template-columns: 1fr;
  }
}
</style>
