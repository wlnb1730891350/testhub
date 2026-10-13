<template>
  <div class="scheduler-center page-container">
    <header class="page-header">
      <h1>{{ copy.title }}</h1>
      <el-button :loading="loading" @click="loadSchedulerCenter">{{ copy.refresh }}</el-button>
    </header>

    <section class="card-container">
      <div class="section-header">
        <div>
          <h2>{{ copy.summaryTitle }}</h2>
        </div>
        <span v-if="loading">{{ copy.loading }}</span>
        <span v-else-if="loadError">{{ copy.loadError }}</span>
      </div>

      <div class="summary-grid">
        <article v-for="item in summaryCards" :key="item.key" class="summary-card">
          <span>{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
        </article>
      </div>
    </section>

    <section class="card-container">
      <div class="section-header">
        <div>
          <h2>{{ copy.channelTitle }}</h2>
        </div>
      </div>

      <div class="channel-grid">
        <article
          v-for="item in channels"
          :key="item.key"
          class="channel-card"
          role="button"
          tabindex="0"
          @click="go(item.route)"
          @keyup.enter="go(item.route)"
        >
          <div class="channel-card__meta">
            <span>{{ item.label }}</span>
            <el-tag size="small" type="success">{{ activeLabel(item.active_count) }}</el-tag>
          </div>
          <strong>{{ item.count }}</strong>
          <p>{{ channelDescription(item) }}</p>
          <el-button text type="primary">{{ copy.openChannel }}</el-button>
        </article>
      </div>
    </section>

    <section class="card-container">
      <div class="section-header">
        <div>
          <h2>{{ copy.activityTitle }}</h2>
        </div>
      </div>

      <div v-if="recentTasks.length" class="task-grid">
        <article v-for="item in recentTasks" :key="`${item.module}-${item.id}`" class="task-card">
          <div class="task-card__meta">
            <span>{{ item.module }}</span>
            <el-tag size="small" :type="statusType(item.status)">{{ formatStatus(item.status) }}</el-tag>
          </div>
          <h3>{{ item.name }}</h3>
          <div class="task-card__times">
            <p>{{ copy.nextRunLabel }} {{ formatTime(item.next_run_time) || copy.notScheduled }}</p>
            <p>{{ copy.lastRunLabel }} {{ formatTime(item.last_run_time) || copy.neverRun }}</p>
          </div>
          <div class="task-card__stats">
            <span>{{ copy.runCountLabel }} {{ item.total_runs ?? 0 }}</span>
            <span>{{ copy.passLabel }} {{ item.successful_runs ?? 0 }}</span>
            <span>{{ copy.failLabel }} {{ item.failed_runs ?? 0 }}</span>
          </div>
          <el-button text type="primary" @click="go(item.route)">{{ copy.openTask }}</el-button>
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
import { getUnifiedSchedulerCenter } from '@/api/core'

const router = useRouter()
const appStore = useAppStore()
const loading = ref(false)
const loadError = ref(false)
const schedulerData = ref(null)

const isChinese = computed(() => appStore.language === 'zh-cn')

const copy = computed(() =>
  isChinese.value
    ? {
        title: '统一调度中心',
        refresh: '刷新',
        summaryTitle: '调度全景',
        channelTitle: '模块调度入口',
        activityTitle: '最近调度任务',
        loading: '正在加载调度汇总',
        loadError: '调度汇总加载失败，请稍后重试',
        openChannel: '进入模块',
        openTask: '查看任务列表',
        nextRunLabel: '下次运行',
        lastRunLabel: '最近运行',
        runCountLabel: '累计执行',
        passLabel: '成功',
        failLabel: '失败',
        notScheduled: '未设置',
        neverRun: '尚未执行',
        empty: '当前还没有可展示的调度任务。'
      }
    : {
        title: 'Unified Scheduler Center',
        refresh: 'Refresh',
        summaryTitle: 'Scheduling overview',
        channelTitle: 'Module scheduling entry points',
        activityTitle: 'Latest scheduled tasks',
        loading: 'Loading scheduler aggregation',
        loadError: 'Failed to load scheduler aggregation',
        openChannel: 'Open channel',
        openTask: 'View task list',
        nextRunLabel: 'Next run',
        lastRunLabel: 'Last run',
        runCountLabel: 'Runs',
        passLabel: 'Passed',
        failLabel: 'Failed',
        notScheduled: 'Not scheduled',
        neverRun: 'Never ran',
        empty: 'No scheduled tasks are available yet.'
      }
)

const channels = computed(() => schedulerData.value?.channels ?? [])
const recentTasks = computed(() => schedulerData.value?.recent_tasks ?? [])

const summaryCards = computed(() => {
  const summary = schedulerData.value?.summary ?? {}
  return isChinese.value
    ? [
        {
          key: 'total',
          label: '任务总数',
          value: summary.total_tasks ?? 0
        },
        {
          key: 'active',
          label: '运行中任务',
          value: summary.active_tasks ?? 0
        },
        {
          key: 'paused',
          label: '暂停任务',
          value: summary.paused_tasks ?? 0
        },
        {
          key: 'failed',
          label: '失败任务',
          value: summary.failed_tasks ?? 0
        }
      ]
    : [
        {
          key: 'total',
          label: 'Total tasks',
          value: summary.total_tasks ?? 0
        },
        {
          key: 'active',
          label: 'Active tasks',
          value: summary.active_tasks ?? 0
        },
        {
          key: 'paused',
          label: 'Paused tasks',
          value: summary.paused_tasks ?? 0
        },
        {
          key: 'failed',
          label: 'Failed tasks',
          value: summary.failed_tasks ?? 0
        }
      ]
})

const loadSchedulerCenter = async () => {
  loading.value = true
  loadError.value = false

  try {
    const response = await getUnifiedSchedulerCenter()
    schedulerData.value = response.data
  } catch (error) {
    console.error('Failed to load unified scheduler center:', error)
    loadError.value = true
  } finally {
    loading.value = false
  }
}

const activeLabel = (count) => {
  if (isChinese.value) return `运行中 ${count ?? 0}`
  return `${count ?? 0} active`
}

const channelDescription = (item) => {
  if (isChinese.value) {
    return `共 ${item.count ?? 0} 个任务，其中 ${item.active_count ?? 0} 个正在运行`
  }
  return `${item.count ?? 0} total tasks with ${item.active_count ?? 0} currently active`
}

const formatTime = value => (value ? dayjs(value).format('YYYY-MM-DD HH:mm') : '')

const formatStatus = value => {
  const map = isChinese.value
    ? {
        ACTIVE: '运行中',
        PAUSED: '已暂停',
        FAILED: '失败',
        COMPLETED: '已完成',
        PENDING: '待执行',
        RUNNING: '执行中'
      }
    : {
        ACTIVE: 'Active',
        PAUSED: 'Paused',
        FAILED: 'Failed',
        COMPLETED: 'Completed',
        PENDING: 'Pending',
        RUNNING: 'Running'
      }

  return map[value] || value || (isChinese.value ? '未知' : 'Unknown')
}

const statusType = value => {
  if (['ACTIVE', 'RUNNING', 'COMPLETED'].includes(value)) return 'success'
  if (value === 'PAUSED') return 'warning'
  if (value === 'FAILED') return 'danger'
  return 'info'
}

const go = path => {
  router.push(path)
}

onMounted(() => {
  loadSchedulerCenter()
})
</script>

<style scoped lang="scss">
.scheduler-center {
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
.task-card h3 {
  margin: 0;
  color: #0f172a;
}

.task-card p {
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
.channel-grid,
.task-grid {
  display: grid;
  gap: 10px;
}

.summary-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.channel-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.task-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.summary-card,
.channel-card,
.task-card {
  border: 1px solid #e5e7eb;
  border-radius: 4px;
  background: #ffffff;
}

.summary-card,
.channel-card,
.task-card {
  padding: 20px;
}

.channel-card,
.task-card {
  transition: background 0.15s ease, border-color 0.15s ease;
}

.channel-card {
  cursor: pointer;
}

.channel-card:hover,
.channel-card:focus-visible,
.task-card:hover {
  border-color: #93c5fd;
  background: #f8fafc;
  outline: none;
}

.summary-card span,
.channel-card__meta span,
.task-card__meta span {
  color: #64748b;
  font-size: 0.84rem;
}

.summary-card strong,
.channel-card strong {
  display: block;
  margin-top: 10px;
  color: #0f172a;
  font-size: 1.6rem;
}

.channel-card p {
  margin: 10px 0 0;
  color: #475569;
  line-height: 1.6;
}

.channel-card__meta,
.task-card__meta,
.task-card__stats {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.task-card__times {
  margin-top: 14px;
}

.task-card__times p {
  margin: 0;
}

.task-card__times p + p,
.task-card__stats {
  margin-top: 10px;
}

.task-card__stats {
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
  .summary-grid,
  .channel-grid,
  .task-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 900px) {
}

@media (max-width: 640px) {
  .card-container {
    padding: 14px;
  }

  .summary-grid,
  .channel-grid,
  .task-grid {
    grid-template-columns: 1fr;
  }
}
</style>
