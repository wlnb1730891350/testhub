<template>
  <div class="page-container">
    <div class="page-header">
      <h1 class="page-title">{{ $t('uiAutomation.ai.executionRecords.title') }}</h1>
      <div class="header-actions">
        <el-button
          type="danger"
          :disabled="selectedRecords.length === 0"
          @click="batchDeleteRecords"
          :loading="isDeleting"
        >
          <el-icon><Delete /></el-icon>
          {{ $t('uiAutomation.common.batchDelete') }}
        </el-button>
      </div>
    </div>

    <div class="card-container">
      <el-table
        :data="records"
        v-loading="loading"
        style="width: 100%"
        @selection-change="handleSelectionChange"
        ref="tableRef"
      >
        <el-table-column type="selection" width="55" />
        <el-table-column :label="$t('uiAutomation.ai.executionRecords.serialNumber')" width="80">
          <template #default="{ $index }">
            {{ getSerialNumber($index) }}
          </template>
        </el-table-column>
        <el-table-column prop="case_name" :label="$t('uiAutomation.ai.executionRecords.caseName')" min-width="240" show-overflow-tooltip>
          <template #default="{ row }">
            <span>{{ row.case_name }}</span>
            <el-tag v-if="row.item_type === 'batch'" size="small" type="info" class="batch-count-tag">
              {{ row.case_count }} 条
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column prop="status" :label="$t('uiAutomation.ai.executionRecords.status')" width="120">
          <template #default="{ row }">
            <el-tag :type="getStatusTag(row.status)">
              {{ getStatusText(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="duration" :label="$t('uiAutomation.ai.executionRecords.durationSeconds')" width="120">
          <template #default="{ row }">
            {{ row.duration ? row.duration.toFixed(2) : '-' }}
          </template>
        </el-table-column>
        <el-table-column prop="start_time" :label="$t('uiAutomation.ai.executionRecords.startTime')" width="180" :formatter="formatDate" />
        <el-table-column prop="executed_by_name" :label="$t('uiAutomation.ai.executionRecords.executor')" width="120" />
        <el-table-column :label="$t('uiAutomation.common.operation')" width="200" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.item_type !== 'batch'" size="small" @click="viewDetail(row)">
              {{ $t('uiAutomation.ai.executionRecords.viewDetail') }}
            </el-button>
            <el-button size="small" type="success" @click="viewReport(row)">
              {{ row.item_type === 'batch' ? '批次报告' : $t('uiAutomation.ai.executionRecords.viewReport') }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination-container">
        <el-pagination
          v-model:current-page="pagination.currentPage"
          v-model:page-size="pagination.pageSize"
          :page-sizes="[10, 20, 50, 100]"
          layout="total, sizes, prev, pager, next, jumper"
          :total="total"
          @size-change="handleSizeChange"
          @current-change="handleCurrentChange"
        />
      </div>
    </div>

    <!-- 详情对话框 -->
    <el-dialog v-model="showDetailDialog" :title="$t('uiAutomation.ai.executionRecords.executionDetail')" width="800px">
      <div v-if="currentRecord" class="record-detail">
        <div class="detail-item">
          <span class="label">{{ $t('uiAutomation.ai.executionRecords.caseName') }}:</span>
          <span class="value">{{ currentRecord.case_name }}</span>
        </div>

        <div class="detail-item">
          <span class="label">{{ $t('uiAutomation.ai.executionRecords.status') }}:</span>
          <el-tag :type="getStatusTag(currentRecord.status)">
            {{ getStatusText(currentRecord.status) }}
          </el-tag>
        </div>
        <div class="detail-item">
          <span class="label">{{ $t('uiAutomation.ai.executionRecords.startTime') }}:</span>
          <span>{{ formatDate(null, null, currentRecord.start_time) }}</span>
        </div>
        <div class="detail-item">
          <span class="label">{{ $t('uiAutomation.ai.executionRecords.duration') }}:</span>
          <span>{{ currentRecord.duration ? currentRecord.duration.toFixed(2) + ' ' + $t('uiAutomation.ai.executionRecords.seconds') : $t('uiAutomation.ai.executionRecords.unknown') }}</span>
        </div>
        <div v-if="currentRecord.cleanup_results" class="detail-item">
          <span class="label">环境回收:</span>
          <el-tag :type="currentRecord.cleanup_results.failed_count ? 'danger' : 'success'">
            {{ currentRecord.cleanup_results.required
              ? (currentRecord.cleanup_results.failed_count ? `失败 ${currentRecord.cleanup_results.failed_count} 项` : `已回收 ${currentRecord.cleanup_results.completed_count} 项`)
              : '无需回收' }}
          </el-tag>
        </div>

        <div class="detail-item">
          <span class="label">GIF录制:</span>
          <el-button v-if="currentRecord.gif_path" type="primary" size="small" @click="showDetailGifDialog = true">
            查看GIF
          </el-button>
          <el-tag v-else type="info">本次未生成GIF</el-tag>
        </div>

        <!-- 任务描述 -->
        <div v-if="currentRecord.task_description" class="detail-item mt-15">
          <span class="label">{{ $t('uiAutomation.ai.executionRecords.taskDescription') }}:</span>
        </div>
        <div v-if="currentRecord.task_description" class="task-description-container">
          <div class="task-description-content">{{ currentRecord.task_description }}</div>
        </div>

        <!-- 执行日志 -->
        <div class="detail-item mt-15">
          <span class="label">{{ $t('uiAutomation.ai.executionRecords.executionLogs') }}:</span>
        </div>
        <div class="log-container">
          <pre>{{ currentRecord.logs }}</pre>
        </div>
      </div>

      <template #footer>
        <div class="dialog-footer">
          <el-button type="success" @click="openReportFromDetail">{{ $t('uiAutomation.ai.executionRecords.viewReport') }}</el-button>
          <el-button @click="showDetailDialog = false">{{ $t('uiAutomation.common.close') }}</el-button>
        </div>
      </template>
    </el-dialog>

    <!-- 报告对话框 -->
    <AIExecutionReport
      v-model="showReportDialog"
      :record-id="reportRecordId"
    />
    <AIBatchExecutionReport
      v-model="showBatchReportDialog"
      :batch-id="reportBatchId"
    />

    <el-dialog v-model="showDetailGifDialog" title="GIF回放" width="800px" append-to-body>
      <div v-if="currentRecord && currentRecord.gif_path" class="gif-container">
        <img :src="getGifUrl(currentRecord.gif_path)" alt="Execution GIF" class="gif-image" />
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete } from '@element-plus/icons-vue'
import { getAIExecutionReportList, batchDeleteAIExecutionRecords } from '@/api/ui_automation'
import AIExecutionReport from './AIExecutionReport.vue'
import AIBatchExecutionReport from './AIBatchExecutionReport.vue'

const { t } = useI18n()
const records = ref([])
const loading = ref(false)
const total = ref(0)
const pagination = reactive({
  currentPage: 1,
  pageSize: 20
})

const showDetailDialog = ref(false)
const showDetailGifDialog = ref(false)
const currentRecord = ref(null)
let pollTimer = null

const selectedRecords = ref([])
const isDeleting = ref(false)
const tableRef = ref(null)

// 报告相关状态
const showReportDialog = ref(false)
const reportRecordId = ref(null)
const showBatchReportDialog = ref(false)
const reportBatchId = ref('')

// 加载记录列表
const loadRecords = async () => {
  loading.value = true
  try {
    const response = await getAIExecutionReportList({
      page: pagination.currentPage,
      page_size: pagination.pageSize
    })

    records.value = response.data.results || []
    total.value = response.data.count || 0
    // 清空选择
    if (tableRef.value) {
      tableRef.value.clearSelection()
    }
  } catch (error) {
    console.error('获取执行记录失败:', error)
    ElMessage.error(t('uiAutomation.ai.executionRecords.messages.loadFailed'))
  } finally {
    loading.value = false
  }
}

const handleSizeChange = () => {
  pagination.currentPage = 1
  loadRecords()
}

const handleCurrentChange = () => {
  loadRecords()
}

const viewDetail = (row) => {
  currentRecord.value = row
  showDetailDialog.value = true
}

// 查看报告
const viewReport = (row) => {
  if (row.item_type === 'batch') {
    reportBatchId.value = String(row.batch_id)
    showBatchReportDialog.value = true
    return
  }
  reportRecordId.value = row.id
  showReportDialog.value = true
}

// 从详情页打开报告
const openReportFromDetail = () => {
  if (currentRecord.value) {
    viewReport(currentRecord.value)
  }
}

const getStatusTag = (status) => {
  const map = {
    'pending': 'info',
    'running': 'warning',
    'passed': 'success',
    'failed': 'danger',
    'stopped': 'warning'
  }
  return map[status] || 'info'
}

const getStatusText = (status) => {
  const map = {
    'pending': t('uiAutomation.status.pending'),
    'running': t('uiAutomation.status.running'),
    'passed': t('uiAutomation.status.success'),
    'failed': t('uiAutomation.status.failed'),
    'stopped': t('uiAutomation.status.stopped')
  }
  return map[status] || status
}

const formatDate = (row, column, cellValue) => {
  if (!cellValue) return ''
  return new Date(cellValue).toLocaleString()
}

const getGifUrl = (path) => {
  if (!path) return ''
  if (path.startsWith('http://') || path.startsWith('https://')) return path
  if (path.startsWith('/')) return path
  if (path.startsWith('media/')) return `/${path}`
  return `/media/${path}`
}

// 获取序号
const getSerialNumber = (index) => {
  return (pagination.currentPage - 1) * pagination.pageSize + index + 1
}

// 处理选择变化
const handleSelectionChange = (selection) => {
  selectedRecords.value = selection
}

// 批量删除
const batchDeleteRecords = async () => {
  if (selectedRecords.value.length === 0) return

  try {
    await ElMessageBox.confirm(
      t('uiAutomation.ai.executionRecords.messages.batchDeleteConfirm', { count: selectedRecords.value.length }),
      t('uiAutomation.ai.executionRecords.messages.batchDeleteTitle'),
      {
        confirmButtonText: t('uiAutomation.common.confirm'),
        cancelButtonText: t('uiAutomation.common.cancel'),
        type: 'warning'
      }
    )

    isDeleting.value = true
    const ids = selectedRecords.value.filter(item => item.item_type !== 'batch').map(item => item.id)
    const batchIds = selectedRecords.value.filter(item => item.item_type === 'batch').map(item => item.batch_id)
    await batchDeleteAIExecutionRecords(ids, batchIds)

    ElMessage.success(t('uiAutomation.ai.executionRecords.messages.deleteSuccess'))

    // 如果当前页数据全部被删除，且不是第一页，则跳转到上一页
    if (records.value.length === ids.length && pagination.currentPage > 1) {
      pagination.currentPage--
    }

    loadRecords()
  } catch (error) {
    if (error !== 'cancel') {
      console.error('批量删除失败:', error)
      ElMessage.error(t('uiAutomation.ai.executionRecords.messages.batchDeleteFailed'))
    }
  } finally {
    isDeleting.value = false
  }
}



// 轮询更新状态
const startPolling = () => {
  pollTimer = setInterval(() => {
    // 只有在第一页且没有打开详情框且没有正在加载时才轮询
    if (pagination.currentPage === 1 && !showDetailDialog.value && !loading.value) {
      // A completed rerun creates a new record after this screen may already
      // have loaded. Keep refreshing so stale failures do not mask its result.
      getAIExecutionReportList({
        page: 1,
        page_size: pagination.pageSize
      }).then(response => {
        // 只有当没有选中项时才更新列表，避免干扰用户选择
        if (selectedRecords.value.length === 0) {
          records.value = response.data.results || []
          total.value = response.data.count || 0
        }
      }).catch(console.error)
    }
  }, 5000)
}

onMounted(() => {
  loadRecords()
  startPolling()
})

onUnmounted(() => {
  if (pollTimer) {
    clearInterval(pollTimer)
  }
})
</script>

<style lang="scss" scoped>
.page-container {
  padding: 20px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;

  .page-title {
    font-size: 20px;
    font-weight: 600;
    margin: 0;
  }

  .header-actions {
    display: flex;
    align-items: center;
  }
}

.card-container {
  background-color: #fff;
  border-radius: 4px;
  padding: 20px;
  box-shadow: 0 2px 12px 0 rgba(0, 0, 0, 0.1);
}

.pagination-container {
  margin-top: 20px;
  display: flex;
  justify-content: flex-end;
}

.record-detail {
  .detail-item {
    margin-bottom: 15px;
    .label {
      font-weight: bold;
      margin-right: 10px;
    }
  }

  .log-container {
    background-color: #1e1e1e;
    color: #fff;
    padding: 15px;
    border-radius: 4px;
    max-height: 400px;
    overflow-y: auto;
    font-family: monospace;

    pre {
      margin: 0;
      white-space: pre-wrap;
      word-wrap: break-word;
    }
  }

  .task-description-container {
    background-color: #f5f7fa;
    border: 1px solid #e4e7ed;
    border-radius: 4px;
    padding: 12px 15px;
    margin-top: 8px;

    .task-description-content {
      color: #606266;
      line-height: 1.6;
      white-space: pre-wrap;
      word-wrap: break-word;
    }
  }
}

.mt-15 {
  margin-top: 15px;
}

.batch-count-tag {
  margin-left: 8px;
}

.gif-container {
  text-align: center;
}

.gif-image {
  max-width: 100%;
  border-radius: 6px;
  border: 1px solid #ebeef5;
}
</style>
