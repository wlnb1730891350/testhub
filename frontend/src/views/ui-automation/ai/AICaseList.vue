<template>
  <div class="page-container">
    <div class="page-header">
      <h1 class="page-title">{{ $t('uiAutomation.ai.caseList.title') }}</h1>
      <el-button type="warning" :disabled="selectedCases.length === 0 || batchRunning" @click="startBatchRun">
        <el-icon><VideoPlay /></el-icon>
        批量运行已选用例 ({{ selectedCases.length }})
      </el-button>
      <el-button type="primary" :disabled="selectedCases.length === 0 || batchConfiguringTemplate" @click="openBatchTemplateDialog">
        <el-icon><Setting /></el-icon>
        批量配置预置模板 ({{ selectedCases.length }})
      </el-button>
      <el-button type="primary" :disabled="selectedCases.length === 0 || batchConfiguringCategory" @click="openBatchCategoryDialog">
        <el-icon><Setting /></el-icon>
        批量归类 ({{ selectedCases.length }})
      </el-button>
      <el-button type="success" :disabled="selectedCases.length === 0 || batchEnablingDualMode" :loading="batchEnablingDualMode" @click="enableSelectedCasesDualMode">
        批量生成 Windows 版 ({{ selectedCases.length }})
      </el-button>
      <el-button type="success" :disabled="selectedCases.length === 0 || batchEnablingBrowserMode" :loading="batchEnablingBrowserMode" @click="enableSelectedCasesBrowserMode">
        批量生成浏览器版 ({{ selectedCases.length }})
      </el-button>
      <el-button type="danger" :disabled="selectedCases.length === 0 || batchDeleting" :loading="batchDeleting" @click="batchDeleteSelectedCases">
        <el-icon><Delete /></el-icon>
        批量删除已选用例 ({{ selectedCases.length }})
      </el-button>
      <el-button type="danger" :disabled="!hasCompletedBatchRecords || batchSaving" :loading="batchSaving" @click="batchSaveAIRecording">
        <el-icon><VideoPlay /></el-icon>
        批量保存录制结果 ({{ completedBatchCount }})
      </el-button>
      <el-button type="primary" @click="openImportDialog">
        <el-icon><Upload /></el-icon>
        导入 AI 用例
      </el-button>
      <el-button type="info" @click="showSetupTemplateDialog = true">
        <el-icon><Setting /></el-icon>
        管理预置步骤模板
      </el-button>
      <el-button type="info" @click="openCategoryDialog">
        <el-icon><Setting /></el-icon>
        管理功能分类
      </el-button>
      <el-button type="info" @click="openDesktopAppDialog">
        <el-icon><Setting /></el-icon>
        管理桌面应用
      </el-button>
    </div>

    <div class="card-container">
      <div class="filter-bar">
        <el-input
          v-model="searchText"
          :placeholder="$t('uiAutomation.ai.caseList.searchPlaceholder')"
          clearable
          @input="handleSearch"
          style="width: 300px;"
        >
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
        </el-input>
        <el-select
          v-model="selectedCategoryId"
          clearable
          filterable
          placeholder="全部功能分类"
          style="width: 220px; margin-left: 12px;"
          @change="handleCategoryFilterChange"
        >
          <el-option
            v-for="category in categories"
            :key="category.id"
            :label="formatCategoryOption(category)"
            :value="category.id"
          />
        </el-select>
      </div>

      <el-table :data="cases" v-loading="loading" style="width: 100%" @selection-change="handleSelectionChange">
        <el-table-column type="selection" width="55" />
        <el-table-column prop="name" :label="$t('uiAutomation.ai.caseList.caseName')" min-width="200" show-overflow-tooltip />
        <el-table-column label="执行端" width="100">
          <template #default="{ row }">
            <el-tag :type="row.execution_target === 'desktop' ? 'warning' : row.execution_target === 'dual' ? 'success' : 'info'" size="small">
              {{ row.execution_target === 'dual' ? '浏览器 + Windows' : row.execution_target === 'desktop' ? 'Windows' : '浏览器' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="description" :label="$t('uiAutomation.common.description')" min-width="200" show-overflow-tooltip />
        <el-table-column prop="task_description" :label="$t('uiAutomation.ai.caseList.taskDescription')" min-width="300" show-overflow-tooltip />
        <el-table-column label="功能分类" width="160" show-overflow-tooltip>
          <template #default="{ row }">
            <el-tag v-if="row.category_name" type="success" size="small">{{ row.category_name }}</el-tag>
            <span v-else style="color: #c0c4cc; font-size: 12px;">未分类</span>
          </template>
        </el-table-column>
        <el-table-column label="预置模板" width="160" show-overflow-tooltip>
          <template #default="{ row }">
            <el-tag v-if="row.setup_template_name" type="info" size="small">{{ row.setup_template_name }}</el-tag>
            <span v-else style="color: #c0c4cc; font-size: 12px;">-</span>
          </template>
        </el-table-column>
        <el-table-column label="最近运行" width="120">
          <template #default="{ row }">
            <el-tag :type="getExecutionStatusTagType(row.latest_execution_status)" size="small">
              {{ getExecutionStatusLabel(row.latest_execution_status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="最近运行时间" width="180">
          <template #default="{ row }">
            {{ row.latest_execution_time ? formatSimpleDate(row.latest_execution_time) : '-' }}
          </template>
        </el-table-column>
        <el-table-column label="失败摘要" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">
            <span v-if="row.latest_failure_reason">{{ row.latest_failure_reason }}</span>
            <span v-else style="color: #c0c4cc;">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" :label="$t('uiAutomation.common.createTime')" width="180" :formatter="formatDate" />
        <el-table-column :label="$t('uiAutomation.common.operation')" width="280" fixed="right">
          <template #default="{ row }">
            <template v-if="caseRunningStatus[row.id]">
              <el-tag type="warning" size="small">录制中...</el-tag>
            </template>
            <template v-else>
              <el-dropdown v-if="row.execution_target === 'dual'" trigger="click" @command="target => runCase(row, target)">
                <el-button size="small" type="success">
                  <el-icon><VideoPlay /></el-icon>
                  运行
                </el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="web">浏览器运行</el-dropdown-item>
                    <el-dropdown-item command="desktop">Windows 运行</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
              <el-button v-else size="small" type="success" @click="runCase(row)">
                <el-icon><VideoPlay /></el-icon>
                {{ $t('uiAutomation.common.run') }}
              </el-button>
              <el-button size="small" type="primary" @click="editCase(row)">
                <el-icon><Edit /></el-icon>
                {{ $t('uiAutomation.common.edit') }}
              </el-button>
              <el-button size="small" type="danger" @click="deleteCase(row.id)">
                <el-icon><Delete /></el-icon>
                {{ $t('uiAutomation.common.delete') }}
              </el-button>
              <el-button v-if="caseAIRecordReady[row.id]" size="small" type="warning" @click="openAIRecordForCase(row)">
                查看 AI 录制
              </el-button>
            </template>
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

    <!-- 缂傚倸鍊归悧鐐垫椤愩倐鍋撻悽娈挎敯闁伙箒妫勯々?-->
    <el-dialog v-model="showEditDialog" :title="$t('uiAutomation.ai.caseList.editCase')" width="600px" :close-on-click-modal="false">
      <el-form :model="editForm" :rules="formRules" ref="editFormRef" label-width="100px">
        <el-form-item :label="$t('uiAutomation.ai.caseList.caseName')" prop="name">
          <el-input v-model="editForm.name" :placeholder="$t('uiAutomation.ai.caseNamePlaceholder')" />
        </el-form-item>
        <el-form-item :label="$t('uiAutomation.common.description')" prop="description">
          <el-input v-model="editForm.description" type="textarea" :placeholder="$t('uiAutomation.ai.caseDescPlaceholder')" />
        </el-form-item>
        <el-form-item label="执行端">
          <el-radio-group v-model="editForm.execution_target">
            <el-radio value="web">浏览器</el-radio>
            <el-radio value="desktop">Windows 桌面</el-radio>
            <el-radio value="dual">浏览器 + Windows</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="editForm.execution_target === 'desktop' || editForm.execution_target === 'dual'" label="桌面应用">
          <el-select v-model="editForm.desktop_app_profile" clearable filterable placeholder="选择已登记的客户端" style="width: 100%;">
            <el-option
              v-for="profile in desktopAppProfiles"
              :key="profile.id"
              :label="profile.name"
              :value="profile.id"
            />
          </el-select>
          <div class="category-empty-tip">
            选择 NN 客户端后会自动连接后台执行，不需要配置端口、启动参数或元素脚本。
          </div>
        </el-form-item>
        <el-form-item v-if="editForm.execution_target !== 'dual'" :label="$t('uiAutomation.ai.caseList.taskDescription')" prop="task_description">
          <el-input
            v-model="editForm.task_description"
            type="textarea"
            :rows="6"
            :placeholder="$t('uiAutomation.ai.taskPlaceholder')"
          />
        </el-form-item>
        <el-form-item v-else label="两端用例">
          <el-tabs v-model="dualTaskTab" class="dual-mode-tabs">
            <el-tab-pane label="浏览器用例" name="web">
              <el-input
                v-model="editForm.web_task_description"
                type="textarea"
                :rows="7"
                placeholder="填写浏览器端的操作步骤和断言"
              />
            </el-tab-pane>
            <el-tab-pane label="Windows 用例" name="desktop">
              <el-input
                v-model="editForm.desktop_task_description"
                type="textarea"
                :rows="7"
                placeholder="填写 Windows 客户端的操作步骤和断言"
              />
            </el-tab-pane>
          </el-tabs>
        </el-form-item>
        <el-form-item label="断言预检">
          <div class="assertion-preview-panel">
            <div class="assertion-preview-toolbar">
              <span v-if="assertionPreview">已编译 {{ assertionPreview.summary.compiled }} 条，待复核 {{ assertionPreview.summary.review_required }} 条</span>
              <span v-else>保存前检查断言能否编译为执行合同</span>
              <el-button size="small" @click="loadAssertionPreview" :loading="assertionPreviewLoading">检查断言</el-button>
            </div>
            <el-empty v-if="assertionPreview && !assertionPreview.assertions.length" description="此用例没有断言步骤" :image-size="44" />
            <div v-else-if="assertionPreview" class="assertion-preview-list">
              <div v-for="item in assertionPreview.assertions" :key="item.step_number" class="assertion-preview-item">
                <el-tag :type="item.status === 'compiled' ? 'info' : 'warning'" size="small">
                  {{ item.status === 'compiled' ? '已编译' : '待复核' }}
                </el-tag>
                <span class="assertion-preview-description">{{ item.description }}</span>
                <span class="assertion-preview-kind">{{ formatAssertionContract(item.contract) }}</span>
              </div>
            </div>
          </div>
        </el-form-item>
        <el-form-item label="预置模板">
          <el-select v-model="editForm.setup_template" placeholder="请选择可选的预置步骤模板" clearable style="width: 100%">
            <el-option
              v-for="tpl in setupTemplates"
              :key="tpl.id"
              :label="tpl.name"
              :value="tpl.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="功能分类">
          <el-select v-model="editForm.category" clearable filterable placeholder="未分类" style="width: 100%">
            <el-option
              v-for="category in categoriesForCurrentCase"
              :key="category.id"
              :label="category.name"
              :value="category.id"
            />
          </el-select>
          <div v-if="!categoriesForCurrentCase.length" class="category-empty-tip">
            暂无功能分类。
            <el-button link type="primary" @click="openCategoryManagerForCurrentCase">新建分类</el-button>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <span class="dialog-footer">
          <el-button @click="showEditDialog = false">{{ $t('uiAutomation.common.cancel') }}</el-button>
          <el-button type="primary" @click="confirmEdit" :loading="saving">{{ $t('uiAutomation.common.save') }}</el-button>
        </span>
      </template>
    </el-dialog>

    <el-dialog v-model="showBatchCategoryDialog" title="批量归类" width="520px" :close-on-click-modal="false">
      <el-alert :title="`已选择 ${selectedCases.length} 条 AI 用例`" type="info" show-icon :closable="false" style="margin-bottom: 16px;" />
      <el-form label-position="top">
        <el-form-item label="功能分类">
          <el-select v-model="batchCategoryId" filterable placeholder="请选择功能分类" style="width: 100%;">
            <el-option
              v-for="category in batchCategoryOptions"
              :key="category.id"
              :label="category.name"
              :value="category.id"
            />
          </el-select>
          <div class="batch-template-tip">功能分类为全局分类，可跨项目批量归类。</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showBatchCategoryDialog = false" :disabled="batchConfiguringCategory">取消</el-button>
        <el-button type="warning" @click="confirmBatchCategory(true)" :loading="batchConfiguringCategory">清空分类</el-button>
        <el-button type="primary" @click="confirmBatchCategory(false)" :loading="batchConfiguringCategory" :disabled="!batchCategoryId">确认归类</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showCategoryDialog" title="管理功能分类" width="760px" :close-on-click-modal="false">
      <div class="category-toolbar">
        <el-button type="primary" @click="openNewCategoryForm">新建分类</el-button>
      </div>
      <el-table :data="categories" v-loading="categoriesLoading" style="width: 100%">
        <el-table-column prop="name" label="分类名称" min-width="150" />
        <el-table-column prop="description" label="说明" min-width="180" show-overflow-tooltip />
        <el-table-column prop="cases_count" label="用例数" width="90" align="center" />
        <el-table-column prop="sort_order" label="排序" width="80" align="center" />
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="viewCategoryCases(row)">查看用例</el-button>
            <el-button link type="primary" @click="editCategory(row)">编辑</el-button>
            <el-button link type="danger" @click="deleteCategory(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <el-dialog v-model="showCategoryFormDialog" :title="editingCategoryId ? '编辑功能分类' : '新建功能分类'" width="480px" :close-on-click-modal="false">
      <el-form :model="categoryForm" label-width="90px">
        <el-form-item label="分类名称" required>
          <el-input v-model="categoryForm.name" maxlength="100" show-word-limit />
        </el-form-item>
        <el-form-item label="分类说明">
          <el-input v-model="categoryForm.description" type="textarea" :rows="3" maxlength="500" show-word-limit />
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="categoryForm.sort_order" :min="0" :max="9999" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCategoryFormDialog = false">取消</el-button>
        <el-button type="primary" :loading="savingCategory" @click="saveCategory">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="showBatchTemplateDialog"
      title="批量配置预置模板"
      width="520px"
      :close-on-click-modal="false"
    >
      <el-alert
        :title="`已选择 ${selectedCases.length} 条 AI 用例`"
        type="info"
        show-icon
        :closable="false"
        style="margin-bottom: 16px;"
      />
      <el-form label-position="top">
        <el-form-item label="配置方式">
          <el-radio-group v-model="batchTemplateMode">
            <el-radio-button value="set">设置模板</el-radio-button>
            <el-radio-button value="clear">清空模板</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="batchTemplateMode === 'set'" label="预置模板">
          <el-select
            v-model="batchTemplateId"
            placeholder="请选择预置步骤模板"
            filterable
            style="width: 100%;"
          >
            <el-option
              v-for="tpl in setupTemplates"
              :key="tpl.id"
              :label="`${tpl.name}（${tpl.project_name || '未命名项目'}）`"
              :value="tpl.id"
            />
          </el-select>
          <div class="batch-template-tip">数据来自“管理预置步骤模板”，可按模板名称搜索。</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showBatchTemplateDialog = false" :disabled="batchConfiguringTemplate">取消</el-button>
        <el-button type="primary" @click="confirmBatchTemplate" :loading="batchConfiguringTemplate">
          {{ batchTemplateMode === 'clear' ? '确认清空' : '确认配置' }}
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showDesktopAppDialog" title="管理桌面应用" width="860px" :close-on-click-modal="false">
      <el-form :model="desktopAppForm" label-width="100px" class="desktop-app-form">
        <el-alert
          v-if="editingDesktopAppId"
          :title="`正在编辑：${desktopAppForm.name || '未命名应用'}`"
          description="请在下方修改配置，点击“保存修改”后才会更新这条桌面应用。"
          type="warning"
          show-icon
          :closable="false"
          style="margin-bottom: 16px;"
        />
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="应用名称" required>
              <el-input v-model="desktopAppForm.name" placeholder="例如：NN 客户端" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="进程名">
              <el-input v-model="desktopAppForm.process_name" placeholder="例如：NNClient.exe" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="程序路径">
          <el-input v-model="desktopAppForm.executable_path" placeholder="例如：C:\\Program Files\\NN\\NNClient.exe" />
        </el-form-item>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="窗口标题规则">
              <el-input v-model="desktopAppForm.window_title_regex" placeholder="例如：.*NN.*" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="自动化后端">
              <el-select v-model="desktopAppForm.backend" style="width: 100%;">
                <el-option label="UI Automation（推荐）" value="uia" />
                <el-option label="Win32" value="win32" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="启动参数">
              <el-input v-model="desktopAppForm.arguments" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="工作目录">
              <el-input v-model="desktopAppForm.work_dir" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="状态">
          <el-switch v-model="desktopAppForm.is_active" active-text="启用" inactive-text="停用" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="savingDesktopApp" @click="saveDesktopApp">
            {{ editingDesktopAppId ? '保存修改' : '新增应用' }}
          </el-button>
          <el-button @click="resetDesktopAppForm">{{ editingDesktopAppId ? '取消编辑' : '清空表单' }}</el-button>
        </el-form-item>
      </el-form>
      <el-table :data="desktopAppProfiles" v-loading="desktopAppsLoading" max-height="300">
        <el-table-column prop="name" label="应用" min-width="140" />
        <el-table-column prop="process_name" label="进程名" min-width="150" />
        <el-table-column prop="executable_path" label="程序路径" min-width="260" show-overflow-tooltip />
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'info'" size="small">{{ row.is_active ? '启用' : '停用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="130" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="editDesktopApp(row)">编辑</el-button>
            <el-button link type="danger" @click="deleteDesktopApp(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <!-- Import dialog -->
    <el-dialog v-model="showImportDialog" title="导入 AI 用例" width="720px" :close-on-click-modal="false">
      <el-alert
        title="支持导入 Markdown 或 Excel 文件，系统会按内容自动生成 AI 用例。"
        type="info"
        show-icon
        :closable="false"
        style="margin-bottom: 16px;"
      />
      <el-form :model="importForm" :rules="importRules" ref="importFormRef" label-width="100px">
        <el-form-item label="所属项目" prop="project_id">
          <el-select v-model="importForm.project_id" placeholder="请选择项目" filterable style="width: 100%;">
            <el-option
              v-for="project in projects"
              :key="project.id"
              :label="project.name"
              :value="project.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="功能分类">
          <el-select v-model="importForm.category_id" clearable filterable placeholder="可选：导入后直接归类" style="width: 100%;">
            <el-option
              v-for="category in categoriesForImportProject"
              :key="category.id"
              :label="category.name"
              :value="category.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="导入文件" prop="file">
          <el-upload
            class="ai-case-import-upload"
            drag
            :auto-upload="false"
            :limit="1"
            accept=".md,.markdown,.txt,.xlsx,.xlsm"
            :on-change="handleImportFileChange"
            :on-remove="handleImportFileRemove"
          >
            <el-icon class="el-icon--upload"><Upload /></el-icon>
            <div class="el-upload__text">将文件拖到这里，或<em>点击选择</em></div>
            <template #tip>
              <div class="el-upload__tip">支持 Markdown、TXT、Excel 格式，建议一份文件只包含同一批待导入用例。</div>
            </template>
          </el-upload>
        </el-form-item>
      </el-form>
      <div class="import-template">
        <div class="template-title">Markdown 示例</div>
        <pre>| 用例名称 | 用例描述 | 任务说明 |
| --- | --- | --- |
| 登录流程检查 | 校验登录页基础功能 | 打开 https://example.com/，完成登录并验证首页可见 |</pre>
      </div>
      <template #footer>
        <span class="dialog-footer">
          <el-button @click="showImportDialog = false">{{ $t('uiAutomation.common.cancel') }}</el-button>
          <el-button type="primary" @click="confirmImport" :loading="importing">开始导入</el-button>
        </span>
      </template>
    </el-dialog>

    <el-dialog v-model="showBatchRunModeDialog" title="批量运行方式" width="480px" :close-on-click-modal="false">
      <el-alert :title="`已选择 ${selectedCases.length} 条 AI 用例`" type="info" show-icon :closable="false" style="margin-bottom: 16px;" />
      <el-form-item label="运行端" style="margin-bottom: 16px;">
        <el-radio-group v-model="batchExecutionTarget">
          <el-radio-button value="web">浏览器</el-radio-button>
          <el-radio-button value="desktop">Windows</el-radio-button>
        </el-radio-group>
      </el-form-item>
      <el-radio-group v-model="batchRunMode" class="batch-run-mode-group">
        <el-radio value="sequential" border>
          <div>
            <div>依次执行</div>
            <div class="batch-run-mode-desc">上一条完成后再启动下一条，适合共享登录态或容易互相影响的用例。</div>
          </div>
        </el-radio>
        <el-radio value="concurrent" border>
          <div>
            <div>并发执行</div>
            <div class="batch-run-mode-desc">同时启动所有已选用例，速度更快，但会占用更多浏览器和机器资源。</div>
          </div>
        </el-radio>
      </el-radio-group>
      <template #footer>
        <el-button @click="showBatchRunModeDialog = false">取消</el-button>
        <el-button type="primary" @click="confirmBatchRun">开始运行</el-button>
      </template>
    </el-dialog>

    <!-- Batch record dialog -->
    <el-dialog v-model="showBatchDialog" title="批量运行进度" width="600px" :close-on-click-modal="false" :close-on-press-escape="false" :show-close="!batchRunning">
      <div v-if="batchRunning" style="margin-bottom: 16px;">
        <el-progress :percentage="batchProgress" :status="batchProgress === 100 ? 'success' : ''" />
        <p style="margin-top: 8px; color: #909399;">
          {{ batchRunMode === 'concurrent'
            ? `正在并发运行 ${batchTotal} 条用例...`
            : `正在处理第 ${batchCurrentIndex + 1} / ${batchTotal} 条用例...` }}
        </p>
      </div>
      <div class="batch-duration-summary">
        <span>批次总耗时</span>
        <strong>{{ batchDurationText }}</strong>
        <span class="batch-duration-note">从批量任务启动到最后一条用例结束</span>
      </div>
      <el-table :data="batchRecords" size="small" max-height="400">
        <el-table-column prop="case_name" label="用例名称" min-width="200" show-overflow-tooltip />
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-tag v-if="row.status === 'running'" type="warning" size="small">运行中</el-tag>
            <el-tag v-else-if="row.status === 'passed'" type="success" size="small">通过</el-tag>
            <el-tag v-else-if="row.status === 'failed'" type="danger" size="small">失败</el-tag>
            <el-tag v-else-if="row.status === 'error'" type="danger" size="small">异常</el-tag>
            <el-tag v-else size="small">等待中</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="单条耗时" width="100">
          <template #default="{ row }">
            {{ row.duration ? row.duration.toFixed(1) + 's' : '-' }}
          </template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button @click="showBatchDialog = false" :disabled="batchRunning">{{ batchRunning ? '运行中...' : '关闭' }}</el-button>
      </template>
    </el-dialog>

    <!-- Review dialog -->
    <el-dialog v-model="showReviewDialog" title="录制结果检查" width="90%" :close-on-click-modal="false" top="5vh">
      <el-alert
        title="这里可以检查本次录制识别出的步骤，勾选是否保留，也可以修改定位器后再保存。"
        type="info"
        show-icon
        :closable="false"
        style="margin-bottom: 16px;"
      />

      <el-tabs v-model="reviewActiveTab" type="border-card" v-if="reviewRecords.length > 0">
        <el-tab-pane
          v-for="(record, rIdx) in reviewRecords"
          :key="record.record_id"
          :label="record.case_name"
          :name="rIdx"
        >
          <div v-if="record.steps.length === 0" style="padding: 20px; text-align: center; color: #909399;">
            当前没有可检查的录制步骤。
          </div>
          <el-table v-else :data="record.steps" size="small" max-height="500" style="width: 100%">
            <el-table-column label="保留" width="60" align="center">
              <template #default="{ row, $index }">
                <el-checkbox :model-value="row.included" @change="toggleStepIncluded(rIdx, $index)" />
              </template>
            </el-table-column>
            <el-table-column prop="step_number" label="#" width="50" />
            <el-table-column prop="action_type" label="动作" width="100">
              <template #default="{ row }">
                <el-tag size="small" :type="row.action_type === 'click' ? '' : row.action_type === 'type' || row.action_type === 'fill' ? 'success' : row.action_type === 'assert' ? 'warning' : 'info'">
                  {{ row.action_type }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="description" label="说明" min-width="180" show-overflow-tooltip />
            <el-table-column label="元素" min-width="150" show-overflow-tooltip>
              <template #default="{ row }">
                <div v-if="row.element_tag" style="font-size: 12px;">
                  <span style="color: #409eff;">&lt;{{ row.element_tag }}</span>
                  <span v-if="row.element_id" style="color: #67c23a;"> id="{{ row.element_id }}"</span>
                  <span v-if="row.element_class" style="color: #909399;"> class="{{ row.element_class.substring(0, 40) }}{{ row.element_class.length > 40 ? '...' : '' }}"</span>
                  <span style="color: #409eff;">&gt;</span>
                </div>
                <span v-else style="color: #c0c4cc;">{{ row.element_name || '-' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="定位器" min-width="250">
              <template #default="{ row }">
                <el-input
                  v-model="row._edit_locator"
                  size="small"
                  placeholder="CSS / Playwright 定位器"
                  :disabled="!row.included"
                >
                  <template #prepend>
                    <span style="font-size: 11px;">{{ row.locator_strategy }}</span>
                  </template>
                </el-input>
              </template>
            </el-table-column>
            <el-table-column label="输入值" width="120" show-overflow-tooltip>
              <template #default="{ row }">
                <span style="font-size: 12px; color: #606266;">{{ row.input_value || '-' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="截图" width="80" align="center">
              <template #default="{ row }">
                <el-image
                  v-if="row.screenshot_b64"
                  :src="'data:image/png;base64,' + row.screenshot_b64"
                  :preview-src-list="['data:image/png;base64,' + row.screenshot_b64]"
                  fit="cover"
                  style="width: 50px; height: 36px; border-radius: 4px; cursor: pointer;"
                />
                <span v-else style="color: #c0c4cc;">-</span>
              </template>
            </el-table-column>
            <el-table-column label="步骤状态" width="90" align="center">
              <template #default="{ row }">
                <el-tag v-if="row.status === 'completed'" type="success" size="small">完成</el-tag>
                <el-tag v-else-if="row.status === 'failed'" type="danger" size="small">失败</el-tag>
                <el-tag v-else size="small">待确认</el-tag>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>

      <template #footer>
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <span style="color: #909399; font-size: 13px;">
            共 {{ reviewRecords.length }} 条录制结果，保留 {{ reviewRecords.reduce((sum, r) => sum + r.steps.filter(s => s.included).length, 0) }} 个步骤
          </span>
          <div>
            <el-button @click="showReviewDialog = false">取消</el-button>
            <el-button type="primary" @click="saveRecordingResults" :loading="savingRecording" :disabled="savingRecording">
              保存录制结果
            </el-button>
          </div>
        </div>
      </template>
    </el-dialog>

    <!-- AI record dialog -->
    <el-dialog v-model="showAIRecordDialog" title="AI 录制步骤确认" width="800px" :close-on-click-modal="false">
      <el-alert
        title="这里展示的是识别后的录制步骤。你可以先检查、删除多余步骤，再保存为测试用例。"
        type="info"
        :closable="false"
        style="margin-bottom: 12px;"
      />
      <el-form :model="aiRecordForm" label-width="100px">
        <el-form-item label="所属项目" required>
          <el-select v-model="aiRecordForm.projectId" placeholder="请选择要保存到的项目" filterable style="width: 100%;">
            <el-option
              v-for="project in projects"
              :key="project.id"
              :label="project.name"
              :value="project.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="测试用例名" required>
          <el-input v-model="aiRecordForm.testCaseName" placeholder="请输入测试用例名称" />
        </el-form-item>
      </el-form>

      <div style="margin-top: 12px; font-weight: 600;">录制步骤</div>
      <el-table :data="aiRecordingActions" v-loading="aiRecordLoading" height="300" border empty-text="暂无可保存的录制步骤" style="margin-top: 8px;">
        <el-table-column type="index" label="#" width="55" />
        <el-table-column prop="action_type" label="动作" width="90" />
        <el-table-column prop="description" label="说明" min-width="200" show-overflow-tooltip />
        <el-table-column prop="element_name" label="元素名称" min-width="150" show-overflow-tooltip />
        <el-table-column prop="locator_value" label="定位器" min-width="200" show-overflow-tooltip />
        <el-table-column prop="input_value" label="输入值" min-width="140" show-overflow-tooltip />
        <el-table-column label="操作" width="70" fixed="right">
          <template #default="{ $index }">
            <el-button size="small" type="danger" link @click="removeAIRecordingStep($index)">
              <el-icon><Delete /></el-icon>
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <template #footer>
        <span class="dialog-footer">
          <el-button @click="showAIRecordDialog = false">取消</el-button>
          <el-button type="primary" @click="confirmSaveAIRecording" :loading="aiRecordSaving" :disabled="aiRecordingActions.length === 0">
            保存为测试用例
          </el-button>
        </span>
      </template>
    </el-dialog>

    <!-- Batch save dialog -->
    <el-dialog v-model="showBatchSaveDialog" title="批量保存录制结果" width="75%" :close-on-click-modal="false" top="5vh">
      <el-alert
        title="批量录制完成后，可以在这里统一设置测试用例名称和所属项目，再一次性保存。"
        type="info"
        show-icon
        :closable="false"
        style="margin-bottom: 16px;"
      />
      <el-table :data="batchSaveItems" size="small" max-height="500" style="width: 100%">
        <el-table-column label="测试用例名" min-width="250">
          <template #default="{ row }">
            <el-input v-model="row.test_case_name" size="small" />
          </template>
        </el-table-column>
        <el-table-column label="所属项目" width="250">
          <template #default="{ row }">
            <el-select v-model="row.project_id" size="small" placeholder="请选择项目" style="width: 100%">
              <el-option
                v-for="p in projects"
                :key="p.id"
                :label="p.name"
                :value="p.id"
              />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.saved" type="success" size="small">已保存</el-tag>
            <el-tag v-else-if="row.saving" type="warning" size="small">保存中</el-tag>
            <el-tag v-else-if="row.error" type="danger" size="small">失败</el-tag>
            <el-tag v-else type="info" size="small">待保存</el-tag>
          </template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button @click="showBatchSaveDialog = false" :disabled="batchSaving">取消</el-button>
        <el-button type="primary" @click="confirmBatchSave" :loading="batchSaving" :disabled="batchSaveItems.every(i => i.saved)">
          开始批量保存
        </el-button>
      </template>
    </el-dialog>

    <!-- Setup template dialog -->
    <el-dialog v-model="showSetupTemplateDialog" title="预置步骤模板管理" width="720px" :close-on-click-modal="false">
      <div style="margin-bottom: 12px;">
        <el-button type="primary" size="small" @click="openNewTemplate">+ 新建模板</el-button>
        <el-button size="small" @click="openTemplateConversionDialog">
          <el-icon><DocumentAdd /></el-icon>
          从 AI 用例转换
        </el-button>
      </div>
      <el-table :data="setupTemplates" size="small" max-height="400">
        <el-table-column prop="name" label="模板名称" min-width="150" />
        <el-table-column prop="description" label="说明" min-width="150" show-overflow-tooltip />
        <el-table-column prop="steps_count" label="步骤数" width="80" align="center" />
        <el-table-column prop="target_url" label="目标地址" min-width="180" show-overflow-tooltip />
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" @click="editTemplate(row)">编辑</el-button>
            <el-button size="small" type="danger" @click="deleteTemplate(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <el-dialog v-model="showTemplateConversionDialog" title="从 AI 用例转换为预置步骤模板" width="640px" :close-on-click-modal="false">
      <el-form label-width="92px">
        <el-form-item label="源用例" required>
          <el-select v-model="templateSourceCaseId" placeholder="请选择已有 AI 用例" filterable :loading="loadingTemplateSourceCases" style="width: 100%;">
            <el-option
              v-for="item in templateSourceCases"
              :key="item.id"
              :label="item.name"
              :value="item.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item v-if="selectedTemplateSourceCase" label="任务描述">
          <el-input :model-value="selectedTemplateSourceCase.task_description" type="textarea" :rows="5" readonly />
        </el-form-item>
      </el-form>
      <el-alert
        title="会按步骤编号提取内容并自动忽略以“断言、验证、校验、检查”开头的步骤。转换后仍可编辑。"
        type="info"
        :closable="false"
      />
      <template #footer>
        <el-button @click="showTemplateConversionDialog = false">取消</el-button>
        <el-button type="primary" @click="convertCaseToTemplate" :disabled="!selectedTemplateSourceCase">转换并编辑</el-button>
      </template>
    </el-dialog>

    <!-- Setup template form -->
    <el-dialog v-model="showTemplateFormDialog" :title="editingTemplateId ? '编辑预置步骤模板' : '新建预置步骤模板'" width="600px" :close-on-click-modal="false">
      <el-form :model="templateForm" label-width="80px">
        <el-form-item label="项目" required>
          <el-select v-model="templateForm.project" placeholder="请选择项目" filterable style="width: 100%;">
            <el-option
              v-for="p in projects"
              :key="p.id"
              :label="p.name"
              :value="p.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="名称" required>
          <el-input v-model="templateForm.name" placeholder="请输入模板名称" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="templateForm.description" placeholder="可选，补充模板用途" />
        </el-form-item>
        <el-form-item label="目标地址">
          <el-input v-model="templateForm.target_url" placeholder="例如 https://test-web.nn.com/" />
        </el-form-item>
        <el-form-item label="步骤" required>
          <div style="width: 100%;">
            <div v-for="(step, idx) in templateForm.steps" :key="idx" style="display: flex; gap: 8px; margin-bottom: 8px; align-items: center;">
              <span style="min-width: 24px; color: #909399;">{{ idx + 1 }}.</span>
              <el-input v-model="step.description" placeholder="请输入这一步的动作说明" style="flex: 1;" />
              <el-select
                v-model="step._variable_expression"
                placeholder="随机数据"
                style="width: 130px;"
                @change="expression => insertTemplateVariable(step, expression)"
              >
                <el-option
                  v-for="item in templateVariableOptions"
                  :key="item.expression"
                  :label="item.label"
                  :value="item.expression"
                />
              </el-select>
              <el-button size="small" type="danger" circle @click="templateForm.steps.splice(idx, 1)">
                <el-icon><Delete /></el-icon>
              </el-button>
            </div>
            <el-button size="small" @click="templateForm.steps.push({ description: '' })">+ 新增步骤</el-button>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showTemplateFormDialog = false">取消</el-button>
        <el-button type="primary" @click="saveTemplate" :loading="savingTemplate">保存</el-button>
      </template>
    </el-dialog>

  </div>
</template>


<script setup>
import { ref, reactive, onMounted, onUnmounted, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, VideoPlay, Edit, Delete, Upload, Setting, DocumentAdd } from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'
import {
  getAICases,
  updateAICase,
  previewAICaseAssertions,
  deleteAICase,
  batchDeleteAICases,
  batchEnableAICaseDualMode,
  batchEnableAICaseBrowserMode,
  batchConfigureAICaseSetupTemplate,
  runAICase,
  batchRunAICases,
  batchRecordAICases,
  getAIExecutionRecordDetail,
  saveAIRecording,
  getAIRecordingActions,
  importAICases,
  getUiProjects,
  getSetupTemplates, createSetupTemplate, updateSetupTemplate, deleteSetupTemplate,
  getAICaseCategories, createAICaseCategory, updateAICaseCategory, deleteAICaseCategory,
  batchConfigureAICaseCategory,
  getDesktopAppProfiles, createDesktopAppProfile, updateDesktopAppProfile, deleteDesktopAppProfile
} from '@/api/ui_automation'

const { t } = useI18n()
const router = useRouter()
const cases = ref([])
const loading = ref(false)
const searchText = ref('')
const total = ref(0)
const categories = ref([])
const categoriesLoading = ref(false)
const selectedCategoryId = ref(null)
const pagination = reactive({
  currentPage: 1,
  pageSize: 20
})

const showEditDialog = ref(false)
const saving = ref(false)
const currentCaseId = ref(null)
const editForm = reactive({
  name: '',
  description: '',
  task_description: '',
  web_task_description: '',
  desktop_task_description: '',
  execution_target: 'web',
  desktop_app_profile: null,
  setup_template: null,
  category: null
})
const desktopConfigText = ref('{}')
const dualTaskTab = ref('web')
const desktopAppProfiles = ref([])
const desktopAppsLoading = ref(false)
const showDesktopAppDialog = ref(false)
const savingDesktopApp = ref(false)
const editingDesktopAppId = ref(null)
const desktopAppForm = reactive({
  name: '',
  executable_path: '',
  process_name: '',
  arguments: '',
  work_dir: '',
  window_title_regex: '',
  backend: 'uia',
  is_active: true
})
const editFormRef = ref(null)
const assertionPreview = ref(null)
const assertionPreviewLoading = ref(false)

const projects = ref([])
const showCategoryDialog = ref(false)
const showCategoryFormDialog = ref(false)
const savingCategory = ref(false)
const editingCategoryId = ref(null)
const categoryForm = reactive({
  name: '',
  description: '',
  sort_order: 0
})
const showImportDialog = ref(false)
const importing = ref(false)
const importFormRef = ref(null)
const importForm = reactive({
  project_id: null,
  category_id: null,
  file: null
})


// 闂佸綊娼х紞濠囧闯妤﹁￥浜归柡鍥╁仜閻撴垿鏌ｅΟ鍨厫闁?
const selectedCases = ref([])
const batchDeleting = ref(false)
const batchEnablingDualMode = ref(false)
const batchEnablingBrowserMode = ref(false)
const showBatchTemplateDialog = ref(false)
const batchConfiguringTemplate = ref(false)
const batchTemplateMode = ref('set')
const batchTemplateId = ref(null)
const showBatchCategoryDialog = ref(false)
const batchConfiguringCategory = ref(false)
const batchCategoryId = ref(null)
const showBatchDialog = ref(false)
const batchRunning = ref(false)
const showBatchRunModeDialog = ref(false)
const batchRunMode = ref('sequential')
const batchExecutionTarget = ref('web')
const batchRecords = ref([])
const batchTotal = ref(0)
const batchCurrentIndex = ref(0)
const batchProgress = ref(0)
const batchStartedAt = ref(null)
const batchElapsedSeconds = ref(0)
const batchTotalDuration = ref(null)
let batchPollTimer = null
let batchElapsedTimer = null

// 濠殿噯绲界换瀣煂濠婂牊鍋ㄩ柕濞垮€楁导鎰版煟閵娿儱顏褏鏅幃鏉跨暆閳ь剚鎱ㄩ幖浣哥畱濞达絽鎲＄€氱潪I閻熸粎澧楀ú鏍春濡ゅ啩鐒婇弶鍫氭櫅瀹曟洟鏌ｅΟ鍨厫闁?
const caseRunningStatus = reactive({})
const caseAIRecordReady = reactive({})
const batchSaving = ref(false)
const showBatchSaveDialog = ref(false)

// Setup Template state
const showSetupTemplateDialog = ref(false)
const showTemplateFormDialog = ref(false)
const showTemplateConversionDialog = ref(false)
const setupTemplates = ref([])
const savingTemplate = ref(false)
const editingTemplateId = ref(null)
const templateSourceCases = ref([])
const templateSourceCaseId = ref(null)
const loadingTemplateSourceCases = ref(false)
const templateForm = reactive({
  name: '',
  description: '',
  target_url: '',
  project: null,
  steps: [{ description: '' }]
})
const batchSaveItems = reactive([])

const completedBatchRecords = computed(() => {
  return batchRecords.value.filter(r => r.execution_id && (r.status === 'passed' || r.status === 'failed'))
})
const hasCompletedBatchRecords = computed(() => completedBatchRecords.value.length > 0)
const completedBatchCount = computed(() => completedBatchRecords.value.length)
const batchDurationText = computed(() => {
  const duration = batchTotalDuration.value ?? batchElapsedSeconds.value
  if (!Number.isFinite(duration)) return '-'
  if (duration < 60) return `${duration.toFixed(1)}s`
  const minutes = Math.floor(duration / 60)
  return `${minutes}m ${Math.floor(duration % 60)}s`
})
const selectedTemplateSourceCase = computed(() => {
  return templateSourceCases.value.find(item => item.id === templateSourceCaseId.value) || null
})
const categoriesForCurrentCase = computed(() => {
  return categories.value
})
const batchCategoryOptions = computed(() => {
  return categories.value
})
const categoriesForImportProject = computed(() => {
  return categories.value
})

// 閻熸粎澧楀ú鏍春濡ゅ啠鍋撻崗澶婂⒉闁绘濞婇幃鈺呮嚋绾版ê浜?
const showReviewDialog = ref(false)
const reviewActiveTab = ref(0)
const reviewRecords = ref([])
const savingRecording = ref(false)

// AI閻熸粎澧楀ú鏍春濡ゅ懏鏅柛顐ゅ枎缁€瀣煙閻熼偊妲搁柛妯绘尵濡叉劙鎮崨顖滎槴闂佺粯顭堥崺鏍焵?
const showAIRecordDialog = ref(false)
const aiRecordLoading = ref(false)
const aiRecordSaving = ref(false)
const aiRecordingActions = ref([])
const aiRecordForm = reactive({
  projectId: null,
  testCaseName: ''
})
const currentAIRecordId = ref(null)

const formRules = computed(() => ({
  name: [{ required: true, message: t('uiAutomation.ai.rules.nameRequired'), trigger: 'blur' }],
  task_description: editForm.execution_target === 'dual'
    ? []
    : [{ required: true, message: t('uiAutomation.ai.caseList.rules.taskDescriptionRequired'), trigger: 'blur' }]
}))

const activeTaskDescription = computed(() => {
  if (editForm.execution_target !== 'dual') return editForm.task_description
  return dualTaskTab.value === 'desktop' ? editForm.desktop_task_description : editForm.web_task_description
})

const importRules = computed(() => ({
  project_id: [{ required: true, message: '请选择项目', trigger: 'change' }],
  file: [{ required: true, message: '请先选择要导入的文件', trigger: 'change' }]
}))


const loadProjects = async () => {
  try {
    const response = await getUiProjects({ page_size: 1000 })
    projects.value = response.data.results || response.data || []
  } catch (error) {
    console.error('闂佸吋鍎抽崲鑼躲亹閸ャ劊浜滈柛锔诲幗缁愭鏌涢幒鎿冩畽闁靛棗鍟鍕綇椤愩儛?', error)
    ElMessage.error('加载项目列表失败')
  }
}

const loadCategories = async () => {
  categoriesLoading.value = true
  try {
    const response = await getAICaseCategories({ page_size: 1000 })
    categories.value = response.data?.results || response.data || []
  } catch (error) {
    console.error('加载功能分类失败:', error)
    ElMessage.error('加载功能分类失败')
  } finally {
    categoriesLoading.value = false
  }
}

const loadDesktopAppProfiles = async () => {
  desktopAppsLoading.value = true
  try {
    const response = await getDesktopAppProfiles({ page_size: 1000, ordering: 'name' })
    desktopAppProfiles.value = response.data?.results || response.data || []
  } catch (error) {
    console.error('加载桌面应用失败:', error)
    ElMessage.error('加载桌面应用失败')
  } finally {
    desktopAppsLoading.value = false
  }
}

const resetDesktopAppForm = () => {
  editingDesktopAppId.value = null
  Object.assign(desktopAppForm, {
    name: '', executable_path: '', process_name: '', arguments: '', work_dir: '',
    window_title_regex: '', backend: 'uia', is_active: true
  })
}

const openDesktopAppDialog = async () => {
  await loadDesktopAppProfiles()
  resetDesktopAppForm()
  showDesktopAppDialog.value = true
}

const editDesktopApp = (profile) => {
  editingDesktopAppId.value = profile.id
  Object.assign(desktopAppForm, {
    name: profile.name || '',
    executable_path: profile.executable_path || '',
    process_name: profile.process_name || '',
    arguments: profile.arguments || '',
    work_dir: profile.work_dir || '',
    window_title_regex: profile.window_title_regex || '',
    backend: profile.backend || 'uia',
    is_active: profile.is_active !== false
  })
  ElMessage.info(`正在编辑桌面应用：${profile.name || profile.id}`)
}

const saveDesktopApp = async () => {
  if (!desktopAppForm.name.trim()) {
    ElMessage.warning('请输入应用名称')
    return
  }
  if (!desktopAppForm.executable_path.trim() && !desktopAppForm.process_name.trim()) {
    ElMessage.warning('至少填写程序路径或进程名')
    return
  }
  savingDesktopApp.value = true
  try {
    const payload = {
      ...desktopAppForm,
      name: desktopAppForm.name.trim(),
      executable_path: desktopAppForm.executable_path.trim(),
      process_name: desktopAppForm.process_name.trim(),
      arguments: desktopAppForm.arguments.trim(),
      work_dir: desktopAppForm.work_dir.trim(),
      window_title_regex: desktopAppForm.window_title_regex.trim()
    }
    if (editingDesktopAppId.value) {
      await updateDesktopAppProfile(editingDesktopAppId.value, payload)
      ElMessage.success('桌面应用已更新')
    } else {
      await createDesktopAppProfile(payload)
      ElMessage.success('桌面应用已新增')
    }
    await loadDesktopAppProfiles()
    resetDesktopAppForm()
  } catch (error) {
    ElMessage.error(error.response?.data?.name?.[0] || error.response?.data?.detail || '保存桌面应用失败')
  } finally {
    savingDesktopApp.value = false
  }
}

const deleteDesktopApp = async (profile) => {
  try {
    await ElMessageBox.confirm(`删除桌面应用“${profile.name}”后，关联用例将不再自动启动该客户端。`, '删除桌面应用', { type: 'warning' })
    await deleteDesktopAppProfile(profile.id)
    if (editForm.desktop_app_profile === profile.id) editForm.desktop_app_profile = null
    await loadDesktopAppProfiles()
    ElMessage.success('桌面应用已删除')
  } catch (error) {
    if (error !== 'cancel') ElMessage.error('删除桌面应用失败')
  }
}

const formatCategoryOption = (category) => {
  return category.name
}

const handleCategoryFilterChange = () => {
  pagination.currentPage = 1
  loadCases()
}

const openCategoryDialog = async () => {
  if (!projects.value.length) await loadProjects()
  await loadCategories()
  showCategoryDialog.value = true
}

const openNewCategoryForm = () => {
  editingCategoryId.value = null
  categoryForm.name = ''
  categoryForm.description = ''
  categoryForm.sort_order = 0
  showCategoryFormDialog.value = true
}

const editCategory = (category) => {
  editingCategoryId.value = category.id
  categoryForm.name = category.name || ''
  categoryForm.description = category.description || ''
  categoryForm.sort_order = category.sort_order || 0
  showCategoryFormDialog.value = true
}

const viewCategoryCases = (category) => {
  selectedCategoryId.value = category.id
  pagination.currentPage = 1
  showCategoryDialog.value = false
  loadCases()
}

const openCategoryManagerForCurrentCase = async () => {
  await openCategoryDialog()
  openNewCategoryForm()
}

const saveCategory = async () => {
  if (!categoryForm.name.trim()) {
    ElMessage.warning('请输入分类名称')
    return
  }
  savingCategory.value = true
  try {
    const payload = {
      name: categoryForm.name.trim(),
      description: categoryForm.description.trim(),
      sort_order: categoryForm.sort_order || 0
    }
    if (editingCategoryId.value) {
      await updateAICaseCategory(editingCategoryId.value, payload)
      ElMessage.success('功能分类已更新')
    } else {
      await createAICaseCategory(payload)
      ElMessage.success('功能分类已创建')
    }
    showCategoryFormDialog.value = false
    await loadCategories()
    loadCases()
  } catch (error) {
    const detail = error.response?.data?.name?.[0] || error.response?.data?.detail || '保存功能分类失败'
    ElMessage.error(detail)
  } finally {
    savingCategory.value = false
  }
}

const deleteCategory = async (category) => {
  try {
    await ElMessageBox.confirm(
      `删除“${category.name}”后，该分类下的用例会保留并变为未分类。`,
      '删除功能分类',
      { type: 'warning' }
    )
    await deleteAICaseCategory(category.id)
    ElMessage.success('功能分类已删除')
    if (selectedCategoryId.value === category.id) selectedCategoryId.value = null
    await loadCategories()
    loadCases()
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('删除功能分类失败')
    }
  }
}

const openBatchCategoryDialog = async () => {
  if (!categories.value.length) await loadCategories()
  batchCategoryId.value = null
  showBatchCategoryDialog.value = true
}

const confirmBatchCategory = async (clearCategory) => {
  if (!clearCategory && !batchCategoryId.value) {
    ElMessage.warning('请选择功能分类')
    return
  }
  batchConfiguringCategory.value = true
  try {
    const response = await batchConfigureAICaseCategory({
      ids: selectedCases.value.map(item => item.id),
      category_id: clearCategory ? null : batchCategoryId.value
    })
    ElMessage.success(response.data?.message || '批量归类完成')
    showBatchCategoryDialog.value = false
    selectedCases.value = []
    loadCategories()
    loadCases()
  } catch (error) {
    ElMessage.error(error.response?.data?.error || '批量归类失败')
  } finally {
    batchConfiguringCategory.value = false
  }
}

const openImportDialog = async () => {
  if (!projects.value.length) {
    await loadProjects()
  }
  importForm.project_id = projects.value[0]?.id || null
  importForm.category_id = null
  importForm.file = null
  await loadCategories()
  showImportDialog.value = true
}

const handleImportFileChange = (uploadFile) => {
  importForm.file = uploadFile.raw
}

const handleImportFileRemove = () => {
  importForm.file = null
}

const confirmImport = async () => {
  if (!importFormRef.value) return
  await importFormRef.value.validate(async (valid) => {
    if (!valid) return
    importing.value = true
    try {
      const formData = new FormData()
      formData.append('project_id', importForm.project_id)
      if (importForm.category_id) formData.append('category_id', importForm.category_id)
      formData.append('file', importForm.file)
      const response = await importAICases(formData)
      const created = response.data.created_count || 0
      const failed = response.data.error_count || 0
      if (failed > 0) {
        ElMessage.warning(`导入完成，成功 ${created} 条，失败 ${failed} 条`)
      } else {
        ElMessage.success(`导入完成，成功创建 ${created} 条用例`)
      }
      showImportDialog.value = false
      pagination.currentPage = 1
      loadCases()
    } catch (error) {
      console.error('AI闂佹椿娼块崝瀣閵壯€鍋撻悽闈涘付闁告瑥妫欏鍕綇椤愩儛?', error)
      ElMessage.error(error.response?.data?.error || '闁诲海鏁搁崢褔宕ｉ崱妯虹窞閺夊牜鍋夎')
    } finally {
      importing.value = false
    }
  })
}

// 闂佸憡姊绘慨鎯归崶顒佸仺闁靛鍊楁导鎰版煕閹烘搩娈欓柕?
const loadCases = async () => {
  loading.value = true
  try {
    const response = await getAICases({
      page: pagination.currentPage,
      page_size: pagination.pageSize,
      search: searchText.value,
      ...(selectedCategoryId.value ? { category: selectedCategoryId.value } : {})
    })

    cases.value = response.data.results || []
    total.value = response.data.count || 0
  } catch (error) {
    console.error('闂佸吋鍎抽崲鑼躲亹閸ヮ剚鍋ㄩ柕濞垮€楁导鎰版煕閹烘搩娈欓柕鍡楀暞瀵板嫭娼忛銉?', error)
    ElMessage.error(t('uiAutomation.ai.caseList.messages.loadFailed'))
  } finally {
    loading.value = false
  }
}

const handleSearch = () => {
  pagination.currentPage = 1
  loadCases()
}

const handleSizeChange = () => {
  pagination.currentPage = 1
  loadCases()
}

const handleCurrentChange = () => {
  loadCases()
}

// 缂傚倸鍊归悧鐐垫椤愶附鍋ㄩ柕濞垮€楁导?
const runCase = async (row, executionTarget = null) => {
  try {
    await runAICase(row.id, executionTarget ? { execution_target: executionTarget } : {})
    ElMessage.success(t('uiAutomation.ai.caseList.messages.runSuccess'))
    router.push('/ai-intelligent-mode/execution-records')
  } catch (error) {
    console.error('执行失败:', error)
    ElMessage.error(t('uiAutomation.ai.caseList.messages.runFailed'))
  }
}

const editCase = (row) => {
  currentCaseId.value = row.id
  editForm.name = row.name
  editForm.description = row.description
  editForm.task_description = row.task_description
  editForm.web_task_description = row.web_task_description || (
    row.execution_target === 'web' || row.execution_target === 'dual'
      ? row.task_description
      : ''
  )
  editForm.desktop_task_description = row.desktop_task_description || (row.execution_target === 'desktop' ? row.task_description : '')
  editForm.execution_target = row.execution_target || 'web'
  dualTaskTab.value = 'web'
  editForm.desktop_app_profile = row.desktop_app_profile || null
  desktopConfigText.value = JSON.stringify(row.desktop_config || {}, null, 2)
  editForm.setup_template = row.setup_template || null
  editForm.category = row.category || null
  assertionPreview.value = null
  showEditDialog.value = true
  loadSetupTemplates()
  loadDesktopAppProfiles()
  loadAssertionPreview()
}

const formatAssertionContract = (contract) => {
  if (contract?.kind === 'review_required') return '无法安全自动验证'
  if (contract?.kind === 'assertion_plan') {
    return (contract.predicates || []).map(item => item.kind).join(' + ') || '断言计划'
  }
  return contract?.kind || '断言计划'
}

const loadAssertionPreview = async () => {
  const taskDescription = activeTaskDescription.value?.trim()
  if (!currentCaseId.value || !taskDescription) return
  assertionPreviewLoading.value = true
  try {
    const response = await previewAICaseAssertions(currentCaseId.value, {
      task_description: taskDescription
    })
    assertionPreview.value = response.data
  } catch (error) {
    console.error('断言预检失败:', error)
    ElMessage.error('断言预检失败')
  } finally {
    assertionPreviewLoading.value = false
  }
}

const confirmEdit = async () => {
  if (!editFormRef.value) return

  await editFormRef.value.validate(async (valid) => {
    if (valid) {
      if (editForm.execution_target === 'dual' && (!editForm.web_task_description.trim() || !editForm.desktop_task_description.trim())) {
        ElMessage.warning('请分别填写浏览器和 Windows 用例')
        return
      }
      let desktopConfig = {}
      if (editForm.execution_target === 'desktop' || editForm.execution_target === 'dual') {
        try {
          desktopConfig = JSON.parse(desktopConfigText.value || '{}')
        } catch {
          ElMessage.error('桌面配置必须是有效的 JSON')
          return
        }
      }
      saving.value = true
      try {
        const taskDescription = editForm.execution_target === 'dual'
          ? editForm.web_task_description
          : editForm.execution_target === 'desktop'
            ? (editForm.desktop_task_description || editForm.task_description)
            : editForm.task_description
        const desktopTaskDescription = editForm.execution_target === 'web'
          ? ''
          : (editForm.desktop_task_description || taskDescription)
        await updateAICase(currentCaseId.value, {
          name: editForm.name,
          description: editForm.description,
          task_description: taskDescription,
          web_task_description: editForm.execution_target === 'dual' ? editForm.web_task_description : '',
          desktop_task_description: desktopTaskDescription,
          execution_target: editForm.execution_target,
          desktop_config: desktopConfig,
          desktop_app_profile: editForm.desktop_app_profile,
          setup_template: editForm.setup_template,
          category: editForm.category
        })

        ElMessage.success(t('uiAutomation.ai.caseList.messages.updateSuccess'))
        showEditDialog.value = false
        loadCases()
      } catch (error) {
        console.error('闂佸搫娲ら悺銊╁蓟婵犲啫绶為弶鍫亯琚?', error)
        const responseData = error.response?.data
        const fieldErrors = responseData && typeof responseData === 'object'
          ? Object.entries(responseData)
            .map(([field, messages]) => `${field}: ${Array.isArray(messages) ? messages.join('；') : messages}`)
            .join('；')
          : ''
        ElMessage.error(fieldErrors || t('uiAutomation.ai.caseList.messages.updateFailed'))
      } finally {
        saving.value = false
      }
    }
  })
}

// 闂佸憡甯炴繛鈧繛鍛叄閹粙濡搁妶鍥︾矗
const deleteCase = async (id) => {
  try {
    await ElMessageBox.confirm(
      t('uiAutomation.ai.caseList.messages.deleteConfirm'),
      t('uiAutomation.messages.confirm.tip'),
      {
        confirmButtonText: t('uiAutomation.common.confirm'),
        cancelButtonText: t('uiAutomation.common.cancel'),
        type: 'warning'
      }
    )

    await deleteAICase(id)
    ElMessage.success(t('uiAutomation.ai.caseList.messages.deleteSuccess'))
    loadCases()
  } catch (error) {
    if (error !== 'cancel') {
      console.error('闂佸憡甯炴繛鈧繛鍛瀵板嫭娼忛銉?', error)
      ElMessage.error(t('uiAutomation.ai.caseList.messages.deleteFailed'))
    }
  }
}

// 闂佸湱鐟抽崱鈺傛杸闂佹椿娼块崝瀣?
const getExecutionStatusLabel = (status) => {
  const statusMap = {
    passed: 'Passed',
    failed: 'Failed',
    error: 'Error',
    running: 'Running',
    pending: 'Pending'
  }
  return statusMap[status] || 'Never Run'
}


const formatSimpleDate = (value) => {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false
  })
}

const formatDate = (_row, _column, cellValue) => {
  if (!cellValue) return '-'
  const date = new Date(cellValue)
  if (Number.isNaN(date.getTime())) return cellValue
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false
  })
}
const getExecutionStatusTagType = (status) => {
  const statusMap = {
    passed: 'success',
    failed: 'danger',
    error: 'danger',
    running: 'warning',
    pending: 'info'
  }
  return statusMap[status] || 'info'
}


// 婢舵岸鈧褰夐崠?
const handleSelectionChange = (selection) => {
  selectedCases.value = selection
}

const openBatchTemplateDialog = async () => {
  if (!selectedCases.value.length) return
  await loadSetupTemplates()
  const currentTemplateIds = [...new Set(
    selectedCases.value.map(item => item.setup_template ?? null)
  )]
  batchTemplateMode.value = 'set'
  batchTemplateId.value = currentTemplateIds.length === 1 ? currentTemplateIds[0] : null
  showBatchTemplateDialog.value = true
}

const confirmBatchTemplate = async () => {
  if (!selectedCases.value.length) return
  if (batchTemplateMode.value === 'set') {
    if (!batchTemplateId.value) {
      ElMessage.warning('请选择要配置的预置模板')
      return
    }
  }

  batchConfiguringTemplate.value = true
  try {
    const response = await batchConfigureAICaseSetupTemplate({
      ids: selectedCases.value.map(item => item.id),
      setup_template_id: batchTemplateMode.value === 'clear' ? null : batchTemplateId.value
    })
    ElMessage.success(response.data.message || `已更新 ${response.data.updated_count || 0} 条 AI 用例`)
    showBatchTemplateDialog.value = false
    selectedCases.value = []
    await loadCases()
  } catch (error) {
    console.error('批量配置预置模板失败:', error)
    ElMessage.error(error.response?.data?.error || '批量配置预置模板失败')
  } finally {
    batchConfiguringTemplate.value = false
  }
}

const batchDeleteSelectedCases = async () => {
  if (!selectedCases.value.length) return

  try {
    await ElMessageBox.confirm(
      `确定删除已选中的 ${selectedCases.value.length} 条 AI 用例吗？删除后无法恢复。`,
      '批量删除 AI 用例',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }
    )
  } catch {
    return
  }

  batchDeleting.value = true
  try {
    const response = await batchDeleteAICases({ ids: selectedCases.value.map(item => item.id) })
    ElMessage.success(`已删除 ${response.data.deleted_count || 0} 条 AI 用例`)
    selectedCases.value = []
    if (cases.value.length === 1 && pagination.currentPage > 1) {
      pagination.currentPage -= 1
    }
    await loadCases()
  } catch (error) {
    console.error('批量删除 AI 用例失败:', error)
    ElMessage.error(error.response?.data?.error || '批量删除 AI 用例失败')
  } finally {
    batchDeleting.value = false
  }
}

const enableSelectedCasesDualMode = async () => {
  const caseIds = selectedCases.value.map(item => item.id)
  if (!caseIds.length) return
  try {
    await ElMessageBox.confirm(
      '将保留原浏览器用例，并为包含 NN 社区地址的用例生成 Windows 版。无法映射社区地址的用例会跳过。',
      '批量生成 Windows 版',
      { type: 'warning' }
    )
  } catch {
    return
  }
  batchEnablingDualMode.value = true
  try {
    const response = await batchEnableAICaseDualMode({ ids: caseIds })
    const { converted_count = 0, skipped_count = 0, message } = response.data || {}
    ElMessage.success(message || `已生成 ${converted_count} 条 Windows 版${skipped_count ? `，跳过 ${skipped_count} 条无需处理或无法映射的用例` : ''}`)
    selectedCases.value = []
    await loadCases()
  } catch (error) {
    console.error('批量生成 Windows 版失败:', error)
    ElMessage.error(error.response?.data?.error || '批量生成 Windows 版失败')
  } finally {
    batchEnablingDualMode.value = false
  }
}

// 閹靛綊鍣鸿ぐ鏇炲煑
const enableSelectedCasesBrowserMode = async () => {
  const caseIds = selectedCases.value.map(item => item.id)
  if (!caseIds.length) return
  try {
    await ElMessageBox.confirm(
      '将保留原 Windows 用例，并为包含 NN 社区地址的用例生成独立浏览器版。浏览器版会使用项目中已有的 NN Web 域名。',
      '批量生成浏览器版',
      { type: 'warning' }
    )
  } catch {
    return
  }
  batchEnablingBrowserMode.value = true
  try {
    const response = await batchEnableAICaseBrowserMode({ ids: caseIds })
    const { converted_count = 0, skipped_count = 0, message } = response.data || {}
    ElMessage.success(message || `已生成 ${converted_count} 条浏览器版${skipped_count ? `，跳过 ${skipped_count} 条已有浏览器版或无法映射的用例` : ''}`)
    selectedCases.value = []
    await loadCases()
  } catch (error) {
    console.error('批量生成浏览器版失败:', error)
    ElMessage.error(error.response?.data?.error || '批量生成浏览器版失败')
  } finally {
    batchEnablingBrowserMode.value = false
  }
}

const startBatchRun = () => {
  if (selectedCases.value.length === 0) return
  batchRunMode.value = 'sequential'
  const selectedTargets = new Set(selectedCases.value.map(item => item.execution_target || 'web'))
  batchExecutionTarget.value = selectedTargets.size === 1 && selectedTargets.has('desktop')
    ? 'desktop'
    : 'web'
  showBatchRunModeDialog.value = true
}

const confirmBatchRun = async () => {
  if (selectedCases.value.length === 0) return
  showBatchRunModeDialog.value = false
  batchRunning.value = true
  // 濠电偞鎸搁幊妯衡枍鎼淬垻鈻曢悗锝庝簻椤ゅ懘鏌ｉ妸銉ユ畼I閻熸粎澧楀ú鏍春濡ゅ啩鐒婇弶鍫氭櫅瀹曟洟鏌ｅΟ鍨厫闁?
  Object.keys(caseAIRecordReady).forEach(k => delete caseAIRecordReady[k])
  // 闂佸搫绉村ú鈺咁敊閸ヮ剚鐒诲璺侯槼閸橆剟鏌ｉ妸銉ヮ伀闁轰降鍊栫粭鐔衡偓锝傛櫈缁€瀣煙缁楁稑妫弨钘夆槈?
  selectedCases.value.forEach(c => { caseRunningStatus[c.id] = true })
  batchRecords.value = selectedCases.value.map(c => ({
    case_name: c.name,
    case_id: c.id,
    status: batchRunMode.value === 'concurrent' ? 'running' : 'pending',
    duration: null
  }))
  batchTotal.value = batchRecords.value.length
  batchCurrentIndex.value = 0
  batchProgress.value = 0
  batchStartedAt.value = new Date().toISOString()
  batchElapsedSeconds.value = 0
  batchTotalDuration.value = null
  startBatchElapsedTimer()
  showBatchDialog.value = true

  try {
    const caseIds = selectedCases.value.map(c => c.id)
    const response = await batchRecordAICases({
      case_ids: caseIds,
      run_mode: batchRunMode.value,
      execution_target: batchExecutionTarget.value
    })
    const records = response.data.records || []
    if (response.data.batch_started_at) {
      batchStartedAt.value = response.data.batch_started_at
      refreshBatchElapsedTime()
    }
    const recordByCaseId = new Map(records.map(record => [record.case_id, record]))
    const orderedRecords = []
    batchRecords.value.forEach(row => {
      const record = recordByCaseId.get(row.case_id)
      if (!record) return
      row.execution_id = record.id
      row.status = record.status || row.status
      orderedRecords.push(record)
    })
    batchCurrentIndex.value = 0
    batchProgress.value = 0

    // 闁哄鍎愰崰娑㈩敋濡ゅ懎绠ラ柍褜鍓熷鍨緞鐎ｎ亖鎸冮柣鐐寸☉閻線顢欓崶顏備汗闁哄洨濮寸瑧闂?
    startBatchPoll(orderedRecords)
  } catch (error) {
    console.error('闂佸綊娼х紞濠囧闯濞差亜绠ョ憸鎴︺€侀幋鐐茬窞閺夊牜鍋夎:', error)
    ElMessage.error(error.response?.data?.error || '批量运行启动失败，请检查执行日志')
    stopBatchElapsedTimer()
    batchRunning.value = false
  }
}

const startBatchPoll = (records) => {
  if (batchPollTimer) clearInterval(batchPollTimer)
  let completed = 0
  const total = records.length

  batchPollTimer = setInterval(async () => {
    try {
      let allDone = true
      for (let i = 0; i < records.length; i++) {
        const r = records[i]
        if (batchRecords.value[i].status === 'running' || batchRecords.value[i].status === 'pending') {
          const resp = await getAIExecutionRecordDetail(r.id)
          const rec = resp.data
          if (rec && rec.status && rec.status !== 'running' && rec.status !== 'pending') {
            batchRecords.value[i].status = rec.status
            batchRecords.value[i].duration = rec.duration
            batchRecords.value[i].end_time = rec.end_time
            // 闂佸搫娲ら悺銊╁蓟婵犲倐鎺曠疀濮樺吋鏂€闂佹椿娼块崝瀣閵夆晜鍋愰柤鍝ヮ暯閸嬫挻绗熸繝鍕崶闂佸憡鐟﹂悧妤冪矓閻戣棄绠ョ憸鎴︺€侀幋鐐碘枖妞ゆ挶鍔庣粈澶愭煛瀹ュ懏绌挎い鏂挎I閻熸粎澧楀ú鏍春濡ゅ啩鐒婇弶鍫氭櫅瀹?
            const caseId = batchRecords.value[i].case_id
            if (caseId) {
              caseRunningStatus[caseId] = false
              caseAIRecordReady[caseId] = true
            }
            batchCurrentIndex.value = i + 1
            completed++
          } else {
            allDone = false
          }
        }
      }
      batchProgress.value = Math.round((completed / total) * 100)
      if (allDone || completed >= total) {
        clearInterval(batchPollTimer)
        batchPollTimer = null
        finishBatchElapsedTimer()
        batchRunning.value = false
        ElMessage.success(`批量录制完成，共完成 ${completed}/${total} 条用例`)
      }
    } catch (e) {
      console.error('闁哄鍎愰崰娑㈩敋濡ゅ懏鍋愰柤鍝ヮ暯閸嬫挻鎷呴幖鐐版澀闁?', e)
    }
  }, 3000)
}

// 闂佸綊娼х紞濠囧闯妤﹁￥浜归柡鍥╁仜閻撴垿寮堕悜鍡楁灕妞ゆ洘顨婇弫宥夊醇濠靛牊娈梺鐟扮摠閸旀洟骞冨Δ浣逛氦婵炴垶锚瀵娊鎮楅崗澶婂⒉闁绘濞婇弫?
const startBatchPollForReview = (records) => {
  if (batchPollTimer) clearInterval(batchPollTimer)
  let completed = 0
  const total = records.length

  batchPollTimer = setInterval(async () => {
    try {
      let allDone = true
      for (let i = 0; i < records.length; i++) {
        const r = records[i]
        if (batchRecords.value[i].status === 'running' || batchRecords.value[i].status === 'pending') {
          const resp = await getAIExecutionRecordDetail(r.id)
          const rec = resp.data
          if (rec && rec.status && rec.status !== 'running' && rec.status !== 'pending') {
            batchRecords.value[i].status = rec.status
            batchRecords.value[i].duration = rec.duration
            batchCurrentIndex.value = i + 1
            completed++
          } else {
            allDone = false
          }
        }
      }
      batchProgress.value = Math.round((completed / total) * 100)
      if (allDone || completed >= total) {
        clearInterval(batchPollTimer)
        batchPollTimer = null
        finishBatchElapsedTimer()
        batchRunning.value = false
        ElMessage.success(`批量录制完成，共完成 ${completed}/${total} 条用例`)
        // 闂佺厧顨庢禍婊勬叏閳哄倹浜ゆ繛鎴灻鎶芥倵閸忓澧查柣?
        await loadReviewData(records)
      }
    } catch (e) {
      console.error('闁哄鍎愰崰娑㈩敋濡ゅ懏鍋愰柤鍝ヮ暯閸嬫挻鎷呴幖鐐版澀闁?', e)
    }
  }, 3000)
}

// 闂佸憡姊绘慨鎯归崶鈹惧亾閸忓澧查柣妤佸▕瀵偊鎮ч崼婵堛偊
const loadReviewData = async (records) => {
  const reviewData = []
  for (const r of records) {
    try {
      const resp = await getAIExecutionRecordDetail(r.id)
      const rec = resp.data
      const steps = rec.steps_completed || []
      // 闁哄鏅涘ú锕傚箮閵堝绠?goto 濠殿喗绺块崕鐢割敁閸愵喗鏅柛锔炬緪L闁荤姳绀佸鈥澄涢懜鐢碘枖鐎广儱顦版禒姗€鎮烽弴姘樂缂佺粯姘ㄩ埀顒佺⊕鐪夐悹鎰枎椤垽濡烽埡濞惧亾閸愵喗鏅?
      const filteredSteps = steps.filter(s => s.action_type !== 'goto')
      reviewData.push({
        record_id: r.id,
        case_name: rec.case_name || r.case_name,
        project_id: rec.project_id,
        status: rec.status,
        steps: filteredSteps.map((s, i) => ({
          ...s,
          step_number: i + 1,
          included: s.status === 'completed',
          // 婵?element 婵炴垶鎼╅崢鍊熴亹娓氣偓瀹曪綁寮借閺嗘澘霉閿濆懐孝婵炲懏甯楃粚閬嶅焺閸愌呯
          locator_value: s.element?.locator_value || '',
          locator_strategy: s.element?.locator_strategy || 'css',
          element_name: s.element?.name || s.element?.placeholder || s.element?.text || '',
          element_tag: s.element?.tag || '',
          element_id: s.element?.id || '',
          element_class: s.element?.className || '',
          screenshot_b64: s.screenshot || null,
          // 缂傚倸鍊归悧鐐垫椤愶附鍋?
          _edit_locator: s.element?.locator_value || '',
        }))
      })
    } catch (e) {
      console.error('闂佸吋鍎抽崲鑼躲亹閸ヮ亗浜归柡鍥╁仜閻撴垿鎮归崶鐑芥闁稿骸绻戝鍕綇椤愩儛?', e)
    }
  }
  reviewRecords.value = reviewData
  if (reviewData.length > 0) {
    showBatchDialog.value = false
    showReviewDialog.value = true
    reviewActiveTab.value = 0
  }
}

// 闂佸憡甯掑ú锕€鐣烽幓鎺濇桨闁靛鏅╅埀顒€鍟村畷鐘诲川椤撶喎鍓甸梺缁橆焾閸╂牠鍩€?
const toggleStepIncluded = (recordIndex, stepIndex) => {
  const step = reviewRecords.value[recordIndex].steps[stepIndex]
  step.included = !step.included
}

// 婵烇絽娲︾换鍌炴偤閵娿劊浜归柡鍥╁仜閻撴垹绱撴担瑙勫鞍闁诲繐顦扮粙澶屽姬椤ゅ繘鏌ｉ～顒€濡虹紒?
const saveRecordingResults = async () => {
  savingRecording.value = true
  try {
    let totalSaved = 0
    for (const record of reviewRecords.value) {
      const includedSteps = record.steps.filter(s => s.included)
      if (includedSteps.length === 0) continue

      const actions = includedSteps.map((s, i) => ({
        step_number: i + 1,
        action_type: s.action_type === 'try_click' ? 'click' : (s.action_type === 'type' ? 'fill' : s.action_type),
        description: s.description || '',
        input_value: s.input_value || '',
        element_name: s.element_name || `录制步骤_${i + 1}`,
        locator_strategy: s.locator_strategy || 'css',
        locator_value: s._edit_locator || s.locator_value || '',
        element_type: s.element_tag === 'button' ? 'BUTTON' : (s.element_tag === 'input' ? 'INPUT' : 'BUTTON'),
        is_optional: s.action_type === 'try_click',
        optional_note: s.action_type === 'try_click' ? '可选点击步骤，执行失败时允许继续后续操作' : '',
        assert_type: s.action_type === 'assert' ? 'textContains' : '',
        assert_value: s.action_type === 'assert' ? (s.description || '') : '',
        wait_time: 1000,
      }))

      try {
        const resp = await saveAIRecording(record.record_id, {
          project_id: record.project_id,
          case_name: record.case_name + ' - AI录制',
          actions: actions,
        })
        totalSaved++
      } catch (e) {
        console.error('保存录制结果失败 (' + record.case_name + '):', e)
        ElMessage.error(`"${record.case_name}" 保存失败: ${e.response?.data?.error || e.message}`)
      }
    }

    if (totalSaved > 0) {
      ElMessage.success(`已成功保存 ${totalSaved} 条录制结果`)
      showReviewDialog.value = false
      router.push('/ui-automation/test-cases')
    }
  } finally {
    savingRecording.value = false
  }
}

const goToRecords = () => {
  showBatchDialog.value = false
  router.push('/ai-intelligent-mode/execution-records')
}

// ========== AI閻熸粎澧楀ú鏍春濡ゅ懏鏅柛顐ゅ枎缁€瀣煙閻熼偊妲搁柛妯绘尵濡叉劙鎮崨顖滎槴==========
// 闂佺懓鐏氶幐鍝ユ閹达箑纭€闁哄洦宀搁崵瀣煟椤剙濡虹紒韬插劦閹啴宕欏褏鎲搁悧鍫熺闁糕晜顨呴锝夊捶椤撶姴鐐?
const openAIRecordForCase = async (row) => {
  // 闂佸搫琚崕鍙夌珶濡吋瀚氶柕澹嫭娈㈡繛鎾磋壘椤戝懘顢氶鑺ュ劅闁哄啫鍊归悾閬嶆煙缁楁稑妫弨浠嬫偣娴ｈ绶茬紓宥呬笉D
  const batchRecord = batchRecords.value.find(r => r.case_id === row.id && r.execution_id)
  if (!batchRecord || !batchRecord.execution_id) {
    ElMessage.warning('当前用例还没有可查看的 AI 录制结果')
    return
  }

  currentAIRecordId.value = batchRecord.execution_id

  // 闂佸憡姊绘慨鎯归崶銊ｄ簻闁革富鍘界粣妤呮煕閹烘搩娈欓柕?
  if (!projects.value.length) {
    await loadProjects()
  }

  showAIRecordDialog.value = true
  aiRecordLoading.value = true
  aiRecordForm.projectId = projects.value[0]?.id || null
  aiRecordForm.testCaseName = `AI录制_${row.name}_${new Date().toLocaleString()}`

  try {
    const response = await getAIRecordingActions(currentAIRecordId.value)
    aiRecordingActions.value = response.data.actions || []
    if (aiRecordingActions.value.length === 0) {
      ElMessage.warning(response.data.message || '当前没有可保存的录制步骤')
    }
  } catch (error) {
    console.error('闂佸吋鍎抽崲鑼躲亹閸㈠様閻熸粎澧楀ú鏍春濡も偓椤垽濡烽埡濞惧亾閸愨晛绶為弶鍫亯琚?', error)
    ElMessage.error('闂佸吋鍎抽崲鑼躲亹閸㈠様閻熸粎澧楀ú鏍春濡も偓椤垽濡烽埡濞惧亾閸愨晛绶為弶鍫亯琚? ' + (error.response?.data?.error || error.message))
  } finally {
    aiRecordLoading.value = false
  }
}

// 閻庢鍠掗崑鎾斥攽椤旂⒈鐖汭閻熸粎澧楀ú鏍春濡ゅ懏鏅慨妯哄暱缁狀垶鏌涘▎鎰濠⒀冪Ч瀵灚寰勬繝鍌氭闁诲海鎳撻張顒勫垂濮樿泛绠ョ憸鎴︺€侀幋鐘冲闁哄娉曠粔鍧楁煟閵娿儱娈業閻熸粎澧楀ú鏍春濡も偓椤垽濡烽埡濞惧亾?
const startAIRecording = async () => {
  // 闂佸吋鍎抽崲鑼躲亹閸ヮ剙绠ラ柍褜鍓熷鍨緞婵犲倸娈ラ柣搴ｆ嚀閺堫剟宕瑰鑸靛剭闁告洦鍓欓埛鏃堟偠濞戞鐒锋い鏂挎穿閵囨劙寮紞?
  const completedRecords = batchRecords.value.filter(r => r.execution_id && (r.status === 'passed' || r.status === 'failed'))
  if (completedRecords.length === 0) {
    ElMessage.warning('当前没有可用于保存的批量录制结果')
    return
  }

  // 婵帗绋掗…鍫ヮ敇婵犳碍鐒诲璺侯儏椤忋儳绱掑Δ濠傚幐缂佹柨鐡ㄧ粙澶愵敂閸ヨ泛鏁归悷婊呭濞叉粌鈻撻幈绠坋cution_id
  currentAIRecordId.value = completedRecords[0].execution_id

  // 闂佸憡姊绘慨鎯归崶銊ｄ簻闁革富鍘界粣妤呮煕閹烘搩娈欓柕?
  if (!projects.value.length) {
    await loadProjects()
  }

  // 闂佸吋鍎抽崲鑼躲亹閸モ晝绠旀い鎴ｆ硶椤忓崬鈽夐幙鍐ф捣妞ゆ柨娲╅妵鎰板即閻樺磭鏆燗I閻熸粎澧楀ú鏍春濡も偓椤垽濡烽埡濞惧亾?
  showAIRecordDialog.value = true
  aiRecordLoading.value = true
  aiRecordForm.projectId = projects.value[0]?.id || null
  aiRecordForm.testCaseName = `AI录制_${new Date().toLocaleString()}`

  try {
    const response = await getAIRecordingActions(currentAIRecordId.value)
    aiRecordingActions.value = response.data.actions || []
    if (aiRecordingActions.value.length === 0) {
      ElMessage.warning(response.data.message || '当前没有可保存的录制步骤')
    }
  } catch (error) {
    console.error('加载 AI 录制步骤失败:', error)
    ElMessage.error('加载 AI 录制步骤失败: ' + (error.response?.data?.error || error.message))
  } finally {
    aiRecordLoading.value = false
  }
}

// 闂佸憡甯炴繛鈧繛鍛叄瀹曪繝寮村璺烘疂AI閻熸粎澧楀ú鏍春濡も偓椤垽濡烽埡濞惧亾?
const removeAIRecordingStep = (index) => {
  aiRecordingActions.value.splice(index, 1)
}

// 缂佺虎鍙庨崰娑㈩敇缂佹鈹嶆繝闈涙閹界嚄I閻熸粎澧楀ú鏍春濡も偓椤垽濡烽埡濞惧亾?
const confirmSaveAIRecording = async () => {
  if (!currentAIRecordId.value) return
  if (!aiRecordForm.projectId) {
    ElMessage.warning('请先选择要保存到的项目')
    return
  }
  if (!aiRecordForm.testCaseName) {
    ElMessage.warning('请输入测试用例名称')
    return
  }
  if (aiRecordingActions.value.length === 0) {
    ElMessage.warning('当前没有可保存的录制步骤')
    return
  }

  aiRecordSaving.value = true
  try {
    const payload = {
      project_id: aiRecordForm.projectId,
      case_name: aiRecordForm.testCaseName,
      actions: aiRecordingActions.value  // 闂佸憡鐟﹂崹鍧楀焵椤戞寧顦烽柟渚垮姂瀵劑鎮烽悧鍫濃偓鐢告煟閵娿儱顏い鎺斿仦椤ㄣ儵濡堕崨顓犱粴闁?
    }
    const response = await saveAIRecording(currentAIRecordId.value, payload)
    ElMessage.success(`已保存为测试用例：${response.data.test_case_name}，共 ${response.data.steps_created} 步`)
    showAIRecordDialog.value = false
  } catch (error) {
    console.error('保存 AI 录制失败:', error)
    ElMessage.error('保存 AI 录制失败: ' + (error.response?.data?.error || error.message))
  } finally {
    aiRecordSaving.value = false
  }
}

const batchSaveAIRecording = async () => {
  const records = completedBatchRecords.value
  if (records.length === 0) {
    ElMessage.warning('当前没有可批量保存的录制结果')
    return
  }

  // 缂佺虎鍙庨崰鏇犳崲濮橆厹浜滈柛锔诲幗缁愭鏌涢幒鎿冩畽闁靛棗鍟蹇涘箵閹烘埈娼遍柡?
  if (!projects.value.length) {
    await loadProjects()
  }
  if (!projects.value.length) {
    ElMessage.error('没有可用项目，无法保存录制结果')
    return
  }

  const defaultProjectId = projects.value[0]?.id

  // 闂佸搫顑呯€氼剛绱撻幘璇茬煑妞ゆ牗绮庡浠嬪级閸喎鐏╂繛鍫熷灦缁屽崬鈹戦崱娆愭喖闂佸憡甯楅〃澶愬Υ?
  batchSaveItems.splice(0, batchSaveItems.length,
    ...records.map(r => ({
      case_id: r.case_id,
      execution_id: r.execution_id,
      case_name: r.case_name || ('Case_' + r.case_id),
      test_case_name: 'AI录制_' + (r.case_name || r.case_id) + '_' + new Date().toLocaleDateString(),
      project_id: defaultProjectId,
      saved: false,
      saving: false,
      error: false
    }))
  )

  showBatchSaveDialog.value = true
}

const confirmBatchSave = async () => {
  // 闂佸搫绋勭换婵嬫偘?
  for (const item of batchSaveItems) {
    if (!item.project_id) {
      ElMessage.warning('请为每条录制结果选择保存项目')
      return
    }
    if (!item.test_case_name || !item.test_case_name.trim()) {
      ElMessage.warning('请为每条录制结果填写测试用例名称')
      return
    }
  }

  batchSaving.value = true
  let successCount = 0
  let failCount = 0

  for (const item of batchSaveItems) {
    if (item.saved) continue
    item.saving = true
    item.error = false
    try {
      const payload = {
        project_id: item.project_id,
        case_name: item.test_case_name.trim()
      }
      const response = await saveAIRecording(item.execution_id, payload)
      item.saved = true
      successCount++
    } catch (error) {
      item.error = true
      failCount++
      console.error('批量保存 AI 录制失败 (ID: ' + item.execution_id + '):', error)
    } finally {
      item.saving = false
    }
  }

  batchSaving.value = false

  if (failCount === 0) {
    ElMessage.success('批量保存完成，成功保存 ' + successCount + ' 条测试用例')
  } else {
    ElMessage.warning('批量保存已完成，成功 ' + successCount + ' 条，失败 ' + failCount + ' 条')
  }
}



// ==================== Setup Template Functions ====================
const loadSetupTemplates = async () => {
  try {
    const res = await getSetupTemplates()
    setupTemplates.value = res.data?.results || res.data || []
  } catch (e) {
    console.error('Failed to load setup templates:', e)
  }
}

const openNewTemplate = () => {
  editingTemplateId.value = null
  templateForm.name = ''
  templateForm.description = ''
  templateForm.target_url = ''
  templateForm.project = null
  templateForm.steps = [{ description: '' }]
  showTemplateFormDialog.value = true
}

const templateVariableOptions = [
  { label: '随机手机号', expression: '${random_phone()}', field: '账号', pattern: /(?<!\d)1[3-9]\d{9}(?!\d)/g },
  { label: '随机姓名', expression: '${random_name()}', field: '姓名' },
  { label: '随机邮箱', expression: '${random_email()}', field: '邮箱', pattern: /[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}/g },
  { label: '随机地址', expression: '${random_address()}', field: '地址' },
  { label: '随机身份证', expression: '${random_id_card()}', field: '身份证号', pattern: /(?<!\d)\d{17}[\dXx](?!\d)/g },
  { label: '随机公司', expression: '${random_company()}', field: '公司名称' },
  { label: '随机密码', expression: '${random_password()}', field: '密码' },
  { label: '随机六码', expression: '${random_digits(6)}', field: '验证码', pattern: /(?<!\d)\d{6}(?!\d)/g },
  { label: '随机 UUID', expression: '${random_uuid()}', field: '唯一标识' },
  { label: '当前时间戳', expression: '${timestamp()}', field: '时间戳', pattern: /(?<!\d)\d{10,13}(?!\d)/g },
]

const insertTemplateVariable = (step, expression) => {
  const option = templateVariableOptions.find(item => item.expression === expression)
  if (!option) return

  const current = String(step.description || '')
  const variablePattern = /\$\{[^}]+\}/
  let next = current
  if (variablePattern.test(current)) {
    next = current.replace(variablePattern, expression)
  } else if (option.pattern?.test(current)) {
    option.pattern.lastIndex = 0
    next = current.replace(option.pattern, expression)
  } else {
    next = current ? `${current}${expression}` : `输入${option.field}${expression}`
  }
  step.description = next
  step._variable_expression = null
}

const extractTemplateSteps = (taskDescription) => {
  const normalized = String(taskDescription || '').replace(/\r/g, '\n').trim()
  if (!normalized) return []

  let lines = normalized.split(/\n+/)
  if (lines.length === 1) {
    lines = normalized.split(/(?=\s*(?:第\s*)?\d+\s*[、.．:：]\s*)/)
  }

  return lines
    .map(line => line.replace(/^\s*(?:第\s*)?\d+\s*[、.．:：]\s*/, '').trim())
    .filter(Boolean)
    .filter(line => !/^(?:断言|验证|校验|检查)(?:\s|[:：，,]|$)/.test(line))
    .map(description => ({ description }))
}

const openTemplateConversionDialog = async () => {
  showTemplateConversionDialog.value = true
  templateSourceCaseId.value = null
  loadingTemplateSourceCases.value = true
  try {
    const response = await getAICases({ page: 1, page_size: 1000 })
    templateSourceCases.value = response.data?.results || response.data || []
  } catch (error) {
    templateSourceCases.value = cases.value
    ElMessage.warning('加载完整用例列表失败，已使用当前列表')
  } finally {
    loadingTemplateSourceCases.value = false
  }
}

const convertCaseToTemplate = () => {
  const sourceCase = selectedTemplateSourceCase.value
  if (!sourceCase) return

  const steps = extractTemplateSteps(sourceCase.task_description)
  if (!steps.length) {
    ElMessage.warning('该用例没有可转换的前置步骤，请检查任务描述')
    return
  }

  const projectId = sourceCase.project?.id || sourceCase.project_id || null
  if (!projectId) {
    ElMessage.warning('该用例未关联项目，无法创建前置步骤模板')
    return
  }

  editingTemplateId.value = null
  templateForm.name = `${sourceCase.name} - 前置步骤`
  templateForm.description = `由 AI 用例“${sourceCase.name}”转换，可按需调整步骤`
  templateForm.target_url = (sourceCase.task_description || '').match(/https?:\/\/[^\s，。；;]+/)?.[0] || ''
  templateForm.project = projectId
  templateForm.steps = steps
  showTemplateConversionDialog.value = false
  showTemplateFormDialog.value = true
}

const editTemplate = (row) => {
  editingTemplateId.value = row.id
  templateForm.name = row.name
  templateForm.description = row.description || ''
  templateForm.target_url = row.target_url || ''
  templateForm.project = row.project || null
  templateForm.steps = (row.steps || []).map(s => ({ description: typeof s === 'string' ? s : s.description || '' }))
  if (!templateForm.steps.length) templateForm.steps = [{ description: '' }]
  showTemplateFormDialog.value = true
}

const saveTemplate = async () => {
  if (!templateForm.project) {
    ElMessage.warning('请先选择项目')
    return
  }
  if (!templateForm.name.trim()) {
    ElMessage.warning('请输入模板名称')
    return
  }
  const validSteps = templateForm.steps.filter(s => s.description.trim())
  if (!validSteps.length) {
    ElMessage.warning('请至少保留一个有效步骤')
    return
  }
  savingTemplate.value = true
  try {
    const payload = {
      name: templateForm.name.trim(),
      description: templateForm.description?.trim() || '',
      target_url: templateForm.target_url?.trim() || '',
      steps: validSteps.map(s => ({ description: s.description.trim(), action_type: 'auto' })),
      project: templateForm.project
    }
    if (editingTemplateId.value) {
      await updateSetupTemplate(editingTemplateId.value, payload)
      ElMessage.success('模板更新成功')
    } else {
      await createSetupTemplate(payload)
      ElMessage.success('模板创建成功')
    }
    showTemplateFormDialog.value = false
    loadSetupTemplates()
  } catch (e) {
    ElMessage.error('保存模板失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    savingTemplate.value = false
  }
}

const deleteTemplate = async (row) => {
  try {
    await ElMessageBox.confirm(`确认删除模板 ${row.name} 吗？`, '删除确认', { type: 'warning' })
    await deleteSetupTemplate(row.id)
    ElMessage.success('模板删除成功')
    loadSetupTemplates()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error('模板删除失败')
  }
}

watch(showSetupTemplateDialog, (val) => {
  if (val) loadSetupTemplates()
})

// 婵＄偑鍊楅弫璇差焽娴兼潙纭€婵繂鏈粊浼存煛閸愵厼鐓愮紒鏂款煼閹爼宕卞杈ㄧ€柣?
const refreshBatchElapsedTime = () => {
  if (!batchStartedAt.value) return
  const startedAtMs = Date.parse(batchStartedAt.value)
  if (Number.isNaN(startedAtMs)) return
  batchElapsedSeconds.value = Math.max(0, (Date.now() - startedAtMs) / 1000)
}

const startBatchElapsedTimer = () => {
  stopBatchElapsedTimer()
  refreshBatchElapsedTime()
  batchElapsedTimer = setInterval(refreshBatchElapsedTime, 250)
}

const stopBatchElapsedTimer = () => {
  if (batchElapsedTimer) {
    clearInterval(batchElapsedTimer)
    batchElapsedTimer = null
  }
}

const finishBatchElapsedTimer = () => {
  const startedAtMs = Date.parse(batchStartedAt.value || '')
  const completedTimes = batchRecords.value
    .map(record => Date.parse(record.end_time || ''))
    .filter(timestamp => !Number.isNaN(timestamp))
  const completedAtMs = completedTimes.length ? Math.max(...completedTimes) : Number.NaN
  const endedAtMs = Number.isNaN(completedAtMs) ? Date.now() : completedAtMs
  if (!Number.isNaN(startedAtMs)) {
    batchTotalDuration.value = Math.max(0, (endedAtMs - startedAtMs) / 1000)
    batchElapsedSeconds.value = batchTotalDuration.value
  }
  stopBatchElapsedTimer()
}

onUnmounted(() => {
  if (batchPollTimer) {
    clearInterval(batchPollTimer)
    batchPollTimer = null
  }
  stopBatchElapsedTimer()
})

onMounted(() => {
  loadProjects()
  loadCategories()
  loadDesktopAppProfiles()
  loadCases()
})
</script>

<style lang="scss" scoped>
.category-toolbar {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 12px;
}

.batch-duration-summary {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin: 0 0 12px;
  color: #606266;
  font-size: 13px;
}

.batch-duration-summary strong {
  color: #303133;
  font-size: 16px;
}

.batch-duration-note {
  color: #909399;
}

.category-empty-tip {
  color: #909399;
  font-size: 12px;
  line-height: 20px;
}

.batch-run-mode-group {
  display: grid;
  gap: 12px;
  width: 100%;

  :deep(.el-radio) {
    align-items: flex-start;
    height: auto;
    margin-right: 0;
    padding: 12px;
    white-space: normal;
  }
}

.batch-run-mode-desc {
  margin-top: 4px;
  color: #909399;
  font-size: 12px;
  line-height: 18px;
}

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
}

.card-container {
  background-color: #fff;
  border-radius: 4px;
  padding: 20px;
  box-shadow: 0 2px 12px 0 rgba(0, 0, 0, 0.1);
}

.filter-bar {
  margin-bottom: 20px;
}

.pagination-container {
  margin-top: 20px;
  display: flex;
  justify-content: flex-end;
}

.assertion-preview-panel {
  width: 100%;
  border: 1px solid #dcdfe6;
  padding: 10px;
}

.assertion-preview-toolbar {
  display: flex;
  min-height: 28px;
  align-items: center;
  justify-content: space-between;
  color: #606266;
  font-size: 13px;
}

.assertion-preview-list {
  margin-top: 8px;
  max-height: 180px;
  overflow-y: auto;
}

.assertion-preview-item {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  padding: 7px 0;
  border-top: 1px solid #ebeef5;
  font-size: 13px;
}

.assertion-preview-description {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.assertion-preview-kind {
  color: #909399;
  font-family: Consolas, monospace;
  font-size: 12px;
}

.batch-template-tip {
  margin-top: 8px;
  color: #909399;
  font-size: 12px;
  line-height: 18px;
}

.batch-template-tip--warning {
  color: #e6a23c;
}

.ai-case-import-upload {
  width: 100%;
}

.import-template {
  margin-top: 12px;
  background: #f7f8fa;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 12px;

  .template-title {
    font-weight: 600;
    margin-bottom: 8px;
  }

  pre {
    margin: 0;
    white-space: pre-wrap;
    font-size: 12px;
    color: #606266;
  }
}
</style>
