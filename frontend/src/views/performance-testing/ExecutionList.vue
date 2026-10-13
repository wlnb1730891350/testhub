<template>
  <div class="perf-page">
    <div class="page-header">
      <h2>执行记录</h2>
      <el-button :icon="Refresh" @click="loadExecutions">刷新</el-button>
    </div>

    <el-table :data="executions" v-loading="loading">
      <el-table-column prop="id" label="ID" width="80" />
      <el-table-column prop="script_name" label="脚本" min-width="180" />
      <el-table-column prop="project_name" label="项目" min-width="150" />
      <el-table-column prop="status" label="状态" width="120">
        <template #default="{ row }">
          <el-tag :type="statusType(row.status)">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="样本" width="90">
        <template #default="{ row }">{{ row.summary?.total_samples || 0 }}</template>
      </el-table-column>
      <el-table-column label="错误率" width="100">
        <template #default="{ row }">{{ row.summary?.error_rate || 0 }}%</template>
      </el-table-column>
      <el-table-column label="平均/P95" width="140">
        <template #default="{ row }">
          {{ row.summary?.avg_response_time || 0 }} / {{ row.summary?.p95_response_time || 0 }}
        </template>
      </el-table-column>
      <el-table-column prop="duration" label="耗时(s)" width="100" />
      <el-table-column label="创建时间" min-width="180">
        <template #default="{ row }">
          {{ formatDate(row.created_at) }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="310" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" :disabled="!row.report_url" @click="openReport(row)">报告</el-button>
          <el-button link type="success" :disabled="!row.realtime_report_url" @click="openRealtimeReport(row)">
            实时
          </el-button>
          <el-button link @click="downloadJmx(row)">JMX</el-button>
          <el-button link @click="downloadJtl(row)">JTL</el-button>
          <el-button v-if="['QUEUED', 'RUNNING'].includes(row.status)" link type="danger" @click="stopRun(row)">
            停止
          </el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import dayjs from 'dayjs'
import {
  downloadExecutionJmx,
  downloadExecutionJtl,
  getPerformanceExecutions,
  stopPerformanceExecution,
} from '@/api/performance-testing'

const loading = ref(false)
const executions = ref([])
const router = useRouter()

const loadExecutions = async () => {
  loading.value = true
  try {
    const { data } = await getPerformanceExecutions({ page_size: 100 })
    executions.value = data.results || data
  } finally {
    loading.value = false
  }
}

const statusType = (status) => {
  if (status === 'COMPLETED') return 'success'
  if (status === 'RUNNING' || status === 'QUEUED') return 'warning'
  if (status === 'FAILED') return 'danger'
  return 'info'
}

const formatDate = (dateString) => {
  return dateString ? dayjs(dateString).format('YYYY-MM-DD HH:mm') : '-'
}

const openReport = (row) => {
  window.open(row.report_url, '_blank')
}

const openRealtimeReport = (row) => {
  router.push({ name: 'PerformanceRealtimeReport', params: { id: row.id } })
}

const downloadJmx = async (row) => {
  const { data } = await downloadExecutionJmx(row.id)
  downloadBlob(data, `performance_execution_${row.id}.jmx`)
}

const downloadJtl = async (row) => {
  const { data } = await downloadExecutionJtl(row.id)
  downloadBlob(data, `performance_execution_${row.id}.jtl`)
}

const stopRun = async (row) => {
  await stopPerformanceExecution(row.id)
  ElMessage.success('停止请求已提交')
  await loadExecutions()
}

const downloadBlob = (blob, filename) => {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}

onMounted(loadExecutions)
</script>

<style scoped lang="scss">
.perf-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;

  h2 {
    margin: 0;
  }
}
</style>
