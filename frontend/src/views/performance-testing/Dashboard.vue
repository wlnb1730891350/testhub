<template>
  <div class="perf-page">
    <div class="page-header">
      <div>
        <h2>性能测试</h2>
        <p>JMeter 脚本编排、执行与结果回收</p>
      </div>
      <el-button :icon="Refresh" @click="loadData">刷新</el-button>
    </div>

    <div class="metric-grid">
      <el-card v-for="item in metrics" :key="item.label" shadow="never">
        <span>{{ item.label }}</span>
        <strong>{{ item.value }}</strong>
      </el-card>
    </div>

    <el-card shadow="never">
      <template #header>最近执行</template>
      <el-table :data="latestExecutions" v-loading="loading">
        <el-table-column prop="id" label="ID" width="80" />
        <el-table-column prop="script_name" label="脚本" min-width="180" />
        <el-table-column prop="project_name" label="项目" min-width="160" />
        <el-table-column prop="status" label="状态" width="120">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="样本/错误率" min-width="150">
          <template #default="{ row }">
            {{ row.summary?.total_samples || 0 }} / {{ row.summary?.error_rate || 0 }}%
          </template>
        </el-table-column>
        <el-table-column label="P95(ms)" width="110">
          <template #default="{ row }">{{ row.summary?.p95_response_time || 0 }}</template>
        </el-table-column>
        <el-table-column label="创建时间" min-width="180">
          <template #default="{ row }">
            {{ formatDate(row.created_at) }}
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import dayjs from 'dayjs'
import { getPerformanceStats } from '@/api/performance-testing'

const loading = ref(false)
const stats = ref({})

const metrics = computed(() => [
  { label: '项目数', value: stats.value.project_count || 0 },
  { label: '脚本数', value: stats.value.script_count || 0 },
  { label: '执行次数', value: stats.value.execution_count || 0 },
  { label: '运行中', value: stats.value.running_count || 0 },
])

const latestExecutions = computed(() => stats.value.latest_executions || [])

const statusType = (status) => {
  if (status === 'COMPLETED') return 'success'
  if (status === 'RUNNING' || status === 'QUEUED') return 'warning'
  if (status === 'FAILED') return 'danger'
  return 'info'
}

const formatDate = (dateString) => {
  return dateString ? dayjs(dateString).format('YYYY-MM-DD HH:mm') : '-'
}

const loadData = async () => {
  loading.value = true
  try {
    const statsRes = await getPerformanceStats()
    stats.value = statsRes.data
  } finally {
    loading.value = false
  }
}

onMounted(loadData)
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
    margin: 0 0 6px;
  }

  p {
    margin: 0;
    color: var(--el-text-color-secondary);
  }
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;

  :deep(.el-card__body) {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  strong {
    font-size: 28px;
  }
}
</style>
