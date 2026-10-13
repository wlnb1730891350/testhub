<template>
  <div class="perf-page">
    <div class="page-header">
      <h2>性能项目</h2>
      <el-button type="primary" :icon="Plus" @click="openDialog()">新建项目</el-button>
    </div>

    <el-table :data="projects" v-loading="loading">
      <el-table-column prop="name" label="项目名称" min-width="180" />
      <el-table-column prop="base_url" label="基础 URL" min-width="220" />
      <el-table-column prop="status" label="状态" width="120" />
      <el-table-column prop="owner.username" label="负责人" width="120" />
      <el-table-column label="更新时间" min-width="180">
        <template #default="{ row }">
          {{ formatDate(row.updated_at) }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="180" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openDialog(row)">编辑</el-button>
          <el-button link type="danger" @click="removeProject(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogVisible" :title="form.id ? '编辑项目' : '新建项目'" width="560px">
      <el-form :model="form" label-width="100px">
        <el-form-item label="项目名称" required>
          <el-input v-model.trim="form.name" />
        </el-form-item>
        <el-form-item label="基础 URL">
          <el-input v-model.trim="form.base_url" placeholder="https://example.com" />
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="form.status" style="width: 100%">
            <el-option label="未开始" value="not_started" />
            <el-option label="进行中" value="active" />
            <el-option label="暂停" value="paused" />
            <el-option label="完成" value="completed" />
            <el-option label="归档" value="archived" />
          </el-select>
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveProject">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import dayjs from 'dayjs'
import {
  createPerformanceProject,
  deletePerformanceProject,
  getPerformanceProjects,
  updatePerformanceProject,
} from '@/api/performance-testing'

const loading = ref(false)
const saving = ref(false)
const projects = ref([])
const dialogVisible = ref(false)
const form = ref({})

const blankForm = () => ({ name: '', description: '', status: 'active', base_url: '' })

const formatDate = (dateString) => {
  return dateString ? dayjs(dateString).format('YYYY-MM-DD HH:mm') : '-'
}

const loadProjects = async () => {
  loading.value = true
  try {
    const { data } = await getPerformanceProjects({ page_size: 1000 })
    projects.value = data.results || data
  } finally {
    loading.value = false
  }
}

const openDialog = (row) => {
  form.value = row ? { ...row } : blankForm()
  dialogVisible.value = true
}

const saveProject = async () => {
  if (!form.value.name) {
    ElMessage.warning('请输入项目名称')
    return
  }
  saving.value = true
  try {
    if (form.value.id) {
      await updatePerformanceProject(form.value.id, form.value)
    } else {
      await createPerformanceProject(form.value)
    }
    ElMessage.success('保存成功')
    dialogVisible.value = false
    await loadProjects()
  } finally {
    saving.value = false
  }
}

const removeProject = async (row) => {
  await ElMessageBox.confirm(`确认删除项目「${row.name}」？`, '提示', { type: 'warning' })
  await deletePerformanceProject(row.id)
  ElMessage.success('删除成功')
  await loadProjects()
}

onMounted(loadProjects)
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
