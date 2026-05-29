<template>
  <div class="execution-detail">
    <!-- 美化的页面头部 -->
    <div class="page-header-card">
      <div class="header-content">
        <div class="title-section">
          <h1 class="page-title">{{ testPlan.name }}</h1>
          <el-tag v-if="testPlan.version" type="primary" size="large" class="version-tag">
            <el-icon><Stamp /></el-icon>
            {{ testPlan.version }}
          </el-tag>
        </div>
        
        <!-- 项目信息 -->
        <div class="project-info">
          <el-icon class="info-icon"><FolderOpened /></el-icon>
          <span v-if="testPlan.projects && testPlan.projects.length > 0">
            {{ testPlan.projects.join(', ') }}
          </span>
          <span v-else class="no-data">{{ $t('execution.noProject') }}</span>
        </div>
      </div>
    </div>

    <!-- 测试执行区域 -->
    <div v-if="testPlan.test_runs && testPlan.test_runs.length > 0">
      <div v-for="run in testPlan.test_runs" :key="run.id" class="test-run-card">
        <!-- 美化的运行头部 -->
        <div class="run-header">
          <div class="run-title-section">
            <h2 class="run-title">{{ run.name }}</h2>
            <el-tag :type="getRunStatusType(run.progress)" size="large" class="run-status-tag">
              {{ getRunStatusText(run.progress) }}
            </el-tag>
          </div>
          
          <!-- 美化的统计卡片 -->
          <div class="stats-cards">
            <div class="stat-card total">
              <el-icon class="stat-icon"><Document /></el-icon>
              <div class="stat-content">
                <div class="stat-value">{{ run.progress.total }}</div>
                <div class="stat-label">{{ $t('execution.total') }}</div>
              </div>
            </div>
            <div class="stat-card passed">
              <el-icon class="stat-icon"><CircleCheck /></el-icon>
              <div class="stat-content">
                <div class="stat-value">{{ run.progress.passed }}</div>
                <div class="stat-label">{{ $t('execution.passed') }}</div>
              </div>
            </div>
            <div class="stat-card failed">
              <el-icon class="stat-icon"><CircleClose /></el-icon>
              <div class="stat-content">
                <div class="stat-value">{{ run.progress.failed }}</div>
                <div class="stat-label">{{ $t('execution.failed') }}</div>
              </div>
            </div>
            <div class="stat-card blocked">
              <el-icon class="stat-icon"><WarningFilled /></el-icon>
              <div class="stat-content">
                <div class="stat-value">{{ run.progress.blocked }}</div>
                <div class="stat-label">{{ $t('execution.blocked') }}</div>
              </div>
            </div>
            <div class="stat-card untested">
              <el-icon class="stat-icon"><QuestionFilled /></el-icon>
              <div class="stat-content">
                <div class="stat-value">{{ run.progress.untested }}</div>
                <div class="stat-label">{{ $t('execution.untested') }}</div>
              </div>
            </div>
          </div>
        </div>

        <!-- 进度条 -->
        <div class="progress-section">
          <el-progress 
            :percentage="run.progress.progress" 
            :stroke-width="12"
            :color="getProgressColor(run.progress.progress)"
            :show-text="true">
            <template #default="{ percentage }">
              <span class="progress-text">{{ percentage }}%</span>
            </template>
          </el-progress>
        </div>

        <!-- 批量操作按钮 -->
        <div v-if="selectedCases.length > 0" class="batch-actions">
          <span class="batch-actions-label">已选 {{ selectedCases.length }} 个：</span>
          <el-button-group class="batch-status-group">
            <el-button type="success" :icon="CircleCheck" :disabled="isBatchUpdating" @click="batchUpdateStatus('passed')">通过</el-button>
            <el-button type="danger" :icon="CircleClose" :disabled="isBatchUpdating" @click="batchUpdateStatus('failed')">未通过</el-button>
            <el-button type="warning" :icon="WarningFilled" :disabled="isBatchUpdating" @click="batchUpdateStatus('blocked')">阻塞</el-button>
            <el-button type="primary" :icon="RefreshRight" :disabled="isBatchUpdating" @click="batchUpdateStatus('retest')">重测</el-button>
            <el-button :icon="QuestionFilled" :disabled="isBatchUpdating" @click="batchUpdateStatus('untested')">未测试</el-button>
          </el-button-group>
          <el-button
            type="danger"
            plain
            :icon="Delete"
            @click="batchDeleteCases"
            :disabled="isDeleting || isBatchUpdating">
            {{ $t('execution.batchDelete') }} ({{ selectedCases.length }})
          </el-button>
        </div>

        <!-- 优化的用例表格 -->
        <el-table
          ref="tableRef"
          :data="paginatedCases(run.run_cases)"
          style="width: 100%"
          class="execution-table"
          :row-class-name="getRowClassName"
          @selection-change="handleSelectionChange"
          :row-key="(row) => row.id">
          <el-table-column type="selection" width="55" :reserve-selection="true" />
          <el-table-column
            type="index"
            :label="$t('execution.serialNumber')"
            width="80"
            :index="getSerialNumber" />
          <el-table-column :label="$t('execution.testCase')" min-width="220">
            <template #default="scope">
              <div class="case-title-cell">
                <el-tag v-if="scope.row.testcase && scope.row.testcase.module" size="small" type="info" effect="plain" class="module-tag">
                  {{ scope.row.testcase.module }}
                </el-tag>
                <span class="case-title-text">{{ scope.row.testcase && scope.row.testcase.title || scope.row.testcase }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="操作步骤" min-width="260">
            <template #default="scope">
              <div v-if="scope.row.testcase && scope.row.testcase.steps" class="steps-cell">
                <el-tooltip placement="top-start" :show-after="300">
                  <template #content>
                    <div class="steps-tooltip-content">{{ scope.row.testcase.steps }}</div>
                  </template>
                  <pre class="steps-text">{{ scope.row.testcase.steps }}</pre>
                </el-tooltip>
              </div>
              <span v-else class="empty-text">-</span>
            </template>
          </el-table-column>
          <el-table-column label="预期结果" min-width="220">
            <template #default="scope">
              <div v-if="scope.row.testcase && scope.row.testcase.expected_result" class="steps-cell">
                <el-tooltip placement="top-start" :show-after="300">
                  <template #content>
                    <div class="steps-tooltip-content">{{ scope.row.testcase.expected_result }}</div>
                  </template>
                  <pre class="steps-text">{{ scope.row.testcase.expected_result }}</pre>
                </el-tooltip>
              </div>
              <span v-else class="empty-text">-</span>
            </template>
          </el-table-column>
          <el-table-column :label="$t('execution.executionStatus')" width="150">
            <template #default="scope">
              <el-select
                v-model="scope.row.status"
                @change="updateCaseStatus(scope.row)"
                size="small">
                <el-option :label="$t('execution.untested')" value="untested" />
                <el-option :label="$t('execution.passed')" value="passed" />
                <el-option :label="$t('execution.failed')" value="failed" />
                <el-option :label="$t('execution.blocked')" value="blocked" />
                <el-option :label="$t('execution.retest')" value="retest" />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column :label="$t('execution.comments')" min-width="250">
            <template #default="scope">
              <el-input
                v-model="scope.row.comments"
                :placeholder="$t('execution.commentsPlaceholder')"
                type="textarea"
                :rows="2"
                size="small"
                @blur="updateCaseDetails(scope.row)">
              </el-input>
            </template>
          </el-table-column>
          <el-table-column :label="$t('execution.actions')" width="120" fixed="right">
            <template #default="scope">
              <el-button
                size="small"
                type="primary"
                :icon="Clock"
                @click="viewCaseHistory(scope.row)">
                {{ $t('execution.viewHistory') }}
              </el-button>
            </template>
          </el-table-column>
        </el-table>

        <!-- 分页组件 -->
        <div v-if="run.run_cases && run.run_cases.length > 0" class="pagination-container">
          <el-pagination
            v-model:current-page="currentPage"
            v-model:page-size="pageSize"
            :page-sizes="[10, 20, 50, 100]"
            :total="run.run_cases.length"
            layout="total, sizes, prev, pager, next, jumper"
            @current-change="handlePageChange"
            @size-change="handleSizeChange">
          </el-pagination>
        </div>
      </div>
    </div>

    <!-- 历史记录对话框 -->
    <el-dialog
      :title="$t('execution.executionHistory')"
      v-model="historyDialogVisible"
      width="80%">
      <el-table :data="currentCaseHistory" style="width: 100%">
        <el-table-column prop="status" :label="$t('execution.status')" width="100">
          <template #default="scope">
            <el-tag :type="getStatusType(scope.row.status)">
              {{ getStatusText(scope.row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="comments" :label="$t('execution.comments')" show-overflow-tooltip />
        <el-table-column prop="executed_by.username" :label="$t('execution.executedBy')" width="120" />
        <el-table-column prop="executed_at" :label="$t('execution.executedAt')" width="180">
          <template #default="scope">
            {{ formatDate(scope.row.executed_at) }}
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Delete, Clock, Document, CircleCheck, CircleClose,
  WarningFilled, QuestionFilled, Stamp, FolderOpened, RefreshRight
} from '@element-plus/icons-vue'
import axios from 'axios'

const { t } = useI18n()

const route = useRoute()
const testPlan = ref({})
const historyDialogVisible = ref(false)
const currentCaseHistory = ref([])
const selectedCases = ref([])
const currentPage = ref(1)
const pageSize = ref(10)
const isDeleting = ref(false)
const isBatchUpdating = ref(false)
const tableRef = ref(null)

const fetchTestPlan = async () => {
  try {
    const planId = route.params.id
    const response = await axios.get(`/api/executions/plans/${planId}/`)
    testPlan.value = response.data
  } catch (error) {
    ElMessage.error(t('execution.fetchDetailFailed'))
  }
}

const updateCaseStatus = async (runCase) => {
  try {
    await axios.patch(`/api/executions/run_cases/${runCase.id}/update_status/`, {
      status: runCase.status,
      comments: runCase.comments || ''
    })
    await fetchTestPlan() // 刷新数据以更新进度和最后执行时间
    ElMessage.success(t('execution.statusUpdateSuccess'))
  } catch (error) {
    ElMessage.error(t('execution.statusUpdateFailed'))
  }
}

const updateCaseDetails = async (runCase) => {
  try {
    await axios.patch(`/api/executions/run_cases/${runCase.id}/update_status/`, {
      status: runCase.status,
      comments: runCase.comments || ''
    })
    ElMessage.success(t('execution.detailsUpdateSuccess'))
  } catch (error) {
    ElMessage.error(t('execution.detailsUpdateFailed'))
  }
}

const viewCaseHistory = async (runCase) => {
  try {
    const response = await axios.get(`/api/executions/run_cases/${runCase.id}/history/`)
    currentCaseHistory.value = response.data
    historyDialogVisible.value = true
  } catch (error) {
    ElMessage.error(t('execution.fetchHistoryFailed'))
  }
}

// 批量更新状态
const statusLabelMap = {
  passed: t('execution.passed'),
  failed: t('execution.failed'),
  blocked: t('execution.blocked'),
  retest: t('execution.retest'),
  untested: t('execution.untested'),
}

// 根据状态返回行背景色类名
const getRowClassName = ({ row }) => {
  const s = row && row.status
  if (!s || s === 'untested') return ''
  return `row-status row-status-${s}`
}

const batchUpdateStatus = async (newStatus) => {
  if (selectedCases.value.length === 0) {
    ElMessage.warning(t('execution.selectCasesFirst'))
    return
  }
  const label = statusLabelMap[newStatus] || newStatus
  try {
    await ElMessageBox.confirm(
      `确认将已选的 ${selectedCases.value.length} 个用例状态批量更改为 “${label}” 吗？`,
      t('common.warning'),
      {
        confirmButtonText: t('common.confirm'),
        cancelButtonText: t('common.cancel'),
        type: 'warning'
      }
    )

    isBatchUpdating.value = true
    const ids = selectedCases.value.map(c => c.id)
    const resp = await axios.patch('/api/executions/run_cases/batch_update_status/', {
      ids,
      status: newStatus,
    })
    const updated = resp.data && resp.data.updated != null ? resp.data.updated : ids.length
    ElMessage.success(`批量更新成功：${updated} 个用例 → ${label}`)
    selectedCases.value = []
    if (tableRef.value) {
      const tables = Array.isArray(tableRef.value) ? tableRef.value : [tableRef.value]
      tables.forEach(t => t && t.clearSelection && t.clearSelection())
    }
    await fetchTestPlan()
  } catch (error) {
    if (error !== 'cancel') {
      console.error('批量更新状态失败:', error)
      const msg = (error.response && error.response.data && (error.response.data.error || error.response.data.detail)) || '批量更新状态失败'
      ElMessage.error(msg)
    }
  } finally {
    isBatchUpdating.value = false
  }
}

// 处理选择变化
const handleSelectionChange = (selection) => {
  selectedCases.value = selection
}

// 批量删除
const batchDeleteCases = async () => {
  if (selectedCases.value.length === 0) {
    ElMessage.warning(t('execution.selectCasesFirst'))
    return
  }

  try {
    await ElMessageBox.confirm(
      t('execution.batchDeleteCasesConfirm', { count: selectedCases.value.length }),
      t('common.warning'),
      {
        confirmButtonText: t('common.confirm'),
        cancelButtonText: t('common.cancel'),
        type: 'warning'
      }
    )

    isDeleting.value = true
    let successCount = 0
    let failCount = 0

    for (const runCase of selectedCases.value) {
      try {
        await axios.delete(`/api/executions/run_cases/${runCase.id}/`)
        successCount++
      } catch (error) {
        console.error(`删除用例 ${runCase.id} 失败:`, error)
        failCount++
      }
    }

    if (successCount > 0) {
      if (failCount > 0) {
        ElMessage.success(t('execution.batchDeleteCasesPartialSuccess', { successCount, failCount }))
      } else {
        ElMessage.success(t('execution.batchDeleteCasesSuccess', { successCount }))
      }
    } else {
      ElMessage.error(t('execution.batchDeleteFailed'))
    }

    selectedCases.value = []
    await fetchTestPlan()

  } catch (error) {
    if (error !== 'cancel') {
      console.error('批量删除失败:', error)
      ElMessage.error(t('execution.batchDeleteFailed'))
    }
  } finally {
    isDeleting.value = false
  }
}

// 分页相关
const paginatedCases = (cases) => {
  if (!cases) return []
  const start = (currentPage.value - 1) * pageSize.value
  const end = start + pageSize.value
  return cases.slice(start, end)
}

const getSerialNumber = (index) => {
  return (currentPage.value - 1) * pageSize.value + index + 1
}

const handlePageChange = () => {
  selectedCases.value = []
  // 清空表格选择
  if (tableRef.value) {
    tableRef.value.clearSelection()
  }
}

const handleSizeChange = () => {
  currentPage.value = 1
  selectedCases.value = []
  // 清空表格选择
  if (tableRef.value) {
    tableRef.value.clearSelection()
  }
}

const formatDate = (dateString) => {
  if (!dateString) return '-'
  return new Date(dateString).toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

const getProgressColor = (percentage) => {
  if (percentage < 30) return '#f56c6c'
  if (percentage < 70) return '#e6a23c'
  return '#67c23a'
}

const getRunStatusType = (progress) => {
  if (progress.progress === 100) return 'success'
  if (progress.failed > 0) return 'danger'
  if (progress.blocked > 0) return 'warning'
  return 'info'
}

const getRunStatusText = (progress) => {
  if (progress.progress === 100) return t('execution.completed')
  if (progress.untested === progress.total) return t('execution.notStarted')
  return t('execution.inProgress')
}

const getStatusType = (status) => {
  const typeMap = {
    'untested': 'info',
    'passed': 'success',
    'failed': 'danger',
    'blocked': 'warning',
    'retest': 'primary'
  }
  return typeMap[status] || 'info'
}

const getStatusText = (status) => {
  const textMap = {
    'untested': t('execution.untested'),
    'passed': t('execution.passed'),
    'failed': t('execution.failed'),
    'blocked': t('execution.blocked'),
    'retest': t('execution.retest')
  }
  return textMap[status] || status
}

onMounted(() => {
  fetchTestPlan()
})
</script>

<style scoped>
.execution-detail {
  padding: 24px;
  background: #f5f7fa;
  min-height: 100vh;
}

/* 美化的页面头部 */
.page-header-card {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border-radius: 16px;
  padding: 32px;
  margin-bottom: 24px;
  box-shadow: 0 8px 24px rgba(102, 126, 234, 0.25);
  color: white;
}

.header-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.title-section {
  display: flex;
  align-items: center;
  gap: 16px;
}

.page-title {
  margin: 0;
  font-size: 28px;
  font-weight: 600;
  color: white;
}

.version-tag {
  display: flex;
  align-items: center;
  gap: 6px;
  background: rgba(255, 255, 255, 0.2);
  border: 1px solid rgba(255, 255, 255, 0.3);
  color: white;
  backdrop-filter: blur(10px);
}

.project-info {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  color: rgba(255, 255, 255, 0.9);
}

.info-icon {
  font-size: 18px;
}

.no-data {
  color: rgba(255, 255, 255, 0.6);
  font-style: italic;
}

/* 测试运行卡片 */
.test-run-card {
  background: white;
  border-radius: 12px;
  padding: 24px;
  margin-bottom: 24px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.08);
}

.run-header {
  margin-bottom: 24px;
}

.run-title-section {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 20px;
}

.run-title {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
  color: #303133;
}

.run-status-tag {
  font-weight: 600;
}

/* 美化的统计卡片 */
.stats-cards {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 16px;
  margin-bottom: 20px;
}

.stat-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
  border-radius: 12px;
  transition: all 0.3s ease;
  cursor: default;
}

.stat-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

.stat-card.total {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
}

.stat-card.passed {
  background: linear-gradient(135deg, #84fab0 0%, #8fd3f4 100%);
  color: #155724;
}

.stat-card.failed {
  background: linear-gradient(135deg, #fa709a 0%, #fee140 100%);
  color: #721c24;
}

.stat-card.blocked {
  background: linear-gradient(135deg, #ffecd2 0%, #fcb69f 100%);
  color: #856404;
}

.stat-card.untested {
  background: linear-gradient(135deg, #e0e7ff 0%, #cfd9ff 100%);
  color: #383d41;
}

.stat-icon {
  font-size: 32px;
  opacity: 0.9;
}

.stat-content {
  display: flex;
  flex-direction: column;
}

.stat-value {
  font-size: 24px;
  font-weight: 700;
  line-height: 1;
}

.stat-label {
  font-size: 12px;
  margin-top: 4px;
  opacity: 0.9;
}

/* 进度条区域 */
.progress-section {
  margin-bottom: 24px;
  padding: 16px;
  background: #f8f9fa;
  border-radius: 8px;
}

.progress-text {
  font-weight: 600;
  font-size: 14px;
}

/* 已执行用例行背景色高亮 */
.execution-table :deep(.el-table__row.row-status-passed) > td.el-table__cell {
  background-color: #f0f9eb !important;
}
.execution-table :deep(.el-table__row.row-status-passed:hover) > td.el-table__cell {
  background-color: #e1f3d8 !important;
}
.execution-table :deep(.el-table__row.row-status-failed) > td.el-table__cell {
  background-color: #fef0f0 !important;
}
.execution-table :deep(.el-table__row.row-status-failed:hover) > td.el-table__cell {
  background-color: #fde2e2 !important;
}
.execution-table :deep(.el-table__row.row-status-blocked) > td.el-table__cell {
  background-color: #fdf6ec !important;
}
.execution-table :deep(.el-table__row.row-status-blocked:hover) > td.el-table__cell {
  background-color: #faecd8 !important;
}
.execution-table :deep(.el-table__row.row-status-retest) > td.el-table__cell {
  background-color: #ecf5ff !important;
}
.execution-table :deep(.el-table__row.row-status-retest:hover) > td.el-table__cell {
  background-color: #d9ecff !important;
}

/* 批量操作 */
.batch-actions {
  margin-bottom: 16px;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  padding: 10px 14px;
  background: linear-gradient(135deg, #f0f5ff 0%, #f9fbff 100%);
  border: 1px solid #d6e4ff;
  border-radius: 8px;
}
.batch-actions-label {
  font-size: 13px;
  color: #606266;
  font-weight: 500;
}
.batch-status-group {
  margin-right: auto;
}

/* 表格样式 */
.execution-table {
  border-radius: 8px;
  overflow: hidden;
}

/* 单元格样式 */
.case-title-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.module-tag {
  align-self: flex-start;
  font-size: 11px;
}
.case-title-text {
  font-weight: 500;
  color: #303133;
  word-break: break-word;
}
.steps-cell {
  max-height: 120px;
  overflow: hidden;
  position: relative;
}
.steps-text {
  margin: 0;
  font-family: inherit;
  font-size: 13px;
  color: #606266;
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.6;
  max-height: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 5;
  -webkit-box-orient: vertical;
}
.steps-tooltip-content {
  max-width: 480px;
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.6;
  font-size: 13px;
  max-height: 60vh;
  overflow-y: auto;
}
.empty-text {
  color: #c0c4cc;
}

/* 分页 */
.pagination-container {
  margin-top: 20px;
  display: flex;
  justify-content: center;
}
</style>
