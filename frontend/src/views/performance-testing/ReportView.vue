<template>
  <div class="report-page">
    <div class="page-header">
      <h2>性能报告</h2>
      <el-button :icon="Refresh" @click="loadExecutions">刷新</el-button>
    </div>

    <div class="report-layout">
      <el-card shadow="never" class="report-list">
        <el-table :data="executions" height="640" v-loading="loading" highlight-current-row @row-click="selectExecution">
          <el-table-column prop="id" label="ID" width="70" />
          <el-table-column prop="script_name" label="脚本" min-width="150" />
          <el-table-column label="错误率" width="90">
            <template #default="{ row }">{{ row.summary?.error_rate || 0 }}%</template>
          </el-table-column>
          <el-table-column label="P95" width="90">
            <template #default="{ row }">{{ row.summary?.p95_response_time || 0 }}</template>
          </el-table-column>
        </el-table>
      </el-card>

      <el-card shadow="never" class="report-detail">
        <template #header>
          <div class="detail-header">
            <span>{{ selected?.script_name || '选择一条执行记录' }}</span>
            <el-button v-if="selected?.report_url" link type="primary" @click="openReport">新窗口打开</el-button>
          </div>
        </template>

        <div v-if="selected" class="summary-grid">
          <div><span>样本</span><strong>{{ selected.summary?.total_samples || 0 }}</strong></div>
          <div><span>成功</span><strong>{{ selected.summary?.success_samples || 0 }}</strong></div>
          <div><span>失败</span><strong>{{ selected.summary?.failed_samples || 0 }}</strong></div>
          <div><span>吞吐/s</span><strong>{{ selected.summary?.throughput || 0 }}</strong></div>
          <div><span>平均(ms)</span><strong>{{ selected.summary?.avg_response_time || 0 }}</strong></div>
          <div><span>P99(ms)</span><strong>{{ selected.summary?.p99_response_time || 0 }}</strong></div>
        </div>

        <iframe v-if="selected?.report_url" :src="selected.report_url" title="JMeter Report" />
        <el-empty v-else description="暂无可查看的 JMeter HTML 报告" />
      </el-card>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { getPerformanceExecutions } from '@/api/performance-testing'

const loading = ref(false)
const executions = ref([])
const selected = ref(null)

const loadExecutions = async () => {
  loading.value = true
  try {
    const { data } = await getPerformanceExecutions({ page_size: 100 })
    executions.value = (data.results || data).filter((item) => item.report_url)
    selected.value = executions.value[0] || null
  } finally {
    loading.value = false
  }
}

const selectExecution = (row) => {
  selected.value = row
}

const openReport = () => {
  window.open(selected.value.report_url, '_blank')
}

onMounted(loadExecutions)
</script>

<style scoped lang="scss">
.report-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.page-header,
.detail-header {
  display: flex;
  justify-content: space-between;
  align-items: center;

  h2 {
    margin: 0;
  }
}

.report-layout {
  display: grid;
  grid-template-columns: 420px minmax(0, 1fr);
  gap: 16px;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 8px;
  margin-bottom: 12px;

  div {
    border: 1px solid var(--el-border-color);
    border-radius: 6px;
    padding: 8px;
  }

  span,
  strong {
    display: block;
  }

  span {
    color: var(--el-text-color-secondary);
    font-size: 12px;
  }
}

iframe {
  width: 100%;
  height: 560px;
  border: 1px solid var(--el-border-color);
  border-radius: 6px;
}
</style>
