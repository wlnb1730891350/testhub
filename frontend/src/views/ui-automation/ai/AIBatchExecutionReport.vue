<template>
  <el-dialog
    v-model="visible"
    title="AI 批量测试报告"
    width="1080px"
    :close-on-click-modal="false"
    @open="loadReport"
  >
    <div v-if="loading" class="report-loading">正在生成批量汇总报告...</div>
    <template v-else-if="report">
      <section class="report-overview">
        <div class="overview-item">
          <span>执行方式</span>
          <strong>{{ report.batch.run_mode === 'concurrent' ? '并发执行' : '依次执行' }}</strong>
        </div>
        <div class="overview-item">
          <span>批次总耗时</span>
          <strong>{{ formatDuration(report.batch.duration) }}</strong>
        </div>
        <div class="overview-item">
          <span>通过率</span>
          <strong>{{ report.summary.completion_rate }}%</strong>
        </div>
        <div class="overview-item">
          <span>执行状态</span>
          <el-tag :type="report.batch.is_complete ? (report.summary.failed ? 'danger' : (report.summary.stopped ? 'warning' : 'success')) : 'warning'">
            {{ report.batch.is_complete ? (report.summary.failed ? '已完成，存在失败' : (report.summary.stopped ? '已完成，存在已停止任务' : '全部通过')) : '执行中' }}
          </el-tag>
        </div>
      </section>

      <section class="report-summary">
        <span>总计 {{ report.summary.total }}</span>
        <span class="success">通过 {{ report.summary.passed }}</span>
        <span class="danger">失败 {{ report.summary.failed }}</span>
        <span v-if="report.summary.stopped" class="warning">已停止 {{ report.summary.stopped }}</span>
        <span v-if="report.summary.running">执行中 {{ report.summary.running }}</span>
        <span v-if="report.summary.pending">等待中 {{ report.summary.pending }}</span>
        <span>开始时间 {{ formatDate(report.batch.started_at) }}</span>
        <span v-if="report.batch.finished_at">结束时间 {{ formatDate(report.batch.finished_at) }}</span>
      </section>

      <el-table :data="report.cases" stripe max-height="460">
        <el-table-column type="index" label="#" width="56" />
        <el-table-column prop="case_name" label="用例名称" min-width="250" show-overflow-tooltip />
        <el-table-column label="状态" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="statusTag(row.status)" size="small">{{ statusText(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="单条耗时" width="110" align="right">
          <template #default="{ row }">{{ formatDuration(row.duration) }}</template>
        </el-table-column>
        <el-table-column label="开始时间" width="170">
          <template #default="{ row }">{{ formatDate(row.start_time) }}</template>
        </el-table-column>
        <el-table-column label="失败原因" min-width="240" show-overflow-tooltip>
          <template #default="{ row }">{{ row.failure_reason || '-' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="110" fixed="right" align="center">
          <template #default="{ row }">
            <el-button size="small" link type="primary" @click="viewCaseReport(row)">
              查看报告
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </template>
    <el-empty v-else description="未获取到批量报告" />
    <template #footer>
      <el-button @click="visible = false">关闭</el-button>
    </template>
  </el-dialog>
  <AIExecutionReport
    v-model="showCaseReport"
    :record-id="selectedCaseRecordId"
  />
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { getAIBatchExecutionReport } from '@/api/ui_automation'
import AIExecutionReport from './AIExecutionReport.vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  batchId: { type: String, default: '' }
})
const emit = defineEmits(['update:modelValue'])
const visible = computed({
  get: () => props.modelValue,
  set: value => emit('update:modelValue', value)
})
const loading = ref(false)
const report = ref(null)
const showCaseReport = ref(false)
const selectedCaseRecordId = ref(null)

const loadReport = async () => {
  if (!props.batchId) return
  loading.value = true
  try {
    const response = await getAIBatchExecutionReport(props.batchId)
    report.value = response.data
  } catch (error) {
    report.value = null
    ElMessage.error(error.response?.data?.error || '获取批量报告失败')
  } finally {
    loading.value = false
  }
}

watch(() => props.batchId, () => {
  if (visible.value) loadReport()
})

const viewCaseReport = (row) => {
  selectedCaseRecordId.value = row.id
  showCaseReport.value = true
}

const formatDuration = (value) => {
  if (!Number.isFinite(value)) return '-'
  if (value < 60) return `${value.toFixed(2)}秒`
  return `${Math.floor(value / 60)}分${Math.floor(value % 60)}秒`
}

const formatDate = (value) => value ? new Date(value).toLocaleString() : '-'
const statusTag = status => ({ passed: 'success', failed: 'danger', error: 'danger', stopped: 'warning', running: 'warning', pending: 'info' }[status] || 'info')
const statusText = status => ({ passed: '通过', failed: '失败', error: '异常', stopped: '已停止', running: '执行中', pending: '等待中' }[status] || status)
</script>

<style scoped>
.report-loading { padding: 40px 0; text-align: center; color: #909399; }
.report-overview { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 14px; }
.overview-item { padding: 12px; border: 1px solid #e4e7ed; background: #fafafa; }
.overview-item span { display: block; color: #909399; font-size: 12px; margin-bottom: 6px; }
.overview-item strong { font-size: 16px; color: #303133; }
.report-summary { display: flex; flex-wrap: wrap; gap: 14px; margin: 0 0 14px; color: #606266; font-size: 13px; }
.success { color: #67c23a; }
.danger { color: #f56c6c; }
</style>
