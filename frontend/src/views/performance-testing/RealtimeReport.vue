<template>
  <div class="realtime-page">
    <div class="page-header">
      <div class="title-block">
        <el-button :icon="ArrowLeft" circle @click="goBack" />
        <div>
          <h2>{{ executionTitle }}</h2>
          <p>
            {{ report.execution?.project_name || '-' }}
            <el-tag size="small" :type="statusType(report.execution?.status)">
              {{ report.execution?.status || '-' }}
            </el-tag>
          </p>
        </div>
      </div>
      <div class="header-actions">
        <el-select v-model="windowSize" size="small" style="width: 104px">
          <el-option label="5s" value="5s" />
          <el-option label="10s" value="10s" />
          <el-option label="30s" value="30s" />
          <el-option label="1m" value="1m" />
        </el-select>
        <el-switch v-model="autoRefresh" active-text="自动刷新" />
        <el-button :icon="Refresh" :loading="loading" @click="loadReport">刷新</el-button>
      </div>
    </div>

    <el-alert
      v-if="report.error"
      type="warning"
      :title="report.error"
      show-icon
      :closable="false"
    />

    <div class="metric-grid">
      <div v-for="item in metrics" :key="item.label" class="metric-card">
        <span>{{ item.label }}</span>
        <strong>{{ item.value }}</strong>
      </div>
    </div>

    <div class="chart-grid" v-loading="loading">
      <section class="chart-panel">
        <div class="chart-title">响应时间</div>
        <div ref="responseChartRef" class="chart"></div>
      </section>
      <section class="chart-panel">
        <div class="chart-title">吞吐量</div>
        <div ref="throughputChartRef" class="chart"></div>
      </section>
      <section class="chart-panel">
        <div class="chart-title">错误率</div>
        <div ref="errorChartRef" class="chart"></div>
      </section>
      <section class="chart-panel">
        <div class="chart-title">活跃线程</div>
        <div ref="threadChartRef" class="chart"></div>
      </section>
    </div>

    <section class="table-panel">
      <div class="chart-title">事务明细</div>
      <el-table :data="report.transactions || []" height="320">
        <el-table-column prop="name" label="事务" min-width="180" show-overflow-tooltip />
        <el-table-column prop="samples" label="样本" width="100" />
        <el-table-column prop="errors" label="失败" width="100" />
        <el-table-column prop="error_rate" label="错误率(%)" width="120" />
        <el-table-column prop="throughput" label="吞吐/s" width="120" />
        <el-table-column prop="avg" label="平均(ms)" width="120" />
        <el-table-column prop="p95" label="P95(ms)" width="120" />
        <el-table-column prop="p99" label="P99(ms)" width="120" />
      </el-table>
    </section>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts'
import dayjs from 'dayjs'
import { getExecutionRealtimeReport } from '@/api/performance-testing'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const autoRefresh = ref(true)
const windowSize = ref('5s')
const report = ref({
  execution: {},
  summary: {},
  series: {
    response_time: [],
    throughput: [],
    errors: [],
    threads: [],
  },
  transactions: [],
})

const responseChartRef = ref(null)
const throughputChartRef = ref(null)
const errorChartRef = ref(null)
const threadChartRef = ref(null)
const charts = {}
let timer = null

const executionTitle = computed(() => {
  return report.value.execution?.script_name || `执行 #${route.params.id}`
})

const isRunning = computed(() => {
  return ['QUEUED', 'RUNNING'].includes(report.value.execution?.status)
})

const metrics = computed(() => {
  const summary = report.value.summary || {}
  return [
    { label: '样本', value: summary.samples ?? 0 },
    { label: '失败', value: summary.errors ?? 0 },
    { label: '错误率', value: `${summary.error_rate ?? 0}%` },
    { label: '吞吐/s', value: summary.throughput ?? 0 },
    { label: '平均(ms)', value: summary.avg_response_time ?? '-' },
    { label: 'P95(ms)', value: summary.p95_response_time ?? '-' },
    { label: '活跃线程', value: summary.active_threads ?? 0 },
  ]
})

const loadReport = async (silent = false) => {
  if (!silent) loading.value = true
  try {
    const { data } = await getExecutionRealtimeReport(route.params.id, { window: windowSize.value })
    report.value = data
    await nextTick()
    renderCharts()
    resetTimer()
    if (data.error && !silent) {
      ElMessage.warning(data.error)
    }
  } finally {
    loading.value = false
  }
}

const initCharts = () => {
  if (responseChartRef.value && !charts.response) charts.response = echarts.init(responseChartRef.value)
  if (throughputChartRef.value && !charts.throughput) charts.throughput = echarts.init(throughputChartRef.value)
  if (errorChartRef.value && !charts.error) charts.error = echarts.init(errorChartRef.value)
  if (threadChartRef.value && !charts.thread) charts.thread = echarts.init(threadChartRef.value)
}

const renderCharts = () => {
  initCharts()
  const series = report.value.series || {}
  renderResponseChart(series.response_time || [])
  renderLineChart(charts.throughput, series.throughput || [], 'throughput', '吞吐/s', '#409eff')
  renderLineChart(charts.error, series.errors || [], 'error_rate', '错误率(%)', '#f56c6c')
  renderLineChart(charts.thread, series.threads || [], 'active_threads', '活跃线程', '#67c23a')
}

const renderResponseChart = (points) => {
  const times = points.map((item) => formatTime(item.time))
  charts.response?.setOption(baseOption({
    legend: ['平均', 'P95', 'P99'],
    xAxis: times,
    series: [
      lineSeries('平均', points.map((item) => item.avg), '#409eff'),
      lineSeries('P95', points.map((item) => item.p95), '#e6a23c'),
      lineSeries('P99', points.map((item) => item.p99), '#f56c6c'),
    ],
  }))
}

const renderLineChart = (chart, points, key, name, color) => {
  chart?.setOption(baseOption({
    legend: [name],
    xAxis: points.map((item) => formatTime(item.time)),
    series: [lineSeries(name, points.map((item) => item[key]), color)],
  }))
}

const baseOption = ({ legend, xAxis, series }) => ({
  color: series.map((item) => item.itemStyle?.color).filter(Boolean),
  tooltip: { trigger: 'axis' },
  legend: { data: legend, top: 0, right: 8 },
  grid: { left: 48, right: 24, top: 42, bottom: 36 },
  xAxis: { type: 'category', boundaryGap: false, data: xAxis },
  yAxis: { type: 'value', splitLine: { lineStyle: { type: 'dashed' } } },
  series,
})

const lineSeries = (name, data, color) => ({
  name,
  type: 'line',
  smooth: true,
  showSymbol: false,
  data,
  itemStyle: { color },
  lineStyle: { width: 2 },
})

const formatTime = (value) => {
  return value ? dayjs(value).format('HH:mm:ss') : ''
}

const statusType = (status) => {
  if (status === 'COMPLETED') return 'success'
  if (status === 'RUNNING' || status === 'QUEUED') return 'warning'
  if (status === 'FAILED') return 'danger'
  return 'info'
}

const resetTimer = () => {
  clearTimer()
  if (autoRefresh.value && isRunning.value) {
    timer = window.setInterval(() => loadReport(true), 5000)
  }
}

const clearTimer = () => {
  if (timer) {
    window.clearInterval(timer)
    timer = null
  }
}

const resizeCharts = () => {
  Object.values(charts).forEach((chart) => chart?.resize())
}

const goBack = () => {
  router.push({ name: 'PerformanceExecutions' })
}

watch(autoRefresh, resetTimer)
watch(windowSize, () => loadReport())

onMounted(async () => {
  await nextTick()
  initCharts()
  await loadReport()
  window.addEventListener('resize', resizeCharts)
})

onUnmounted(() => {
  clearTimer()
  window.removeEventListener('resize', resizeCharts)
  Object.values(charts).forEach((chart) => chart?.dispose())
})
</script>

<style scoped lang="scss">
.realtime-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.page-header,
.title-block,
.header-actions {
  display: flex;
  align-items: center;
}

.page-header {
  justify-content: space-between;
  gap: 16px;
}

.title-block {
  gap: 12px;
  min-width: 0;

  h2 {
    margin: 0;
    font-size: 22px;
  }

  p {
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 4px 0 0;
    color: var(--el-text-color-secondary);
  }
}

.header-actions {
  gap: 12px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(7, minmax(120px, 1fr));
  gap: 12px;
}

.metric-card,
.chart-panel,
.table-panel {
  border: 1px solid var(--el-border-color-light);
  border-radius: 6px;
  background: var(--el-bg-color);
}

.metric-card {
  padding: 14px;

  span,
  strong {
    display: block;
  }

  span {
    color: var(--el-text-color-secondary);
    font-size: 12px;
  }

  strong {
    margin-top: 8px;
    font-size: 24px;
  }
}

.chart-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.chart-panel,
.table-panel {
  padding: 14px;
}

.chart-title {
  margin-bottom: 10px;
  font-weight: 600;
}

.chart {
  height: 300px;
}

@media (max-width: 1180px) {
  .metric-grid {
    grid-template-columns: repeat(3, minmax(120px, 1fr));
  }

  .chart-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .page-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .metric-grid {
    grid-template-columns: repeat(2, minmax(120px, 1fr));
  }
}
</style>
