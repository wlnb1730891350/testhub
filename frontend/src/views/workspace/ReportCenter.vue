<template>
  <div class="report-center page-container">
    <section class="report-hero">
      <div>
        <p class="hero-kicker">{{ copy.kicker }}</p>
        <h1>{{ copy.title }}</h1>
        <p>{{ copy.description }}</p>
      </div>
      <div class="hero-actions">
        <el-button type="primary" size="large" @click="go('/workspace/command-center')">
          {{ copy.backAction }}
        </el-button>
      </div>
    </section>

    <section class="report-summary card-container">
      <div class="section-header">
        <div>
          <p>{{ copy.summaryEyebrow }}</p>
          <h2>{{ copy.summaryTitle }}</h2>
        </div>
        <span v-if="loading">{{ copy.loading }}</span>
        <span v-else-if="loadError">{{ copy.loadError }}</span>
      </div>

      <div class="summary-grid">
        <article v-for="item in channels" :key="item.key" class="summary-card" @click="go(item.route)">
          <span>{{ item.label }}</span>
          <strong>{{ item.count }}</strong>
          <p>{{ channelDescription(item.key) }}</p>
        </article>
      </div>
    </section>

    <section class="report-activity card-container">
      <div class="section-header">
        <div>
          <p>{{ copy.activityEyebrow }}</p>
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
        kicker: 'Unified Reporting',
        title: '统一报告中心',
        description: '从平台层统一查看 API、UI、APP 和手工执行结果，再进入各模块做深入排查和分析。',
        backAction: '返回平台工作台',
        summaryEyebrow: 'Summary',
        summaryTitle: '报告通道总览',
        activityEyebrow: 'Recent Reports',
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
        kicker: 'Unified Reporting',
        title: 'Unified Report Center',
        description: 'View API, UI, APP and manual execution outcomes in one place, then jump into each module for deeper analysis.',
        backAction: 'Back to command center',
        summaryEyebrow: 'Summary',
        summaryTitle: 'Reporting channels overview',
        activityEyebrow: 'Recent Reports',
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

const channelDescription = (key) => {
  const descriptions = isChinese.value
    ? {
        manual: '手工/通用测试报告沉淀',
        api: '接口测试执行与 Allure 输出',
        ui: 'UI 自动化执行报告',
        app: 'APP 自动化执行结果',
        execution: '手工执行计划与进度'
      }
    : {
        manual: 'Manual and general testing reports',
        api: 'API executions and Allure output',
        ui: 'UI automation reporting',
        app: 'APP automation results',
        execution: 'Manual execution plans and progress'
      }
  return descriptions[key] || key
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
  gap: 24px;
}

.report-hero,
.card-container {
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 28px;
  background:
    radial-gradient(circle at top left, rgba(56, 189, 248, 0.14), transparent 28%),
    radial-gradient(circle at bottom right, rgba(20, 184, 166, 0.14), transparent 32%),
    linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(248, 250, 252, 0.92));
  box-shadow: 0 24px 70px rgba(15, 23, 42, 0.08);
}

.report-hero {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 18px;
  padding: 28px;
}

.hero-kicker,
.section-header p {
  margin: 0 0 10px;
  color: #0f766e;
  font-size: 0.8rem;
  font-weight: 700;
  letter-spacing: 0.16em;
  text-transform: uppercase;
}

.report-hero h1,
.section-header h2,
.activity-card h3 {
  margin: 0;
  color: #0f172a;
}

.report-hero p:last-child,
.activity-card p {
  margin: 14px 0 0;
  color: #475569;
  line-height: 1.7;
}

.card-container {
  padding: 26px;
}

.section-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 22px;
}

.section-header span {
  color: #64748b;
}

.summary-grid,
.activity-grid {
  display: grid;
  gap: 18px;
}

.summary-grid {
  grid-template-columns: repeat(5, minmax(0, 1fr));
}

.activity-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.summary-card,
.activity-card {
  border: 1px solid rgba(148, 163, 184, 0.14);
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.84);
}

.summary-card {
  padding: 20px;
  cursor: pointer;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.summary-card:hover,
.activity-card:hover {
  transform: translateY(-3px);
  box-shadow: 0 18px 36px rgba(15, 23, 42, 0.08);
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

.summary-card p {
  margin: 10px 0 0;
  color: #475569;
  line-height: 1.6;
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
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.76);
  color: #64748b;
}

@media (max-width: 1200px) {
  .summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 900px) {
  .report-hero,
  .activity-grid {
    grid-template-columns: 1fr;
  }

  .report-hero {
    flex-direction: column;
    align-items: flex-start;
  }
}

@media (max-width: 640px) {
  .report-hero,
  .card-container {
    padding: 18px;
    border-radius: 22px;
  }

  .summary-grid,
  .activity-grid {
    grid-template-columns: 1fr;
  }
}
</style>
