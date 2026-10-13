<template>
  <div class="task-detail">
    <div class="page-header">
      <div class="header-left">
        <h2>{{ $t('taskDetail.title') }} <span v-if="task.title">- {{ task.title }}</span></h2>
        <div class="task-info">
          <span class="task-id">{{ $t('taskDetail.taskId') }}: {{ taskId }}</span>
          <span class="task-status" :class="task.status">{{ getStatusText(task.status) }}</span>
        </div>
      </div>
      <div class="header-actions">
        <div class="export-dropdown" v-if="testCases.length > 0">
          <button
            class="export-btn"
            @click="toggleExportMenu"
            :disabled="isExporting">
            <span v-if="isExporting">{{ $t('taskDetail.exporting') }}</span>
            <span v-else>{{ $t('taskDetail.exportBtn') }}</span>
            <span class="export-arrow">▼</span>
          </button>
          <div class="export-menu" v-if="showExportMenu">
            <button @click="handleExport('excel')">
              {{ $t('taskDetail.exportExcel') }}
            </button>
            <button @click="handleExport('markdown')">
              {{ $t('taskDetail.exportMarkdown') }}
            </button>
            <button @click="handleExport('opml')">
              {{ $t('taskDetail.exportOPML') }}
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- 闇€姹傛弿杩版姌鍙犲崱鐗?-->
    <div v-if="task.requirement_text" ref="requirementSection" class="requirement-description-card">
      <el-collapse>
        <el-collapse-item name="requirement">
          <template #title>
            <div class="collapse-title">
              <span class="title-text">{{ $t('taskDetail.requirementTitle') }}</span>
              <span class="title-hint">{{ $t('taskDetail.requirementHint') }}</span>
            </div>
          </template>
          <div class="requirement-content">
            <div class="requirement-text">
              {{ task.requirement_text }}
            </div>
            <div v-if="task.requirement_images && task.requirement_images.length > 0" class="requirement-images">
              <div class="requirement-images__header">
                <strong>文档附图</strong>
                <span>{{ task.requirement_images.length }} 张</span>
              </div>
              <div class="requirement-images__grid">
                <a
                  v-for="image in task.requirement_images"
                  :key="image.url"
                  class="requirement-image-card"
                  :href="image.url"
                  target="_blank"
                  rel="noopener noreferrer">
                  <img :src="image.url" :alt="image.label || '文档附图'" class="requirement-image-card__img">
                  <span class="requirement-image-card__label">{{ image.label || image.name }}</span>
                </a>
              </div>
            </div>
            <div class="requirement-actions">
              <el-button size="small" @click="copyRequirementText">
                <el-icon><DocumentCopy /></el-icon>
                {{ $t('taskDetail.copyRequirement') }}
              </el-button>
            </div>
          </div>
        </el-collapse-item>
      </el-collapse>
    </div>

    <!-- 闇€姹傛緞娓呭璇濓紙浠呭湪 pending_clarification 鐘舵€佷笅鏄剧ず锛?-->
    <div v-if="task.status === 'pending_clarification'" class="clarification-panel">
      <div class="clarification-header">
        <div class="clarification-header-left">
          <div class="clarification-icon-wrap">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>
          </div>
          <div class="clarification-header-text">
            <div class="clarification-title">{{ $t('taskDetail.clarificationTitle') }}</div>
            <div class="clarification-subtitle">{{ $t('taskDetail.clarificationSubtitle') }}</div>
          </div>
        </div>
        <div class="clarification-status-badge" v-if="clarificationDone">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>
          <span>{{ $t('taskDetail.clarificationDoneTip') }}</span>
        </div>
      </div>

      <div class="clarification-messages" ref="clarificationMessages">
        <div v-if="clarificationLoading && clarifications.length === 0" class="clarification-loading">
          <div class="loading-spinner"></div>
          <span>{{ $t('taskDetail.clarificationStarting') }}</span>
        </div>
        <div v-else-if="clarifications.length === 0" class="clarification-empty">
          {{ $t('taskDetail.clarificationEmpty') }}
        </div>
        <div
          v-for="msg in clarifications"
          :key="msg.id"
          class="chat-message"
          :class="msg.role === 'ai' ? 'message-ai' : 'message-user'">
          <div class="message-avatar">
            <template v-if="msg.role === 'ai'">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="10" rx="2"/><circle cx="12" cy="5" r="2"/><path d="M12 7v4"/><line x1="8" y1="16" x2="8" y2="16"/><line x1="16" y1="16" x2="16" y2="16"/></svg>
            </template>
            <template v-else>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
            </template>
          </div>
          <div class="message-bubble-wrap">
            <div class="message-bubble">
              <div class="message-content" v-html="msg.role === 'ai' ? formatClarificationMarkdown(msg.content) : formatMarkdown(msg.content)"></div>
            </div>
            <div class="message-meta">{{ formatTime(msg.created_at) }}</div>
          </div>
        </div>
        <div v-if="clarificationSubmitting" class="chat-message message-ai">
          <div class="message-avatar">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="10" rx="2"/><circle cx="12" cy="5" r="2"/><path d="M12 7v4"/></svg>
          </div>
          <div class="message-bubble-wrap">
            <div class="message-bubble">
              <div class="message-content typing">
                <span class="typing-dot"></span>
                <span class="typing-dot"></span>
                <span class="typing-dot"></span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="clarification-footer" v-if="!clarificationDone">
        <div class="clarification-input-area">
          <el-input
            v-model="clarificationInput"
            type="textarea"
            :rows="3"
            resize="none"
            :placeholder="$t('taskDetail.clarificationInputPlaceholder')"
            :disabled="clarificationSubmitting || clarifications.length === 0"
            @keydown.ctrl.enter="submitClarification"
            @keydown.meta.enter="submitClarification" />
          <div class="clarification-input-bar">
            <span class="clarification-input-hint">{{ $t('taskDetail.clarificationInputHint') }}</span>
            <button
              class="btn-primary"
              :disabled="!clarificationInput.trim() || clarificationSubmitting || clarifications.length === 0"
              @click="submitClarification">
              <svg v-if="!clarificationSubmitting" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
              <span>{{ clarificationSubmitting ? $t('taskDetail.clarificationSending') : $t('taskDetail.clarificationSend') }}</span>
            </button>
          </div>
        </div>
        <div class="clarification-actions">
          <button
            class="btn-success"
            :disabled="clarifications.length === 0 || clarificationSubmitting"
            @click="finalizeClarification">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
            <span>{{ $t('taskDetail.clarificationFinalize') }}</span>
          </button>
          <button
            class="btn-ghost"
            :disabled="clarificationSubmitting"
            @click="skipClarification">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 4 15 12 5 20 5 4"/><line x1="19" y1="5" x2="19" y2="19"/></svg>
            <span>{{ $t('taskDetail.clarificationSkip') }}</span>
          </button>
        </div>
      </div>
      <div v-else class="clarification-finalize-bar">
        <button
          class="btn-success btn-large"
          :disabled="clarificationSubmitting"
          @click="finalizeClarification">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
          <span>{{ $t('taskDetail.clarificationFinalize') }}</span>
        </button>
      </div>
    </div>

    <div v-if="isLoading" class="loading-state">
      <p>{{ $t('taskDetail.loading') }}</p>
    </div>

    <div v-else-if="!task.task_id" class="error-state">
      <h3>{{ $t('taskDetail.taskNotExist') }}</h3>
      <router-link to="/ai-generation/generated-testcases">{{ $t('taskDetail.backToList') }}</router-link>
    </div>

    <div v-else class="task-content">

    <div class="task-intelligence-grid">
      <section class="intelligence-card intelligence-card--summary">
        <div class="intelligence-card__header">
          <div>
            <p class="intelligence-card__eyebrow">Task cockpit</p>
            <h3>任务总览驾驶舱</h3>
            <p class="intelligence-card__desc">把任务质量、产出规模和交付成熟度压缩到首屏，减少长页面来回查找。</p>
          </div>
          <span class="delivery-badge" :class="deliveryMaturity.tone">{{ deliveryMaturity.label }}</span>
        </div>

        <div class="summary-metric-grid">
          <article
            v-for="metric in summaryMetrics"
            :key="metric.label"
            class="summary-metric">
            <span class="summary-metric__label">{{ metric.label }}</span>
            <strong class="summary-metric__value">{{ metric.value }}</strong>
            <span class="summary-metric__hint">{{ metric.hint }}</span>
          </article>
        </div>

        <div class="signal-strip">
          <div
            v-for="signal in healthSignals"
            :key="signal.label"
            class="signal-pill"
            :class="signal.tone">
            <span class="signal-pill__label">{{ signal.label }}</span>
            <span class="signal-pill__value">{{ signal.value }}</span>
          </div>
        </div>
      </section>

      <section class="intelligence-card intelligence-card--navigator">
        <div class="intelligence-card__header">
          <div>
            <p class="intelligence-card__eyebrow">Deliverables</p>
            <h3>交付物导航</h3>
            <p class="intelligence-card__desc">快速跳到各阶段产物，也可以一键复制，方便评审和流转。</p>
          </div>
        </div>

        <div class="deliverable-list">
          <article
            v-for="item in deliverableSections"
            :key="item.key"
            class="deliverable-item"
            :class="{ 'is-ready': item.ready }">
            <div class="deliverable-item__meta">
              <div class="deliverable-item__title-row">
                <strong>{{ item.label }}</strong>
                <span class="deliverable-status" :class="item.ready ? 'is-ready' : 'is-waiting'">{{ item.ready ? '已就绪' : '待生成' }}</span>
              </div>
              <p>{{ item.description }}</p>
            </div>
            <div class="deliverable-item__actions">
              <button class="mini-action-btn" :disabled="!item.available" @click="scrollToSection(item.ref)">{{ item.available ? '查看' : '未生成' }}</button>
              <button class="mini-action-btn mini-action-btn--ghost" :disabled="!item.ready" @click="copyDeliverable(item.key)">复制</button>
            </div>
          </article>
        </div>
      </section>
    </div>

    <section class="decision-log-card">
      <div class="decision-log-card__header">
        <div>
          <p class="intelligence-card__eyebrow">Decision trail</p>
          <h3>决策日志</h3>
          <p class="intelligence-card__desc">自动串联需求输入、澄清、生成、评审和最终交付，保留可追溯证据链。</p>
        </div>
      </div>
      <div class="decision-timeline">
        <article
          v-for="entry in decisionLogEntries"
          :key="entry.title"
          class="timeline-item">
          <div class="timeline-item__dot" :class="entry.tone"></div>
          <div class="timeline-item__content">
            <div class="timeline-item__row">
              <strong>{{ entry.title }}</strong>
              <span>{{ entry.meta }}</span>
            </div>
            <p>{{ entry.description }}</p>
          </div>
        </article>
      </div>
    </section>

    <!-- 鐢熸垚涓繘搴﹂潰鏉匡紙status 涓?generating / writing / reviewing / revising / completing 鏃舵樉绀猴級 -->
    <div v-if="isGenerationInProgress && task.status !== 'completed' && task.status !== 'failed'" class="generation-progress-panel">
      <div class="gen-progress-header">
        <div class="gen-progress-icon">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>
        </div>
        <div class="gen-progress-title-wrap">
          <div class="gen-progress-title">{{ $t('taskDetail.generatingTitle') || 'AI 正在生成测试用例' }}</div>
          <div class="gen-progress-subtitle">{{ progressPhaseText }}</div>
        </div>
        <div class="gen-progress-percent">{{ progressPercent }}%</div>
      </div>

      <el-progress
        :percentage="progressPercent"
        :stroke-width="10"
        :status="progressPercent >= 100 ? 'success' : ''"
        :show-text="false"
        class="gen-progress-bar" />

      <div class="gen-progress-steps">
        <div class="gen-step" :class="{ active: progressPercent >= 10, done: progressPercent > 30 }">
          <span class="step-num">1</span>
          <span class="step-label">{{ $t('taskDetail.stepGenerating') || '正在生成' }}</span>
        </div>
        <div class="gen-step" :class="{ active: progressPercent >= 60, done: progressPercent > 70 }">
          <span class="step-num">2</span>
          <span class="step-label">{{ $t('taskDetail.stepReviewing') || 'AI 评审' }}</span>
        </div>
        <div class="gen-step" :class="{ active: progressPercent >= 80, done: progressPercent >= 100 }">
          <span class="step-num">3</span>
          <span class="step-label">{{ $t('taskDetail.stepRevising') || '修正优化' }}</span>
        </div>
        <div class="gen-step" :class="{ active: progressPercent >= 100, done: progressPercent >= 100 }">
          <span class="step-num">4</span>
          <span class="step-label">{{ $t('taskDetail.stepCompleted') || '已完成' }}</span>
        </div>
      </div>

      <!-- 娴佸紡鍐呭棰勮锛堝凡杩佺Щ鍒?琛ㄦ牸鐎戝竷娴佷腑锛屾澶勪繚鐣欎絾闅愯棌锛?-->
      <div v-if="false && rawStreamContent" class="gen-stream-preview">
        <div class="gen-stream-header">
          <span>{{ streamPhaseLabel }}</span>
          <span class="gen-stream-count">{{ rawStreamContent.length }} 瀛楃</span>
        </div>
        <div class="gen-stream-body" v-html="formatMarkdown(rawStreamContent)"></div>
      </div>
    </div>

      <div ref="finalSection" v-if="testCases.length > 0" class="final-deliverable-block">
        <div class="waterfall-card waterfall-card-table4">
          <div class="waterfall-card-header">
            <span class="waterfall-card-icon">04</span>
            <span class="waterfall-card-title">最终版测试用例</span>
            <span class="waterfall-card-badge badge-done">{{ testCases.length }} 条用例</span>
          </div>
        </div>

      <!-- 鎵归噺鎿嶄綔鍖哄煙 -->
      <!-- 鎵归噺鎿嶄綔鍖哄煙锛堝惛椤堕€昏緫鐢?JS 鎺у埗锛?-->
      <div class="batch-actions" style="display: flex !important; justify-content: space-between !important; align-items: center !important; flex-wrap: wrap !important; gap: 15px; background: white; padding: 12px 15px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); border-radius: 8px; margin-bottom: 0;">
        <!-- 宸︿晶锛氬叏閫?+ 妯″潡绛涢€?-->
        <div style="display: flex !important; align-items: center !important; gap: 20px !important; flex-wrap: wrap !important; margin-right: auto !important;">
          <label class="select-all">
            <input
              type="checkbox"
              :checked="isAllSelected"
              @change="toggleSelectAll">
            {{ $t('taskDetail.selectAll') }}
          </label>
          <select
            v-model="moduleFilter"
            @change="currentPage = 1"
            class="module-filter-select">
            <option value="">全部模块 ({{ testCases.length }})</option>
            <option v-for="mod in uniqueModules" :key="mod" :value="mod">
              {{ mod }} ({{ testCases.filter(tc => tc.module === mod).length }})
            </option>
          </select>
          <span class="selected-count" v-if="selectedCases.length > 0">
            {{ $t('taskDetail.selectedCount', { count: selectedCases.length }) }}
          </span>
        </div>
        
        <!-- 鍙充晶锛氭搷浣滄寜閽?-->
        <div style="display: flex !important; gap: 10px !important; flex-shrink: 0 !important;">
          <button
            class="batch-adopt-btn"
            :disabled="selectedCases.length === 0"
            @click="batchAdopt">
            {{ $t('taskDetail.batchAdopt', { count: selectedCases.length }) }}
          </button>
          <button
            class="batch-discard-btn"
            :disabled="selectedCases.length === 0"
            @click="batchDiscard">
            {{ $t('taskDetail.batchDiscard', { count: selectedCases.length }) }}
          </button>
        </div>
      </div>

      <!-- 琛ㄥご锛堢嫭绔嬪嚭鏉ワ紝涓?batch-actions 鍚岀骇锛屽疄鐜板惛椤讹級 -->
      <div class="table-header">
        <div class="header-cell checkbox-cell">{{ $t('taskDetail.tableSelect') }}</div>
        <div class="header-cell">模块</div>
        <div class="header-cell">{{ $t('taskDetail.tableCaseId') }}</div>
        <div class="header-cell">{{ $t('taskDetail.tableScenario') }}</div>
        <div class="header-cell">{{ $t('taskDetail.tablePrecondition') }}</div>
        <div class="header-cell">{{ $t('taskDetail.tableSteps') }}</div>
        <div class="header-cell">{{ $t('taskDetail.tableExpected') }}</div>
        <div class="header-cell">{{ $t('taskDetail.tablePriority') }}</div>
        <div class="header-cell">{{ $t('taskDetail.tableActions') }}</div>
      </div>

      <!-- 娴嬭瘯鐢ㄤ緥鍒楄〃 -->
      <div class="testcases-table">
        <div class="table-body">
          <div
            v-for="(testCase, index) in paginatedTestCases"
            :key="testCase.id || index"
            class="table-row">
            <div class="body-cell checkbox-cell">
              <input 
                type="checkbox" 
                :value="testCase"
                v-model="selectedCases"
                @change="updateSelectAll">
            </div>
            <div class="body-cell"><span class="module-tag">{{ testCase.module || '-' }}</span></div>
            <div class="body-cell">{{ testCase.caseId || `TC${String(index + 1).padStart(3, '0')}` }}</div>
            <div class="body-cell">{{ testCase.scenario }}</div>
            <div class="body-cell text-truncate">
              {{ formatTextForList(testCase.precondition) }}
            </div>
            <div class="body-cell text-truncate">
              {{ formatTextForList(testCase.steps) }}
            </div>
            <div class="body-cell text-truncate">
              {{ formatTextForList(testCase.expected) }}
            </div>
            <div class="body-cell">
              <span class="priority-tag" :class="testCase.priority?.toLowerCase()">{{ testCase.priority || 'P2' }}</span>
            </div>
            <div class="body-cell">
              <div class="action-buttons">
                <button class="view-btn" @click="viewCaseDetail(testCase, index)">{{ $t('taskDetail.viewDetail') }}</button>
                <button class="adopt-btn" @click="adoptSingleCase(testCase, index)">{{ $t('taskDetail.adopt') }}</button>
                <button class="discard-btn" @click="discardSingleCase(testCase, index)">{{ $t('taskDetail.discard') }}</button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="pagination-section">
        <div class="pagination-info">
          {{ $t('taskDetail.paginationInfo', { start: paginationStart, end: paginationEnd, total: filteredTestCases.length }) }}
        </div>
        <div class="pagination-controls">
          <div class="page-size-selector">
            <label>{{ $t('taskDetail.pageSizeLabel') }}</label>
            <select v-model="pageSize" @change="currentPage = 1">
              <option value="10">{{ $t('taskDetail.pageSizeOption', { size: 10 }) }}</option>
              <option value="20">{{ $t('taskDetail.pageSizeOption', { size: 20 }) }}</option>
              <option value="50">{{ $t('taskDetail.pageSizeOption', { size: 50 }) }}</option>
            </select>
          </div>
          <div class="pagination-buttons">
            <button :disabled="currentPage <= 1" @click="currentPage--">{{ $t('taskDetail.previousPage') }}</button>
            <span class="current-page">{{ $t('taskDetail.currentPageInfo', { current: currentPage, total: totalPages }) }}</span>
            <button :disabled="currentPage >= totalPages" @click="currentPage++">{{ $t('taskDetail.nextPage') }}</button>
          </div>
        </div>
      </div>
      </div>

      <!-- ===== 4琛ㄦ牸鐎戝竷娴佽鍥撅紙濮嬬粓鏄剧ず锛屾湁鏁版嵁鐨勮〃鏍兼墠娓叉煋鍐呭 ===== -->
      <div v-if="showFourTables" class="four-tables-waterfall">

        <!-- 琛ㄦ牸1锛氶渶姹傛媶鍒嗚〃 -->
        <div ref="breakdownSection" class="waterfall-card" v-if="requirementBreakdown || task.requirement_breakdown">
          <div class="waterfall-card-header">
            <span class="waterfall-card-icon">01</span>
            <span class="waterfall-card-title">需求模块拆解</span>
            <span class="waterfall-card-badge" :class="requirementBreakdown ? 'badge-done' : 'badge-waiting'">{{ requirementBreakdown ? '已完成' : '生成中...' }}</span>
          </div>
          <div class="waterfall-card-body" v-if="requirementBreakdown" v-html="formatMarkdown(requirementBreakdown)"></div>
          <div class="waterfall-card-body card-loading" v-else>
            <span class="loading-dots"><i></i><i></i><i></i></span> AI 正在分析需求模块...
          </div>
        </div>

        <!-- 琛ㄦ牸2锛欰I 鐢ㄤ緥缂栧啓 -->
        <div ref="generatedSection" class="waterfall-card" v-if="rawStreamContent || generatedCases.length > 0 || task.stream_buffer">
          <div class="waterfall-card-header">
            <span class="waterfall-card-icon">02</span>
            <span class="waterfall-card-title">AI 测试用例编写</span>
            <span class="waterfall-card-badge" :class="(task.status === 'completed' || task.status === 'revising' || task.status === 'completing') ? 'badge-done' : (task.status === 'writing' || task.status === 'generating') ? 'badge-active' : 'badge-waiting'">{{ (task.status === 'completed' || task.status === 'revising' || task.status === 'completing') ? '已完成' : (task.status === 'writing' || task.status === 'generating') ? '正在生成...' : '等待中...' }}</span>
          </div>
          <!-- 杩涜涓細娴佸紡鏂囨湰棰勮 -->
          <div class="waterfall-card-body stream-body" v-if="rawStreamContent && task.status !== 'completed' && task.status !== 'failed'" v-html="formatMarkdown(rawStreamContent)"></div>
          <!-- 宸插畬鎴愶細瑙ｆ瀽涓鸿〃鏍?-->
          <div class="waterfall-card-body" v-else-if="generatedCases.length > 0">
            <table class="waterfall-table">
              <thead>
                <tr>
                  <th>用例 ID</th><th>所属模块</th><th>测试场景</th><th>前置条件</th><th>操作步骤</th><th>预期结果</th><th>优先级</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(c, idx) in generatedCases" :key="'gen-'+idx">
                  <td>{{ c.caseId }}</td><td>{{ c.module }}</td><td>{{ c.scenario }}</td><td>{{ c.precondition }}</td><td class="cell-steps">{{ c.steps }}</td><td>{{ c.expected }}</td><td><span class="priority-tag" :class="c.priority?.toLowerCase()">{{ c.priority }}</span></td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="waterfall-card-body card-empty" v-else-if="task.status === 'completed' || task.status === 'revising' || task.status === 'completing'">
            初稿内容未单独保留，最终结果请查看下方“最终版测试用例”。
          </div>
          <div class="waterfall-card-body card-loading" v-else>
            <span class="loading-dots"><i></i><i></i><i></i></span> AI 正在编写测试用例...
          </div>
        </div>

        <!-- 琛ㄦ牸3锛欰I 鐢ㄤ緥璇勫 -->
        <div ref="reviewSection" class="waterfall-card" v-if="task.review_feedback">
          <div class="waterfall-card-header">
            <span class="waterfall-card-icon">03</span>
            <span class="waterfall-card-title">AI 用例评审意见</span>
            <span class="waterfall-card-badge" :class="task.status === 'revising' || task.status === 'completing' || task.status === 'completed' ? 'badge-done' : (task.status === 'reviewing' ? 'badge-active' : 'badge-waiting')">{{ task.status === 'reviewing' ? '评审中...' : (task.status === 'revising' || task.status === 'completing' || task.status === 'completed' ? '已完成' : '等待中...') }}</span>
          </div>
          <div class="waterfall-card-body" v-html="formatMarkdown(task.review_feedback)"></div>
        </div>

      </div><!-- /four-tables-waterfall -->
      <div v-else class="empty-state">
        <h3>{{ $t('taskDetail.emptyTitle') }}</h3>
        <p>{{ $t('taskDetail.emptyHint') }}</p>
      </div>

    </div>

    <!-- 鐢ㄤ緥璇︽儏寮圭獥 -->
    <div v-if="showCaseDetail" class="case-detail-modal">
      <div class="modal-content" @click.stop>
        <div class="modal-header">
          <h3>{{ isEditing ? $t('taskDetail.modalEditTitle') : $t('taskDetail.modalViewTitle') }}</h3>
          <button class="close-btn" @click="closeCaseDetail">×</button>
        </div>

        <!-- 鏌ョ湅妯″紡 -->
        <div v-if="!isEditing" class="modal-body">
          <div class="detail-item">
            <label>{{ $t('taskDetail.labelCaseId') }}</label>
            <span>{{ selectedCase.caseId || `TC${String(selectedCaseIndex + 1).padStart(3, '0')}` }}</span>
          </div>
          <div class="detail-item">
            <label>{{ $t('taskDetail.labelScenario') }}</label>
            <p v-html="formatMarkdown(selectedCase.scenario)"></p>
          </div>
          <div class="detail-item">
            <label>{{ $t('taskDetail.labelPrecondition') }}</label>
            <p v-html="formatMarkdown(selectedCase.precondition || $t('taskDetail.labelNone'))"></p>
          </div>
          <div class="detail-item">
            <label>{{ $t('taskDetail.labelSteps') }}</label>
            <p class="test-steps" v-html="formatMarkdown(selectedCase.steps)"></p>
          </div>
          <div class="detail-item">
            <label>{{ $t('taskDetail.labelExpected') }}</label>
            <p v-html="formatMarkdown(selectedCase.expected)"></p>
          </div>
          <div class="detail-item">
            <label>{{ $t('taskDetail.labelPriority') }}</label>
            <span class="priority-tag" :class="selectedCase.priority?.toLowerCase()">{{ selectedCase.priority || 'P2' }}</span>
          </div>
        </div>

        <!-- 缂栬緫妯″紡 -->
        <div v-else class="modal-body edit-mode">
          <div class="form-item">
            <label>{{ $t('taskDetail.labelCaseId') }}</label>
            <span class="readonly-field">{{ editForm.caseId || `TC${String(selectedCaseIndex + 1).padStart(3, '0')}` }}</span>
          </div>
          <div class="form-item">
            <label>{{ $t('taskDetail.labelScenario') }}</label>
            <el-input v-model="editForm.scenario" type="textarea" :rows="2" :placeholder="$t('taskDetail.placeholderScenario')" />
          </div>
          <div class="form-item">
            <label>{{ $t('taskDetail.labelPrecondition') }}</label>
            <el-input v-model="editForm.precondition" type="textarea" :rows="3" :placeholder="$t('taskDetail.placeholderPrecondition')" />
          </div>
          <div class="form-item">
            <label>{{ $t('taskDetail.labelSteps') }}</label>
            <el-input v-model="editForm.steps" type="textarea" :rows="6" :placeholder="$t('taskDetail.placeholderSteps')" />
          </div>
          <div class="form-item">
            <label>{{ $t('taskDetail.labelExpected') }}</label>
            <el-input v-model="editForm.expected" type="textarea" :rows="4" :placeholder="$t('taskDetail.placeholderExpected')" />
          </div>
          <div class="form-item">
            <label>{{ $t('taskDetail.labelPriority') }}</label>
            <el-select v-model="editForm.priority" :placeholder="$t('taskDetail.placeholderPriority')">
              <el-option label="P0" value="P0"></el-option>
              <el-option label="P1" value="P1"></el-option>
              <el-option label="P2" value="P2"></el-option>
              <el-option label="P3" value="P3"></el-option>
            </el-select>
          </div>
        </div>

        <!-- 搴曢儴鎿嶄綔鏍?-->
        <div class="modal-footer">
          <template v-if="!isEditing">
            <button class="action-btn edit-btn" @click="startEdit">
              <span>{{ $t('taskDetail.btnEdit') }}</span>
            </button>
            <button class="action-btn close-btn-footer" @click="closeCaseDetail">{{ $t('taskDetail.btnClose') }}</button>
          </template>
          <template v-else>
            <button class="action-btn save-btn" @click="saveEdit" :disabled="isSaving">
              <span v-if="isSaving">{{ $t('taskDetail.btnSaveing') }}</span>
              <span v-else>{{ $t('taskDetail.btnSave') }}</span>
            </button>
            <button class="action-btn cancel-btn" @click="cancelEdit" :disabled="isSaving">{{ $t('taskDetail.btnCancel') }}</button>
          </template>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import api from '@/utils/api'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import { DocumentCopy } from '@element-plus/icons-vue'
import * as XLSX from 'xlsx'

export default {
  name: 'TaskDetail',
  data() {
    return {
      taskId: '',
      task: {},
      testCases: [],
      selectedCases: [],
      isLoading: true,
      showCaseDetail: false,
      selectedCase: {},
      selectedCaseIndex: 0,
      currentPage: 1,
      pageSize: 20,
      isExporting: false,
      showExportMenu: false,
      moduleFilter: '', // 妯″潡绛涢€?
      // 闇€姹傛緞娓呭璇濈浉鍏崇姸鎬?
      clarifications: [],
      clarificationInput: '',
      clarificationLoading: false,
      clarificationSubmitting: false,
      clarificationDone: false,
      // 鐢熸垚杩涘害杞鐘舵€?
      progressTimer: null,
      // 鍘熷娴佸紡鍐呭锛坰tream_buffer 涓嶅畬鏁存椂鏄剧ず锛?
      rawStreamContent: '',
      // 4琛ㄦ牸瑙嗗浘
      requirementBreakdown: '',
      generatedCases: [],
      showFourTables: false,
      // 缂栬緫鐩稿叧鐘舵€?
      isEditing: false,
      isSaving: false,
      editForm: {
        caseId: '',
        scenario: '',
        precondition: '',
        steps: '',
        expected: '',
        priority: 'P2'
      }
    }
  },

  computed: {
    isAllSelected() {
      const filtered = this.filteredTestCases
      return filtered.length > 0 && this.selectedCases.length === filtered.length
    },

    uniqueModules() {
      const modules = [...new Set(this.testCases.map(tc => tc.module).filter(Boolean))]
      return modules.sort()
    },

    filteredTestCases() {
      if (!this.moduleFilter) return this.testCases
      return this.testCases.filter(tc => tc.module === this.moduleFilter)
    },

    totalPages() {
      return Math.ceil(this.filteredTestCases.length / this.pageSize)
    },

    paginatedTestCases() {
      const start = (this.currentPage - 1) * this.pageSize
      const end = start + this.pageSize
      return this.filteredTestCases.slice(start, end)
    },

    paginationStart() {
      return (this.currentPage - 1) * this.pageSize + 1
    },

    paginationEnd() {
      return Math.min(this.currentPage * this.pageSize, this.filteredTestCases.length)
    },

    /**
     * 鏄惁澶勪簬鐢熸垚涓姸鎬侊紙闇€瑕佹樉绀鸿繘搴﹂潰鏉匡級
     */
    isGenerationInProgress() {
      const runningStates = ['generating', 'writing', 'reviewing', 'revising', 'completing', 'pending']
      return this.task && runningStates.includes(this.task.status)
    },

    /**
     * 杩涘害鐧惧垎姣旓紙浠?task.progress 璇诲彇锛岄粯璁?0锛?
     */
    progressPercent() {
      return Math.max(0, Math.min(100, Number(this.task?.progress || 0)))
    },

    /**
     * 褰撳墠闃舵鏂囨湰锛堜腑鏂囷級
     */
    progressPhaseText() {
      const map = {
        pending: '排队中...',
        generating: 'AI 正在生成测试用例...',
        writing: 'AI 正在编写测试用例...',
        reviewing: 'AI 正在评审用例质量...',
        revising: '根据评审意见优化修正...',
        completing: '最后整理中...'
      }
      const phase = map[this.task?.status] || ''
      return phase ? `${phase} ${this.progressPercent}%` : ''
    },
    streamPhaseLabel() {
      const map = {
        generating: '实时生成内容',
        writing: '实时编写内容',
        reviewing: '实时评审内容',
        revising: '实时修正内容',
        completing: '整理输出内容'
      }
      return map[this.task?.status] || '实时生成内容'
    },

    summaryMetrics() {
      return [
        {
          label: '任务状态',
          value: this.getStatusText(this.task.status || 'pending'),
          hint: this.progressPhaseText || '等待处理'
        },
        {
          label: '任务耗时',
          value: this.taskDurationText,
          hint: this.task.completed_at ? '已完成闭环' : '仍在持续更新'
        },
        {
          label: '模块覆盖',
          value: `${this.breakdownModuleCount} 个模块`,
          hint: this.breakdownModuleCount > 0 ? '来自需求拆解表' : '待拆解'
        },
        {
          label: '最终用例',
          value: `${this.testCases.length} 条`,
          hint: this.generatedCases.length > 0 ? `草稿 ${this.generatedCases.length} 条` : '等待生成'
        }
      ]
    },

    deliveryMaturity() {
      if (this.task.status === 'completed' && this.testCases.length > 0) {
        return { label: '可交付', tone: 'tone-good' }
      }
      if (this.task.status === 'failed') {
        return { label: '需修复', tone: 'tone-risk' }
      }
      if (this.isGenerationInProgress || this.task.status === 'pending_clarification') {
        return { label: '生成中', tone: 'tone-warn' }
      }
      return { label: '待完善', tone: 'tone-neutral' }
    },

    healthSignals() {
      return [
        {
          label: '澄清轮次',
          value: `${this.clarificationRounds} 轮`,
          tone: this.clarificationRounds > 0 ? 'tone-good' : 'tone-neutral'
        },
        {
          label: '评审反馈',
          value: this.task.review_feedback ? '已产出' : '暂无',
          tone: this.task.review_feedback ? 'tone-good' : 'tone-neutral'
        },
        {
          label: '采纳准备度',
          value: this.testCases.length > 0 ? `${this.selectedCases.length}/${this.testCases.length}` : '0/0',
          tone: this.testCases.length > 0 ? 'tone-warn' : 'tone-neutral'
        }
      ]
    },

    deliverableSections() {
      return [
        {
          key: 'requirement',
          ref: 'requirementSection',
          label: '需求原文',
          description: '查看完整需求输入，确认原始上下文。',
          ready: !!this.task.requirement_text,
          available: !!this.task.requirement_text
        },
        {
          key: 'breakdown',
          ref: 'breakdownSection',
          label: '模块拆解',
          description: '核对 AI 对需求模块和功能点的拆分。',
          ready: !!this.getDeliverableText('breakdown'),
          available: !!this.requirementBreakdown
        },
        {
          key: 'generated',
          ref: 'generatedSection',
          label: '编写草稿',
          description: '查看 AI 初稿用例，确认覆盖广度。',
          ready: !!this.getDeliverableText('generated'),
          available: this.generatedCases.length > 0 || !!this.rawStreamContent || this.hasGeneratedDraftSummary
        },
        {
          key: 'review',
          ref: 'reviewSection',
          label: '评审意见',
          description: '聚焦 AI 发现的问题与修订建议。',
          ready: !!this.getDeliverableText('review'),
          available: !!this.getDeliverableText('review')
        },
        {
          key: 'final',
          ref: 'finalSection',
          label: '最终用例',
          description: '交付最终版本，支持继续采纳和导出。',
          ready: !!this.getDeliverableText('final'),
          available: this.testCases.length > 0
        }
      ]
    },

    decisionLogEntries() {
      const entries = [
        {
          title: '需求已接收',
          meta: this.task.created_at ? this.formatDateTime(this.task.created_at) : '刚刚创建',
          description: `原始需求约 ${this.requirementSizeText}，已进入 AI 任务流水线。`,
          tone: 'tone-good'
        },
        {
          title: '需求澄清',
          meta: this.clarificationRounds > 0 ? `${this.clarificationRounds} 轮对话` : '未触发',
          description: this.clarificationRounds > 0
            ? '系统已记录澄清往返，可回溯 AI 提问与人工补充。'
            : '当前任务未产生澄清轮次，默认按原始输入推进。',
          tone: this.clarificationRounds > 0 ? 'tone-good' : 'tone-neutral'
        },
        {
          title: '模块拆解',
          meta: `${this.breakdownModuleCount} 个模块`,
          description: this.breakdownModuleCount > 0
            ? '需求已被拆解为可执行模块，便于覆盖范围检查。'
            : '尚未产出模块拆解结果。',
          tone: this.breakdownModuleCount > 0 ? 'tone-good' : 'tone-neutral'
        },
        {
          title: '初稿编写',
          meta: `${this.generatedCases.length || 0} 条草稿`,
          description: this.generatedCases.length > 0
            ? 'AI 已输出首版测试用例草稿，可作为覆盖基线。'
            : '初稿尚未准备完成。',
          tone: this.generatedCases.length > 0 ? 'tone-good' : 'tone-neutral'
        },
        {
          title: '质量评审',
          meta: this.task.review_feedback ? '已完成' : '未产出',
          description: this.task.review_feedback
            ? `评审内容已沉淀，当前摘要：${this.reviewFeedbackSummary}`
            : '暂无评审反馈，质量判断信息不足。',
          tone: this.task.review_feedback ? 'tone-warn' : 'tone-neutral'
        },
        {
          title: '最终交付',
          meta: this.task.completed_at ? this.formatDateTime(this.task.completed_at) : '进行中',
          description: this.testCases.length > 0
            ? `最终交付 ${this.testCases.length} 条用例，可直接继续采纳、导出和评审。`
            : '最终用例尚未落地，交付链路未闭环。',
          tone: this.testCases.length > 0 ? 'tone-good' : 'tone-risk'
        }
      ]

      if (this.task.error_message) {
        entries.push({
          title: '异常提示',
          meta: '系统告警',
          description: this.task.error_message,
          tone: 'tone-risk'
        })
      }

      return entries
    },

    taskDurationText() {
      const start = this.task.created_at ? new Date(this.task.created_at) : null
      const end = this.task.completed_at ? new Date(this.task.completed_at) : (this.task.updated_at ? new Date(this.task.updated_at) : null)
      if (!start || !end || Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return '暂无'
      const diffMinutes = Math.max(1, Math.round((end - start) / 60000))
      if (diffMinutes < 60) return `${diffMinutes} 分钟`
      const hours = Math.floor(diffMinutes / 60)
      const minutes = diffMinutes % 60
      return minutes ? `${hours} 小时 ${minutes} 分钟` : `${hours} 小时`
    },

    breakdownModuleCount() {
      const text = this.requirementBreakdown || this.task.requirement_breakdown || ''
      if (!text) return 0
      const lines = text
        .split('\n')
        .map(line => line.trim())
        .filter(line => line.startsWith('|') && !line.includes('---'))
      return Math.max(lines.length - 1, 0)
    },

    clarificationRounds() {
      return this.clarifications.filter(item => item.role === 'user').length
    },

    requirementSizeText() {
      const length = (this.task.requirement_text || '').replace(/\s+/g, '').length
      if (!length) return '0 字'
      return `${length} 字`
    },

    reviewFeedbackSummary() {
      const text = (this.task.review_feedback || '').replace(/\s+/g, ' ').trim()
      if (!text) return '暂无摘要'
      return text.slice(0, 42) + (text.length > 42 ? '...' : '')
    },

    hasGeneratedDraftSummary() {
      return (this.task.status === 'completed' || this.task.status === 'revising' || this.task.status === 'completing') && !!this.getDeliverableText('generated')
    }
  },

  mounted() {
    this.taskId = this.$route.params.taskId
    this.loadTaskDetail()
    // 鍚姩婊氬姩鍚搁《閫昏緫
    this.$nextTick(() => {
      this.initStickyHeader()
    })
  },

  beforeUnmount() {
    // 娓呯悊婊氬姩鐩戝惉
    if (this._scrollContainer && this._onScroll) {
      this._scrollContainer.removeEventListener('scroll', this._onScroll)
    }
    window.removeEventListener('resize', this._onResize)
    // 鍋滄杩涘害杞
    this.stopProgressPolling()
  },

  methods: {
    // 鍒濆鍖栧惛椤讹紙JS 瀹炵幇锛岄伩鍏?sticky 鍦ㄦ粴鍔ㄥ鍣ㄤ腑鐨勯棶棰橈級
    initStickyHeader() {
      // 鏌ユ壘瀹為檯婊氬姩瀹瑰櫒锛?el-main锛?
      const scrollContainer = document.querySelector('.el-main') || window
      this._scrollContainer = scrollContainer === window ? window : scrollContainer

      const batchActions = this.$el.querySelector('.batch-actions')
      const tableHeader = this.$el.querySelector('.table-header')
      if (!batchActions || !tableHeader) return

      // 闃叉閲嶅鍒濆鍖栵細濡傛灉宸插瓨鍦?placeholder 鍒欏厛绉婚櫎
      const oldBatchPh = batchActions.previousElementSibling
      if (oldBatchPh && oldBatchPh.classList && oldBatchPh.classList.contains('sticky-placeholder')) {
        oldBatchPh.remove()
      }
      const oldHeaderPh = tableHeader.previousElementSibling
      if (oldHeaderPh && oldHeaderPh.classList && oldHeaderPh.classList.contains('sticky-placeholder')) {
        oldHeaderPh.remove()
      }
      // 绉婚櫎鏃х殑 scroll 浜嬩欢鐩戝惉锛堥槻姝㈤噸澶嶇粦瀹氾級
      if (this._stickyCleanup) {
        this._stickyCleanup()
        this._stickyCleanup = null
      }

      // 鍒涘缓鍗犱綅鍗犱綅绗︼紝闃叉 fixed 鍚庨〉闈㈠穿濉?
      const batchPlaceholder = document.createElement('div')
      const headerPlaceholder = document.createElement('div')
      batchPlaceholder.className = 'sticky-placeholder'
      headerPlaceholder.className = 'sticky-placeholder'
      batchPlaceholder.style.display = 'none'
      headerPlaceholder.style.display = 'none'
      batchActions.parentNode.insertBefore(batchPlaceholder, batchActions)
      tableHeader.parentNode.insertBefore(headerPlaceholder, tableHeader)

      // 璁板綍鍘熷鍋忕Щ锛堢浉瀵规粴鍔ㄥ鍣級
      const getOffset = () => {
        const containerRect = this._scrollContainer === window
          ? { top: 0, left: 0 }
          : this._scrollContainer.getBoundingClientRect()
        const batchRect = batchPlaceholder.style.display === 'none'
          ? batchActions.getBoundingClientRect()
          : batchPlaceholder.getBoundingClientRect()
        return {
          batchTop: batchRect.top - containerRect.top + (this._scrollContainer === window ? window.scrollY : this._scrollContainer.scrollTop),
          containerLeft: this._scrollContainer === window ? 0 : containerRect.left,
          contentLeft: batchRect.left,
          contentWidth: batchActions.offsetWidth,
        }
      }

      let initialOffset = null

      const updateSticky = () => {
        if (!initialOffset) {
          initialOffset = getOffset()
        }
        const scrollTop = this._scrollContainer === window
          ? window.scrollY
          : this._scrollContainer.scrollTop
        const containerRect = this._scrollContainer === window
          ? { top: 0, left: 0 }
          : this._scrollContainer.getBoundingClientRect()

        const shouldStick = scrollTop >= initialOffset.batchTop - (this._scrollContainer === window ? 0 : 0)

        if (shouldStick) {
          // 璁剧疆鍗犱綅楂樺害
          if (batchPlaceholder.style.display === 'none') {
            batchPlaceholder.style.height = batchActions.offsetHeight + 'px'
            batchPlaceholder.style.marginBottom = window.getComputedStyle(batchActions).marginBottom
            headerPlaceholder.style.height = tableHeader.offsetHeight + 'px'
            batchPlaceholder.style.display = 'block'
            headerPlaceholder.style.display = 'block'
          }

          // 璁＄畻瀹藉害鍜屽乏杈硅窛锛堜娇鐢ㄥ崰浣嶇浣嶇疆锛?
          const placeholderRect = batchPlaceholder.getBoundingClientRect()
          const headerPlaceholderRect = headerPlaceholder.getBoundingClientRect()

          batchActions.style.position = 'fixed'
          batchActions.style.top = containerRect.top + 'px'
          batchActions.style.left = placeholderRect.left + 'px'
          batchActions.style.width = placeholderRect.width + 'px'
          batchActions.style.zIndex = '100'
          batchActions.style.boxShadow = '0 2px 8px rgba(0,0,0,0.1)'

          tableHeader.style.position = 'fixed'
          tableHeader.style.top = (containerRect.top + batchActions.offsetHeight) + 'px'
          tableHeader.style.left = headerPlaceholderRect.left + 'px'
          tableHeader.style.width = headerPlaceholderRect.width + 'px'
          tableHeader.style.zIndex = '99'
          tableHeader.style.boxShadow = '0 2px 8px rgba(0,0,0,0.1)'
        } else {
          // 鎭㈠鍘熷鐘舵€?
          if (batchPlaceholder.style.display !== 'none') {
            batchPlaceholder.style.display = 'none'
            headerPlaceholder.style.display = 'none'
          }
          batchActions.style.position = ''
          batchActions.style.top = ''
          batchActions.style.left = ''
          batchActions.style.width = ''
          batchActions.style.zIndex = ''
          batchActions.style.boxShadow = ''

          tableHeader.style.position = ''
          tableHeader.style.top = ''
          tableHeader.style.left = ''
          tableHeader.style.width = ''
          tableHeader.style.zIndex = ''
          tableHeader.style.boxShadow = ''
        }
      }

      // 鑺傛祦
      let rafId = null
      const onScroll = () => {
        if (rafId) return
        rafId = requestAnimationFrame(() => {
          updateSticky()
          rafId = null
        })
      }

      const onResize = () => {
        initialOffset = null
        updateSticky()
      }

      this._onScroll = onScroll
      this._onResize = onResize
      this._scrollContainer.addEventListener('scroll', onScroll, { passive: true })
      window.addEventListener('resize', onResize)

      // 鎻愪緵 cleanup 鍑芥暟渚涢噸澶嶈皟鐢ㄦ椂浣跨敤
      this._stickyCleanup = () => {
        if (this._onScroll && this._scrollContainer) {
          this._scrollContainer.removeEventListener('scroll', this._onScroll)
        }
        if (this._onResize) {
          window.removeEventListener('resize', this._onResize)
        }
        this._onScroll = null
        this._onResize = null
      }
    },

    // 澶嶅埗闇€姹傛弿杩版枃鏈?
    async copyRequirementText() {
      try {
        await navigator.clipboard.writeText(this.task.requirement_text)
        ElMessage.success(this.$t('taskDetail.copySuccess'))
      } catch (error) {
        // 濡傛灉 navigator.clipboard 涓嶅彲鐢?浣跨敤澶囩敤鏂规硶
        const textArea = document.createElement('textarea')
        textArea.value = this.task.requirement_text
        textArea.style.position = 'fixed'
        textArea.style.opacity = '0'
        document.body.appendChild(textArea)
        textArea.select()
        try {
          document.execCommand('copy')
          ElMessage.success(this.$t('taskDetail.copySuccess'))
        } catch (err) {
          ElMessage.error(this.$t('taskDetail.copyFailed'))
        }
        document.body.removeChild(textArea)
      }
    },

    async copyDeliverable(kind) {
      const text = this.getDeliverableText(kind)
      if (!text) {
        ElMessage.warning('当前交付物还没有可复制内容')
        return
      }
      await this.copyText(text, '交付物内容已复制')
    },

    scrollToSection(refName) {
      const target = this.$refs[refName]
      const element = Array.isArray(target) ? target[0] : target
      if (!element || typeof element.getBoundingClientRect !== 'function') {
        ElMessage.warning('该区块还未生成完成')
        return
      }

      const headerOffset = 96
      const absoluteTop = window.scrollY + element.getBoundingClientRect().top
      const targetTop = Math.max(0, absoluteTop - headerOffset)

      window.scrollTo({
        top: targetTop,
        behavior: 'smooth'
      })

      element.classList.remove('section-flash')
      void element.offsetWidth
      element.classList.add('section-flash')

      if (element._sectionFlashTimer) {
        window.clearTimeout(element._sectionFlashTimer)
      }

      element._sectionFlashTimer = window.setTimeout(() => {
        element.classList.remove('section-flash')
      }, 1800)
    },

    getDeliverableText(kind) {
      const map = {
        requirement: this.task.requirement_text || '',
        breakdown: this.requirementBreakdown || this.task.requirement_breakdown || '',
        generated: this.task.generated_test_cases || this.rawStreamContent || '',
        review: this.task.review_feedback || '',
        final: this.task.final_test_cases || ''
      }
      return map[kind] || ''
    },

    async copyText(text, successMessage = '复制成功') {
      try {
        await navigator.clipboard.writeText(text)
        ElMessage.success(successMessage)
      } catch (error) {
        const textArea = document.createElement('textarea')
        textArea.value = text
        textArea.style.position = 'fixed'
        textArea.style.opacity = '0'
        document.body.appendChild(textArea)
        textArea.select()
        try {
          document.execCommand('copy')
          ElMessage.success(successMessage)
        } catch (err) {
          ElMessage.error(this.$t('taskDetail.copyFailed'))
        }
        document.body.removeChild(textArea)
      }
    },

    formatDateTime(iso) {
      if (!iso) return ''
      try {
        const d = new Date(iso)
        const yyyy = d.getFullYear()
        const mm = String(d.getMonth() + 1).padStart(2, '0')
        const dd = String(d.getDate()).padStart(2, '0')
        const hh = String(d.getHours()).padStart(2, '0')
        const mi = String(d.getMinutes()).padStart(2, '0')
        return `${yyyy}-${mm}-${dd} ${hh}:${mi}`
      } catch {
        return ''
      }
    },

    async loadTaskDetail() {
      try {
        // 鑾峰彇浠诲姟鍩烘湰淇℃伅
        const taskResponse = await api.get(`/requirement-analysis/testcase-generation/${this.taskId}/`)
        this.task = taskResponse.data

        // 瑙ｆ瀽鏈€缁堟祴璇曠敤渚?
        if (this.task.final_test_cases) {
          this.testCases = this.parseTestCases(this.task.final_test_cases)
        }

        // ===== 宸插畬鎴?澶辫触锛?琛ㄦ牸鐎戝竷娴?+ 鍋滄杞 =====
        if (this.task.status === 'completed' || this.task.status === 'failed') {
          this.stopProgressPolling()
          this.rawStreamContent = ''  // 娓呯┖娴佸紡棰勮

          // 瑙ｆ瀽闇€姹傛媶鍒嗚〃 鈫?琛ㄦ牸1
          if (this.task.requirement_breakdown && this.task.requirement_breakdown.trim()) {
            this.requirementBreakdown = this.task.requirement_breakdown.trim()
          }

          // 瑙ｆ瀽 AI 缂栧啓鐢ㄤ緥 鈫?琛ㄦ牸2
          if (this.task.generated_test_cases && this.task.generated_test_cases.trim()) {
            this.generatedCases = this.parseTestCases(this.task.generated_test_cases)
          }

          // 鏍囪鍚敤4琛ㄦ牸瑙嗗浘
          this.showFourTables = true
        }

        // 鑻ヤ换鍔″浜庨渶姹傛緞娓呴樁娈碉紝鎷夊彇瀵硅瘽鍘嗗彶锛涜嫢涓虹┖鍒欒嚜鍔ㄥ惎鍔ㄩ杞彁闂?
        if (this.task.status === 'pending_clarification') {
          await this.loadClarifications()
          if (this.clarifications.length === 0) {
            await this.startClarification()
          }
        } else {
          // 闈?pending_clarification 鐘舵€侊細纭繚娓呯悊婢勬竻闈㈡澘娈嬬暀鐘舵€?
          this.clarifications = []
          this.clarificationLoading = false
          this.clarificationDone = false
        }

        // 鑻ヤ换鍔″浜庣敓鎴愮姸鎬侊紝鍚姩杩涘害杞
        if (this.isGenerationInProgress && !this.progressTimer) {
          this.startProgressPolling()
        }

        // 鏁版嵁鍔犺浇鍚庨噸鏂板垵濮嬪寲鍚搁《锛堝洜涓烘鏃?batch-actions 鍜?table-header 鎵嶈娓叉煋锛?
        this.$nextTick(() => {
          this.initStickyHeader()
        })
      } catch (error) {
        console.error('Failed to load task details:', error)
        ElMessage.error(this.$t('taskDetail.loadFailed'))
      } finally {
        this.isLoading = false
      }
    },

    // ==================== 鐢熸垚杩涘害杞鐩稿叧鏂规硶 ====================

    /**
     * 鍚姩杩涘害杞锛堜换鍔¤繘鍏?generating/reviewing/revising/completing 鍚庤皟鐢級
     */
    startProgressPolling() {
      if (this.progressTimer) return
      this.fetchTaskProgress()
      // 涔嬪悗姣?1.5 绉掕疆璇竴娆?
      this.progressTimer = setInterval(() => {
        this.fetchTaskProgress()
      }, 1500)
    },

    /**
     * 鍋滄杩涘害杞
     */
    stopProgressPolling() {
      if (this.progressTimer) {
        clearInterval(this.progressTimer)
        this.progressTimer = null
      }
    },

    /**
     * 鏌ヨ浠诲姟褰撳墠杩涘害锛堝鐢?detail 鎺ュ彛锛?
     * - 鐘舵€佷粛鍦ㄨ繘琛屼腑 鈫?鏇存柊 task 鍗冲彲锛堣绠楀睘鎬ц嚜鍔ㄩ┍鍔?UI锛?
     * - 鐘舵€佸彉涓?completed/failed 鈫?鍋滄杞 + 瑙ｆ瀽鏈€缁堢敤渚?
     */
    async fetchTaskProgress() {
      try {
        const resp = await api.get(`/requirement-analysis/testcase-generation/${this.taskId}/`)
        // 浣跨敤鍚堝苟璧嬪€硷紝閬垮厤涓㈠け鏈湴鍙瀛楁
        this.task = { ...this.task, ...resp.data }

        // ===== status 寮哄埗鍚屾锛堥槻姝㈢紦瀛?鍚堝苟瀵艰嚧 status 鍗℃棫鍊硷級=====
        if (resp.data && resp.data.status && resp.data.status !== this.task.status) {
          this.task.status = resp.data.status
        }

        // ===== 婢勬竻闈㈡澘鐘舵€佸悓姝ラ槻鎶?=====
        // 鏃犺浣曟椂锛屽彧瑕?status 涓嶆槸 pending_clarification锛屽氨寮哄埗娓呯悊婢勬竻闈㈡澘
        if (this.task.status !== 'pending_clarification') {
          if (this.clarifications.length > 0 || this.clarificationLoading) {
            this.clarifications = []
            this.clarificationLoading = false
            this.clarificationDone = false
          }
        }

        // 瀹炴椂娴佸紡杈撳嚭閫昏緫 鈥?涓夐樁娈靛悇鑷湁娴佸紡婧?
        const activeStatuses = ['pending', 'generating', 'writing', 'reviewing', 'revising', 'completing', 'pending_clarification', 'clarified']
        if (activeStatuses.includes(this.task.status)) {
          // completed/failed 涔嬪墠鐨勯樁娈碉細濮嬬粓鏄剧ず鐎戝竷娴佹枃鏈瑙堬紙涓嶈В鏋愪负琛ㄦ牸锛?
          let streamSource = ''
          if (this.task.status === 'reviewing' && this.task.review_feedback && this.task.review_feedback.trim()) {
            // reviewing 闃舵锛氳鍙?review_feedback
            streamSource = this.task.review_feedback
          } else if (this.task.status === 'revising' && this.task.final_test_cases && this.task.final_test_cases.trim()) {
            // revising 闃舵锛氳鍙?final_test_cases
            streamSource = this.task.final_test_cases
          } else if (this.task.stream_buffer && this.task.stream_buffer.trim()) {
            // writing 闃舵鍙婁箣鍓嶏細璇诲彇 stream_buffer
            streamSource = this.task.stream_buffer
          } else if (this.task.final_test_cases && this.task.final_test_cases.trim()) {
            // 鍏滃簳锛氬鏋滄湁 final_test_cases 涔熸樉绀?
            streamSource = this.task.final_test_cases
          }
          this.rawStreamContent = streamSource
          this.testCases = [] // 鐎戝竷娴佹ā寮忎笉鏄剧ず琛ㄦ牸
        }

        if (this.task.status === 'completed' || this.task.status === 'failed') {
          this.stopProgressPolling()
          this.rawStreamContent = ''  // 娓呯┖娴佸紡棰勮锛岄伩鍏?completed 鍚庝粛鏄剧ず"AI姝ｅ湪鐢熸垚"

          // 瑙ｆ瀽鏈€缁堢敤渚?鈫?琛ㄦ牸4锛堟渶缁堢増娴嬭瘯鐢ㄤ緥锛?
          if (this.task.final_test_cases) {
            this.testCases = this.parseTestCases(this.task.final_test_cases)
          }

          // 瑙ｆ瀽闇€姹傛媶鍒嗚〃 鈫?琛ㄦ牸1
          if (this.task.requirement_breakdown && this.task.requirement_breakdown.trim()) {
            this.requirementBreakdown = this.task.requirement_breakdown.trim()
          }

          // 瑙ｆ瀽 AI 缂栧啓鐢ㄤ緥 鈫?琛ㄦ牸2
          if (this.task.generated_test_cases && this.task.generated_test_cases.trim()) {
            this.generatedCases = this.parseTestCases(this.task.generated_test_cases)
          }

          // 鏍囪鍚敤4琛ㄦ牸瑙嗗浘
          this.showFourTables = true

          if (this.task.status === 'completed') {
            ElMessage.success('测试用例生成完成')
          } else {
            ElMessage.error(this.task.error_message || '鐢熸垚澶辫触')
          }

          // 閲嶆柊鍒濆鍖栧惛椤讹紙琛ㄦ牸鍑虹幇鍚庨渶瑕侊級
          this.$nextTick(() => {
            this.initStickyHeader()
          })
        } else {
          // ===== 杩涜涓姸鎬侊細瀹炴椂鏇存柊4涓〃鏍肩殑鏁版嵁婧?=====
          // 琛ㄦ牸1锛氶渶姹傛媶鍒嗚〃锛坵riting 闃舵瀹屾垚鍚庡氨鏈夛級
          if (this.task.requirement_breakdown && this.task.requirement_breakdown.trim()) {
            this.requirementBreakdown = this.task.requirement_breakdown.trim()
          }
          // 琛ㄦ牸2锛欰I 缂栧啓鐢ㄤ緥锛坰tream_buffer 灏辨槸缂栧啓鍐呭锛?
          if (this.task.stream_buffer && this.task.stream_buffer.trim()) {
            // 杩涜涓椂涔熷皾璇曡В鏋愪负琛ㄦ牸锛岃В鏋愬け璐ヤ篃涓嶅奖鍝?
            const parsed = this.parseTestCases(this.task.stream_buffer)
            if (parsed.length > 0) {
              this.generatedCases = parsed
            }
          }
          // 琛ㄦ牸3锛欰I 璇勫鎰忚锛坮eview_feedback锛?
          // 琛ㄦ牸4锛氭渶缁堢敤渚嬶紙final_test_cases锛宺evising 闃舵鎵嶆湁锛?
        }
      } catch (error) {
        console.error('Failed to fetch progress:', error)
        // 杞鏈熼棿涓嶅脊绐楋紝閬垮厤楠ㄦ壈
      }
    },

    // ==================== 闇€姹傛緞娓呭璇濈浉鍏虫柟娉?====================

    /**
     * 鎷夊彇婢勬竻瀵硅瘽鍘嗗彶
     */
    async loadClarifications() {
      try {
        const resp = await api.get(
          `/requirement-analysis/testcase-generation/${this.taskId}/clarifications/`
        )
        this.clarifications = resp.data.clarifications || []
        // 妫€鏌ユ渶鍚庝竴鏉?AI 娑堟伅鏄惁鏍囪婢勬竻瀹屾垚
        this.updateClarificationDone()
        this.scrollToBottom()
      } catch (error) {
        console.error('Failed to load clarifications:', error)
      }
    },

    /**
     * 鍚姩棣栬疆婢勬竻锛圓I 鎻愰棶锛?
     */
    async startClarification() {
      this.clarificationLoading = true
      // 鍒涘缓 AbortController 浠ユ敮鎸佽烦杩囨緞娓呮椂鍙栨秷璇锋眰
      this._clarificationAbortController = new AbortController()
      try {
        const resp = await api.post(
          `/requirement-analysis/testcase-generation/${this.taskId}/start-clarification/`
        , {}, { timeout: 180000, signal: this._clarificationAbortController.signal })
        // 妫€鏌ユ槸鍚﹀凡琚烦杩囧彇娑堬紙闃叉绔炴€乸ush锛?
        if (this.task.status !== 'pending_clarification') {
          return
        }
        if (resp.data.clarification) {
          this.clarifications.push(resp.data.clarification)
        } else if (resp.data.clarifications) {
          this.clarifications = resp.data.clarifications
        }
        this.updateClarificationDone()
        this.scrollToBottom()
      } catch (error) {
        // 鐢ㄦ埛涓诲姩鍙栨秷锛堣烦杩囨緞娓咃級鏄甯歌涓猴紝闈欓粯澶勭悊
        if (axios.isCancel(error)) {
          return
        }
        console.error('Failed to start clarification:', error)
        ElMessage.error(error.response?.data?.error || this.$t('taskDetail.clarificationStartFailed'))
      } finally {
        this.clarificationLoading = false
        this._clarificationAbortController = null
      }
    },

    /**
     * 鎻愪氦鐢ㄦ埛鍥炲锛岃幏鍙?AI 涓嬩竴杞?
     */
    async submitClarification() {
      const text = this.clarificationInput.trim()
      if (!text || this.clarificationSubmitting || this.clarificationDone) return

      this.clarificationSubmitting = true
      // 涔愯 push 鐢ㄦ埛娑堟伅鍒版湰鍦帮紝鍚庣杩斿洖鍚庢浛鎹?
      const optimisticUser = {
        id: `tmp-${Date.now()}`,
        role: 'user',
        content: text,
        created_at: new Date().toISOString(),
      }
      this.clarifications.push(optimisticUser)
      this.clarificationInput = ''
      this.scrollToBottom()

      try {
        const resp = await api.post(
          `/requirement-analysis/testcase-generation/${this.taskId}/clarification-reply/`,
          { content: text },
          { timeout: 180000 }
        )
        // 鏇挎崲 optimistic 鐢ㄦ埛娑堟伅涓哄悗绔繑鍥炵殑 user_message
        const idx = this.clarifications.findIndex(m => m.id === optimisticUser.id)
        if (idx !== -1 && resp.data.user_message) {
          this.clarifications.splice(idx, 1, resp.data.user_message)
        }
        if (resp.data.ai_message) {
          this.clarifications.push(resp.data.ai_message)
        }
        this.updateClarificationDone()
        this.scrollToBottom()
      } catch (error) {
        console.error('Failed to submit clarification:', error)
        ElMessage.error(error.response?.data?.error || this.$t('taskDetail.clarificationReplyFailed'))
        // 鍥炴粴涔愯 push
        this.clarifications = this.clarifications.filter(m => m.id !== optimisticUser.id)
        this.clarificationInput = text
      } finally {
        this.clarificationSubmitting = false
      }
    },

    /**
     * 瀹岀粨婢勬竻骞跺惎鍔ㄧ敓鎴?
     */
    async finalizeClarification() {
      try {
        await ElMessageBox.confirm(
          this.$t('taskDetail.clarificationFinalizeConfirm'),
          this.$t('taskDetail.clarificationFinalize'),
          { confirmButtonText: this.$t('taskDetail.btnConfirm') || '纭畾', cancelButtonText: this.$t('taskDetail.btnCancel') || '鍙栨秷', type: 'warning' }
        )
      } catch {
        return
      }

      this.clarificationSubmitting = true
      try {
        const resp = await api.post(
          `/requirement-analysis/testcase-generation/${this.taskId}/finalize-clarification/`
        )
        ElMessage.success(resp.data.message || this.$t('taskDetail.clarificationFinalized'))
        // 鍒锋柊浠诲姟鐘舵€?
        await this.loadTaskDetail()
        // 鏄庣‘鍚姩杩涘害杞锛堝悗绔細鍦ㄥ悗鍙扮嚎绋嬩腑鍚姩鐢熸垚锛岃繘鍏?generating 鐘舵€佸彲鑳芥花鍚庝簬 POST 杩斿洖锛?
        if (!this.progressTimer) {
          this.startProgressPolling()
        }
      } catch (error) {
        console.error('Failed to finalize clarification:', error)
        ElMessage.error(error.response?.data?.error || this.$t('taskDetail.clarificationFinalizeFailed'))
      } finally {
        this.clarificationSubmitting = false
      }
    },

    /**
     * 璺宠繃婢勬竻鐩存帴鐢熸垚
     */
    async skipClarification() {
      try {
        await ElMessageBox.confirm(
          this.$t('taskDetail.clarificationSkipConfirm'),
          this.$t('taskDetail.clarificationSkip'),
          { confirmButtonText: this.$t('taskDetail.btnConfirm') || '纭畾', cancelButtonText: this.$t('taskDetail.btnCancel') || '鍙栨秷', type: 'warning' }
        )
      } catch {
        return
      }

      // 鍙栨秷鍙兘姝ｅ湪杩涜鐨?startClarification 璇锋眰锛堥槻姝㈢珵鎬侊細AI闂杩斿洖鍚巔ush鍒癱larifications锛?
      if (this._clarificationAbortController) {
        try { this._clarificationAbortController.abort() } catch(e) { /* ignore */ }
        this._clarificationAbortController = null
      }

      this.clarificationSubmitting = true
      try {
        const resp = await api.post(
          `/requirement-analysis/testcase-generation/${this.taskId}/skip-clarification/`
        )
        ElMessage.success(resp.data.message || this.$t('taskDetail.clarificationSkipped'))
        // 娓呯┖婢勬竻瀵硅瘽鏁版嵁锛岄槻姝㈠凡鐢熸垚鐨凙I闂缁х画鏄剧ず
        this.clarifications = []
        this.clarificationLoading = false
        this.clarificationDone = false
        // 绔嬪嵆寮哄埗鏇存柊 task.status锛岄伩鍏嶉潰鏉块棯鐑侊紙鍚庣宸叉敼涓?clarified/writing锛?
        if (resp.data && resp.data.status) {
          this.task = { ...this.task, status: resp.data.status }
        }
        await this.loadTaskDetail()
        if (!this.progressTimer) {
          this.startProgressPolling()
        }
      } catch (error) {
        console.error('Failed to skip clarification:', error)
        ElMessage.error(error.response?.data?.error || this.$t('taskDetail.clarificationSkipFailed'))
      } finally {
        this.clarificationSubmitting = false
      }
    },

    /**
     * 妫€鏌ユ渶杩戜竴鏉?AI 娑堟伅鏄惁鍚?[CLARIFICATION_DONE] 鏍囪
     */
    updateClarificationDone() {
      const lastAi = [...this.clarifications].reverse().find(m => m.role === 'ai')
      this.clarificationDone = !!(lastAi && /\[CLARIFICATION_DONE\]/.test(lastAi.content || ''))
    },

    /**
     * 婢勬竻瀵硅瘽鍖鸿嚜鍔ㄦ粴鍔ㄥ埌搴曢儴
     */
    scrollToBottom() {
      this.$nextTick(() => {
        const el = this.$refs.clarificationMessages
        if (el) el.scrollTop = el.scrollHeight
      })
    },

    /**
     * 鏍煎紡鍖栨椂闂存樉绀猴紙HH:mm锛?
     */
    formatTime(iso) {
      if (!iso) return ''
      try {
        const d = new Date(iso)
        const hh = String(d.getHours()).padStart(2, '0')
        const mm = String(d.getMinutes()).padStart(2, '0')
        return `${hh}:${mm}`
      } catch {
        return ''
      }
    },

    parseTestCases(content) {
      // 澶嶇敤RequirementAnalysisView涓殑瑙ｆ瀽閫昏緫
      if (!content) return []

      // 鍘婚櫎markdown鍔犵矖鏍囪,淇濈暀绾噣鏂囨湰
      let cleanContent = content.replace(/\*\*([^*]+)\*\*/g, '$1')

      const lines = cleanContent.split('\n').filter(line => line.trim())
      const testCases = []

      // 灏濊瘯瑙ｆ瀽琛ㄦ牸鏍煎紡
      let isTableFormat = false
      const tableData = []

      for (let line of lines) {
        const trimmedLine = line.trim()
        if (trimmedLine.includes('|') && !trimmedLine.includes('--------')) {
          const cells = trimmedLine.split('|').map(cell => cell.trim()).filter(cell => cell)
          if (cells.length > 1) {
            tableData.push(cells)
            isTableFormat = true
          }
        }
      }

      if (isTableFormat && tableData.length > 1) {
        // 琛ㄦ牸鏍煎紡瑙ｆ瀽
        const headers = tableData[0]
        for (let i = 1; i < tableData.length; i++) {
          const row = tableData[i]
          const testCase = {}

          // 娓呯悊<br>鏍囩鐨勮緟鍔╁嚱鏁?
          const cleanBrTags = (text) => {
            if (!text) return ''
            return text.replace(/<br\s*\/?>/gi, '\n')
          }

          headers.forEach((header, index) => {
            const value = cleanBrTags(row[index] || '')

            // 浣跨敤鏇寸簿纭殑鍖归厤閫昏緫,閬垮厤璇垽
            const cleanHeader = header.trim().toLowerCase()

            // 妯″潡鍖归厤
            if (cleanHeader === 'module' || cleanHeader === '模块' || cleanHeader.includes('module')) {
              testCase.module = value
            } else if (cleanHeader === 'priority' || cleanHeader === '优先级' || cleanHeader.includes('priority')) {
              testCase.priority = value
            } else if (cleanHeader === '鐢ㄤ緥id' || cleanHeader === '缂栧彿' || cleanHeader === 'id' || cleanHeader.includes('鐢ㄤ緥id')) {
              testCase.caseId = value
            } else if (cleanHeader === '娴嬭瘯鐩爣' || cleanHeader === '娴嬭瘯鍦烘櫙' || cleanHeader === '鍦烘櫙' || cleanHeader === '鏍囬' || cleanHeader.includes('娴嬭瘯鐩爣')) {
              testCase.scenario = value
            } else if (cleanHeader === '鍓嶇疆鏉′欢' || cleanHeader === '鍓嶇疆' || cleanHeader === '鍓嶆彁鏉′欢') {
              testCase.precondition = value
            } else if (cleanHeader === '娴嬭瘯姝ラ' || cleanHeader === '鎿嶄綔姝ラ' || cleanHeader === '姝ラ') {
              // 纭繚涓嶈璇尮閰?棰勬湡缁撴灉"涓寘鍚殑"姝ラ"瀛楁牱
              if (!cleanHeader.includes('棰勬湡') && !cleanHeader.includes('缁撴灉')) {
                testCase.steps = value
              }
            } else if (cleanHeader === '棰勬湡缁撴灉' || cleanHeader === '棰勬湡' || cleanHeader === '缁撴灉' || cleanHeader.includes('棰勬湡缁撴灉')) {
              testCase.expected = value
            } else if (cleanHeader === '娴嬭瘯绫诲瀷' || cleanHeader.includes('娴嬭瘯绫诲瀷') || cleanHeader === 'type') {
              testCase.testType = value
            } else if (cleanHeader === '关联需求' || cleanHeader === 'related requirement' || cleanHeader.includes('关联需求') || cleanHeader.includes('related')) {
              testCase.relatedReq = value
            }
          })

          if ((!testCase.scenario && !testCase.caseId) && row.length >= 6) {
            testCase.module = testCase.module || cleanBrTags(row[0] || '')
            testCase.caseId = testCase.caseId || cleanBrTags(row[1] || `TC${String(i).padStart(3, '0')}`)
            testCase.scenario = testCase.scenario || cleanBrTags(row[2] || '')
            testCase.precondition = testCase.precondition || cleanBrTags(row[3] || '')
            testCase.steps = testCase.steps || cleanBrTags(row[4] || '')
            testCase.expected = testCase.expected || cleanBrTags(row[5] || '')
            testCase.priority = testCase.priority || cleanBrTags(row[6] || 'P2')
            testCase.testType = testCase.testType || cleanBrTags(row[7] || '')
          }

          if (testCase.scenario || testCase.caseId) {
            // If steps field is empty, use scenario as default
            if (!testCase.steps && testCase.scenario) {
              testCase.steps = testCase.scenario
            }
            // 濡傛灉娌℃湁priority,璁剧疆榛樿鍊?
            if (!testCase.priority) {
              testCase.priority = 'P2'
            }
            testCases.push(testCase)
          }
        }
      } else {
        // 缁撴瀯鍖栨枃鏈牸寮忚В鏋?
        let currentTestCase = {}
        let caseNumber = 1

        for (const line of lines) {
          if (line.includes('娴嬭瘯鐢ㄤ緥') || line.includes('Test Case') ||
              line.match(/^(\d+[\.、]|\*|\-)\s*/)) {

            if (Object.keys(currentTestCase).length > 0) {
              testCases.push(currentTestCase)
              caseNumber++
            }

            currentTestCase = {
              caseId: `TC${String(caseNumber).padStart(3, '0')}`,
              scenario: line.replace(/^(\d+[\.、]|\*|\-)\s*/, '').replace(/娴嬭瘯鐢ㄤ緥\d*[::]?\s*/, '').replace(/Test Case\s*\d*[::]?\s*/i, ''),
              precondition: '',
              steps: '',
              expected: '',
              priority: 'P2'
            }
          } else if (line.includes('鍓嶇疆鏉′欢') || line.includes('鍓嶆彁')) {
            currentTestCase.precondition = line.replace(/.*?[::]\s*/, '')
          } else if (line.includes('娴嬭瘯姝ラ') || line.includes('鎿嶄綔姝ラ') || line.includes('姝ラ')) {
            currentTestCase.steps = line.replace(/.*?[::]\s*/, '')
          } else if (line.includes('棰勬湡缁撴灉') || line.includes('Expected')) {
            currentTestCase.expected = line.replace(/.*?[::]\s*/, '')
          } else if (line.includes('优先级') || line.includes('Priority')) {
            currentTestCase.priority = line.replace(/.*?[::]\s*/, '')
          }
        }

        if (Object.keys(currentTestCase).length > 0) {
          testCases.push(currentTestCase)
        }
      }

      return testCases
    },

    getStatusText(status) {
      if (!status) return ''
      const statusKey = 'status' + status.charAt(0).toUpperCase() + status.slice(1)
      return this.$t('taskDetail.' + statusKey) || status
    },

    // 鏍煎紡鍖栧垪琛ㄤ腑鐨勬枃鏈?灏?br>杞崲涓烘崲琛?
    formatTextForList(text) {
      if (!text) return ''
      // 灏?br>銆?br/>銆?br />绛夋爣绛炬浛鎹负鎹㈣绗?
      return text.replace(/<br\s*\/?>/gi, '\n')
    },

    // 鏍煎紡鍖栨枃鏈?鍘婚櫎markdown鏍囪骞朵繚鐣欐牸寮?
    formatMarkdown(text) {
      if (!text) return ''

      // 鍏堝鐞嗘崲琛岀,杞负<br>鍗犱綅(鍦ㄨ浆涔変箣鍓?
      let formatted = text.replace(/\n/g, '<br>')

      // 鍘婚櫎markdown鍔犵矖鏍囪 **text**,淇濈暀绾枃鏈?
      formatted = formatted.replace(/\*\*([^*]+)\*\*/g, '$1')

      // 杞箟鍓╀綑鐨凥TML鏍囩,闃叉XSS(浣嗕繚鐣欏垰鐢熸垚鐨?br>)
      // 鍏堜繚鎶?br>鏍囩
      formatted = formatted.replace(/<br\s*\/>/gi, '___BR___')
      formatted = formatted.replace(/&/g, '&amp;')
                         .replace(/</g, '&lt;')
                         .replace(/>/g, '&gt;')
      // 鎭㈠<br>鏍囩
      formatted = formatted.replace(/___BR___/g, '<br>')

      return formatted
    },

    // 涓?AI 婢勬竻姘旀场涓撶敤鐨勭粨鏋勫寲娓叉煋:淇濈暀鍔犵矖/鏍囬/鍒楄〃/娈佃惤,XSS 瀹夊叏
    formatClarificationMarkdown(text) {
      if (!text) return ''

      // 1. HTML 杞箟(闃?XSS)
      const escape = (s) => s.replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;')

      let raw = text.trim()

      // 2. 鎻愬彇骞朵繚鎶?[CLARIFICATION_DONE] 鏍囪(鍚庣画鏁翠綋鏇挎崲涓洪珮浜窘绔?
      const DONE_TAG = '[CLARIFICATION_DONE]'
      const hasDoneTag = raw.includes(DONE_TAG)
      raw = raw.split(DONE_TAG).join('')

      // 3. 鎸夌┖琛屽垎娈?
      const blocks = raw.split(/\n\s*\n+/).map(b => b.trim()).filter(Boolean)

      const renderBlock = (block) => {
        const lines = block.split(/\n/).map(l => l.trim()).filter(Boolean)
        if (lines.length === 0) return ''

        // 鍒楄〃璇嗗埆:1. 2. 3. 鎴?- * + 寮€澶?
        const isOrdered = lines.every(l => /^\d+[\.、]\s*/.test(l))
        const isUnordered = lines.every(l => /^[-*+]\s+/.test(l))

        const inlineFormat = (s) => {
          let e = escape(s)
          // **bold** 鈫?<strong>
          e = e.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
          // *italic* (闈炶椽濠?閬垮厤鍚?**)
          e = e.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, '$1<em>$2</em>')
          // `code`
          e = e.replace(/`([^`]+)`/g, '<code>$1</code>')
          return e
        }

        if (isOrdered) {
          const items = lines.map(l => {
            const text = l.replace(/^\d+[\.、]\s*/, '')
            return `<li>${inlineFormat(text)}</li>`
          }).join('')
          return `<ol class="clari-ol">${items}</ol>`
        }
        if (isUnordered) {
          const items = lines.map(l => {
            const text = l.replace(/^[-*+]\s+/, '')
            return `<li>${inlineFormat(text)}</li>`
          }).join('')
          return `<ul class="clari-ul">${items}</ul>`
        }

        // 鏍囬璇嗗埆:鏁存鏄?### / ## / # 寮€澶?
        if (lines.length === 1) {
          const h = lines[0].match(/^(#{1,6})\s+(.+)$/)
          if (h) {
            const level = Math.min(h[1].length + 2, 6) // h3 璧锋
            return `<h${level} class="clari-h">${inlineFormat(h[2])}</h${level}>`
          }
          // 鍗曡涓旀暣琛?**鍔犵矖** 瑙嗕负灏忔爣棰?
          const bold = lines[0].match(/^\*\*(.+)\*\*$/)
          if (bold) {
            return `<h4 class="clari-h">${inlineFormat(bold[1])}</h4>`
          }
        }

        // 澶氳娈佃惤 鈥?鐢?<br> 杩炴帴杞崲琛?
        const para = lines.map(l => {
          // 琛屽唴鍙兘涔熸槸 ### 寮€澶?
          const h = l.match(/^(#{1,6})\s+(.+)$/)
          if (h) {
            const level = Math.min(h[1].length + 2, 6)
            return `</p><h${level} class="clari-h">${inlineFormat(h[2])}</h${level}><p>`
          }
          return inlineFormat(l)
        }).join('<br>')
        return `<p>${para}</p>`.replace(/<p><\/p>/g, '')
      }

      let html = blocks.map(renderBlock).join('')

      if (hasDoneTag) {
        html += '<div class="clari-done-badge"><span class="clari-done-dot"></span>婢勬竻瀹屾垚,鍙偣鍑讳笅鏂广€屽畬鎴愭緞娓?寮€濮嬬敓鎴愩€嶆寜閽?/div>'
      }

      return html
    },

    toggleSelectAll() {
      if (this.isAllSelected) {
        this.selectedCases = []
      } else {
        this.selectedCases = [...this.filteredTestCases]
      }
    },

    updateSelectAll() {
      // 杩欎釜鏂规硶浼氬湪鍗曚釜checkbox鍙樺寲鏃惰Е鍙?鐢ㄤ簬鏇存柊鍏ㄩ€夌姸鎬?
      // Vue鐨剉-model浼氳嚜鍔ㄥ鐞唖electedCases鏁扮粍鐨勬洿鏂?
    },

    async batchAdopt() {
      if (this.selectedCases.length === 0) {
        ElMessage.warning(this.$t('taskDetail.pleaseSelectFirst', { action: this.$t('taskDetail.adopt') }))
        return
      }

      try {
        await ElMessageBox.confirm(
          this.$t('taskDetail.confirmAdopt', { count: this.selectedCases.length }),
          this.$t('taskDetail.confirmAdoptTitle'),
          {
            confirmButtonText: this.$t('taskDetail.btnConfirm'),
            cancelButtonText: this.$t('taskDetail.btnCancelOperation'),
            type: 'success'
          }
        )
      } catch {
        return
      }

      try {
        const casesData = this.selectedCases.map((testCase, index) => ({
          title: testCase.scenario || `Test Case ${index + 1}`,
          description: testCase.scenario || '',
          preconditions: testCase.precondition || '',
          steps: testCase.steps || '',
          expected_result: testCase.expected || '',
          priority: this.mapPriority(testCase.priority),
          test_type: 'functional',
          status: 'draft'
        }))

        await api.post(`/requirement-analysis/testcase-generation/${this.taskId}/batch-adopt-selected/`, {
          test_cases: casesData
        })

        ElMessage.success(this.$t('taskDetail.adoptSuccess', { count: this.selectedCases.length }))
        this.selectedCases = []

        // Keep adopted cases in the list for multiple adoptions
        // this.testCases = this.testCases.filter(tc => !this.selectedCases.includes(tc))

      } catch (error) {
        console.error('Batch adopt failed:', error)
        ElMessage.error(this.$t('taskDetail.batchAdoptFailed') + ': ' + (error.response?.data?.message || error.message))
      }
    },

    async batchDiscard() {
      if (this.selectedCases.length === 0) {
        ElMessage.warning(this.$t('taskDetail.pleaseSelectFirst', { action: this.$t('taskDetail.discard') }))
        return
      }

      try {
        await ElMessageBox.confirm(
          this.$t('taskDetail.confirmDiscard', { count: this.selectedCases.length }),
          this.$t('taskDetail.confirmDiscardTitle'),
          {
            confirmButtonText: this.$t('taskDetail.btnConfirm'),
            cancelButtonText: this.$t('taskDetail.btnCancelOperation'),
            type: 'warning',
            confirmButtonClass: 'el-button--danger'
          }
        )
      } catch {
        return
      }

      try {
        // 鑾峰彇閫変腑鐢ㄤ緥鐨勫叏灞€绱㈠紩(涓嶆槸鍒嗛〉绱㈠紩)
        const caseIndices = this.selectedCases.map(selectedCase => {
          // 鍦ㄥ畬鏁村垪琛ㄤ腑鏌ユ壘绱㈠紩
          const globalIndex = this.testCases.findIndex(tc =>
            tc.scenario === selectedCase.scenario &&
            tc.steps === selectedCase.steps &&
            tc.expected === selectedCase.expected
          )
          return globalIndex
        }).filter(index => index !== -1) // 杩囨护鎺夋湭鎵惧埌鐨?-1)

        const response = await api.post(`/requirement-analysis/testcase-generation/${this.taskId}/discard-selected-cases/`, {
          case_indices: caseIndices
        })

        if (response.data.task_deleted) {
          ElMessage.success(this.$t('taskDetail.allDiscardedSuccess'))
          // 杩斿洖鍒癆I鐢熸垚鐢ㄤ緥璁板綍鍒楄〃
          this.$router.push('/generated-testcases')
        } else {
          ElMessage.success(this.$t('taskDetail.discardSuccess', { count: response.data.discarded_count }))

          // 閲嶆柊瑙ｆ瀽鏇存柊鍚庣殑娴嬭瘯鐢ㄤ緥
          if (response.data.updated_test_cases) {
            this.testCases = this.parseTestCases(response.data.updated_test_cases)
            this.selectedCases = []
            this.currentPage = 1 // 閲嶇疆鍒扮涓€椤?
          }
        }

      } catch (error) {
        console.error('Batch discard failed:', error)
        ElMessage.error(this.$t('taskDetail.batchDiscardFailed') + ': ' + (error.response?.data?.error || error.message))
      }
    },

    viewCaseDetail(testCase, index) {
      this.selectedCase = testCase
      this.selectedCaseIndex = index
      this.showCaseDetail = true
    },

    closeCaseDetail() {
      this.showCaseDetail = false
      this.selectedCase = {}
      this.isEditing = false
      this.editForm = {
        caseId: '',
        scenario: '',
        precondition: '',
        steps: '',
        expected: '',
        priority: 'P2'
      }
    },

    // 寮€濮嬬紪杈?
    startEdit() {
      this.isEditing = true

      this.editForm = {
        caseId: this.selectedCase.caseId || '',
        scenario: this.selectedCase.scenario || '',
        // 灏?br>杞崲涓烘崲琛岀浠ヤ究缂栬緫
        precondition: this.convertBrToNewline(this.selectedCase.precondition || ''),
        steps: this.convertBrToNewline(this.selectedCase.steps || ''),
        expected: this.convertBrToNewline(this.selectedCase.expected || ''),
        // 鐩存帴浣跨敤鍘熷浼樺厛绾у€?涓嶈浆鎹?
        priority: this.selectedCase.priority || 'P2'
      }
    },

    // 鍙栨秷缂栬緫
    cancelEdit() {
      this.isEditing = false
      this.editForm = {
        caseId: '',
        scenario: '',
        precondition: '',
        steps: '',
        expected: '',
        priority: 'P2'
      }
    },

    // 淇濆瓨缂栬緫
    async saveEdit() {
      // 绠€鍗曢獙璇?
      if (!this.editForm.scenario?.trim()) {
        ElMessage.warning(this.$t('taskDetail.enterScenario'))
        return
      }

      this.isSaving = true

      try {
        // 灏嗘崲琛岀杞崲鍥?br>
        const updatedCase = {
          ...this.selectedCase,
          scenario: this.editForm.scenario,
          precondition: this.convertNewlineToBr(this.editForm.precondition),
          steps: this.convertNewlineToBr(this.editForm.steps),
          expected: this.convertNewlineToBr(this.editForm.expected),
          priority: this.editForm.priority
        }

        // 鏇存柊鏈湴鏁扮粍涓殑鏁版嵁
        const index = this.testCases.findIndex(tc => tc === this.selectedCase)
        if (index !== -1) {
          this.testCases[index] = updatedCase
          this.selectedCase = updatedCase
        }

        // 閲嶆柊鐢熸垚琛ㄦ牸鏍煎紡鐨勬祴璇曠敤渚嬪瓧绗︿覆
        const updatedTestCases = this.generateTestCasesString()

        // 璋冪敤鍚庣API淇濆瓨(浣跨敤鑷畾涔塧ction鎺ュ彛)
        await api.post(`/requirement-analysis/testcase-generation/${this.taskId}/update-test-cases/`, {
          final_test_cases: updatedTestCases
        })

        // 鏇存柊鍐呭瓨涓殑task鏁版嵁
        this.task.final_test_cases = updatedTestCases

        ElMessage.success(this.$t('taskDetail.updateSuccess'))
        this.isEditing = false
      } catch (error) {
        console.error('Update failed:', error)
        ElMessage.error(this.$t('taskDetail.updateFailed') + ': ' + (error.response?.data?.error || error.message))
      } finally {
        this.isSaving = false
      }
    },

    // 灏唗estCases鏁扮粍閲嶆柊鐢熸垚涓鸿〃鏍兼牸寮忕殑瀛楃涓?
    generateTestCasesString() {
      if (this.testCases.length === 0) return ''

      // 琛ㄥご
      const headers = [
        this.$t('taskDetail.tableCaseId'),
        this.$t('taskDetail.tableScenario'),
        this.$t('taskDetail.tablePrecondition'),
        this.$t('taskDetail.tableSteps'),
        this.$t('taskDetail.tableExpected'),
        this.$t('taskDetail.tablePriority')
      ]
      let result = headers.join(' | ') + '\n'
      result += '|'.repeat(headers.length) + '\n'

      // 鏁版嵁琛?
      this.testCases.forEach((testCase, index) => {
        const row = [
          testCase.caseId || `TC${String(index + 1).padStart(3, '0')}`,
          testCase.scenario || '',
          testCase.precondition || '',
          testCase.steps || '',
          testCase.expected || '',
          testCase.priority || 'P2'
        ]
        result += row.join(' | ') + '\n'
      })

      return result
    },

    // 灏咹TML鐨?br>鏍囩杞崲涓烘崲琛岀
    convertBrToNewline(text) {
      if (!text) return ''
      return text.replace(/<br\s*\/?>/gi, '\n')
    },

    // 灏嗘崲琛岀杞崲涓篐TML鐨?br>鏍囩
    convertNewlineToBr(text) {
      if (!text) return ''
      return text.replace(/\n/g, '<br>')
    },

    async adoptSingleCase(testCase, index) {
      try {
        await ElMessageBox.confirm(
          this.$t('taskDetail.confirmAdoptSingle', { scenario: testCase.scenario }),
          this.$t('taskDetail.confirmAdoptTitle'),
          {
            confirmButtonText: this.$t('taskDetail.btnConfirm'),
            cancelButtonText: this.$t('taskDetail.btnCancelOperation'),
            type: 'success'
          }
        )
      } catch {
        return
      }

      try {
        const caseData = {
          title: testCase.scenario || `娴嬭瘯鐢ㄤ緥${index + 1}`,
          description: testCase.scenario || '',
          preconditions: testCase.precondition || '',
          steps: testCase.steps || '',
          expected_result: testCase.expected || '',
          priority: this.mapPriority(testCase.priority),
          test_type: 'functional',
          status: 'draft'
        }

        await api.post('/testcases/', caseData)
        ElMessage.success(this.$t('taskDetail.adoptSuccess', { count: 1 }))

        // 涓嶅啀绉婚櫎宸查噰绾崇殑鐢ㄤ緥,淇濈暀鍦ㄥ垪琛ㄤ腑渚涘娆￠噰绾?
        // this.testCases.splice(this.testCases.indexOf(testCase), 1)

      } catch (error) {
        console.error('Adopt case failed:', error)
        ElMessage.error(this.$t('taskDetail.adoptFailed') + ': ' + (error.response?.data?.message || error.message))
      }
    },

    async discardSingleCase(testCase, index) {
      try {
        await ElMessageBox.confirm(
          this.$t('taskDetail.confirmDiscardSingle', { scenario: testCase.scenario }),
          this.$t('taskDetail.confirmDiscardTitle'),
          {
            confirmButtonText: this.$t('taskDetail.btnConfirm'),
            cancelButtonText: this.$t('taskDetail.btnCancelOperation'),
            type: 'warning',
            confirmButtonClass: 'el-button--danger'
          }
        )
      } catch {
        return
      }

      try {
        // 璁＄畻鍏ㄥ眬绱㈠紩(褰撳墠椤甸潰璧峰浣嶇疆 + 褰撳墠绱㈠紩)
        const globalIndex = (this.currentPage - 1) * this.pageSize + index

        // 璋冪敤鍚庣API寮冪敤鍗曚釜娴嬭瘯鐢ㄤ緥
        const response = await api.post(`/requirement-analysis/testcase-generation/${this.taskId}/discard-single-case/`, {
          case_index: globalIndex
        })

        if (response.data.task_deleted) {
          ElMessage.success(this.$t('taskDetail.allDiscardedSuccess'))
          // 杩斿洖鍒癆I鐢熸垚鐢ㄤ緥璁板綍鍒楄〃
          this.$router.push('/generated-testcases')
        } else {
          ElMessage.success(this.$t('taskDetail.caseDiscardedSuccess'))

          // 閲嶆柊瑙ｆ瀽鏇存柊鍚庣殑娴嬭瘯鐢ㄤ緥
          if (response.data.updated_test_cases) {
            this.testCases = this.parseTestCases(response.data.updated_test_cases)

            // 濡傛灉褰撳墠椤垫病鏈夋暟鎹簡,鍥炲埌涓婁竴椤?
            if (this.currentPage > 1 && this.paginatedTestCases.length === 0) {
              this.currentPage--
            }
          }
        }

      } catch (error) {
        console.error('Discard case failed:', error)
        ElMessage.error(this.$t('taskDetail.discardFailed') + ': ' + (error.response?.data?.error || error.message))
      }
    },

    mapPriority(priority) {
      const priorityMap = {
        '最高': 'critical',
        '高': 'high',
        '中': 'medium',
        '低': 'low',
        'P0': 'critical',
        'P1': 'high',
        'P2': 'medium',
        'P3': 'low'
      }
      return priorityMap[priority] || 'medium'
    },

    // 灏嗚嫳鏂囦紭鍏堢骇杞崲涓烘湰鍦板寲鏄剧ず
    priorityToChinese(priority) {
      const priorityMap = {
        'critical': this.$t('generatedTestCases.priorityCritical'),
        'high': this.$t('generatedTestCases.priorityHigh'),
        'medium': this.$t('generatedTestCases.priorityMedium'),
        'low': this.$t('generatedTestCases.priorityLow')
      }
      return priorityMap[priority] || this.$t('generatedTestCases.priorityMedium')
    },

    // 瀵煎嚭鍒癊xcel
    exportToExcel() {
      if (this.testCases.length === 0) {
        ElMessage.warning(this.$t('taskDetail.noCasesToExport'))
        return
      }

      this.isExporting = true

      try {
        // 鍒涘缓宸ヤ綔绨?
        const workbook = XLSX.utils.book_new()

        // 鍑嗗鏁版嵁
        const worksheetData = []

        // 娣诲姞琛ㄥご
        worksheetData.push([
          this.$t('taskDetail.tableCaseId'),
          this.$t('taskDetail.tableScenario'),
          this.$t('taskDetail.tablePrecondition'),
          this.$t('taskDetail.tableSteps'),
          this.$t('taskDetail.tableExpected'),
          this.$t('taskDetail.tablePriority')
        ])

        // 娣诲姞鏁版嵁琛?
        this.testCases.forEach((testCase, index) => {
          worksheetData.push([
            testCase.caseId || `TC${String(index + 1).padStart(3, '0')}`,
            testCase.scenario || '',
            this.formatTextForList(testCase.precondition || ''),
            this.formatTextForList(testCase.steps || ''),
            this.formatTextForList(testCase.expected || ''),
            testCase.priority || 'P2'
          ])
        })

        // 鍒涘缓宸ヤ綔琛?
        const worksheet = XLSX.utils.aoa_to_sheet(worksheetData)

        // 璁剧疆鍒楀
        const colWidths = [
          { wch: 15 }, // 娴嬭瘯鐢ㄤ緥缂栧彿
          { wch: 30 }, // 娴嬭瘯鍦烘櫙
          { wch: 25 }, // 鍓嶇疆鏉′欢
          { wch: 50 }, // 鎿嶄綔姝ラ(澧炲姞瀹藉害)
          { wch: 40 }, // 棰勬湡缁撴灉(澧炲姞瀹藉害)
          { wch: 10 }  // 浼樺厛绾?
        ]
        worksheet['!cols'] = colWidths

        // 涓烘墍鏈夊崟鍏冩牸娣诲姞鑷姩鎹㈣鏍峰紡
        const range = XLSX.utils.decode_range(worksheet['!ref'])
        for (let row = range.s.r; row <= range.e.r; row++) {
          for (let col = range.s.c; col <= range.e.c; col++) {
            const cellAddress = XLSX.utils.encode_cell({ r: row, c: col })
            if (!worksheet[cellAddress]) continue
            worksheet[cellAddress].s = {
              alignment: {
                wrapText: true,
                vertical: 'top'
              }
            }
          }
        }

        // 灏嗗伐浣滆〃娣诲姞鍒板伐浣滅翱
        XLSX.utils.book_append_sheet(workbook, worksheet, this.$t('taskDetail.excelSheetName'))

        // 鐢熸垚鏂囦欢鍚?
        const dateStr = new Date().toISOString().slice(0, 10)
        const fileName = this.$t('taskDetail.excelFileName', { taskId: this.taskId, date: dateStr })

        // 瀵煎嚭鏂囦欢
        XLSX.writeFile(workbook, fileName)

        ElMessage.success(this.$t('taskDetail.exportExcelSuccess'))
      } catch (error) {
        console.error('Export Excel failed:', error)
        ElMessage.error(this.$t('taskDetail.exportFailed') + ': ' + (error.message || ''))
      } finally {
        this.isExporting = false
      }
    },

    // 鍒囨崲瀵煎嚭鑿滃崟鏄剧ず
    toggleExportMenu() {
      this.showExportMenu = !this.showExportMenu
    },

    // 澶勭悊瀵煎嚭鎿嶄綔
    handleExport(type) {
      this.showExportMenu = false
      switch (type) {
        case 'excel':
          this.exportToExcel()
          break
        case 'markdown':
          this.exportToMarkdown()
          break
        case 'opml':
          this.exportToOPML()
          break
      }
    },

    // 瀵煎嚭涓?Markdown 鏍煎紡
    exportToMarkdown() {
      if (this.testCases.length === 0) {
        ElMessage.warning(this.$t('taskDetail.noCasesToExport'))
        return
      }

      this.isExporting = true

      try {
        // 鏋勫缓 Markdown 鍐呭
        let md = '# 娴嬭瘯鐢ㄤ緥\n\n'
        md += `> 浠诲姟ID: ${this.taskId}\n`
        md += `> 鐢熸垚鏃堕棿: ${new Date().toLocaleString()}\n`
        md += `> 鐢ㄤ緥鎬绘暟: ${this.testCases.length}\n\n`

        // 闇€姹傛枃妗ｇ殑鍚嶇О锛堜粠浠诲姟涓幏鍙栵級
        const requirementName = this.task?.title || this.task?.name || this.task?.requirement_name || '测试需求'
        md += `## ${requirementName}\n\n`

        // 鎸夋ā鍧楀垎缁?
        const modules = {}
        this.testCases.forEach((testCase, index) => {
          const module = testCase.module || '未分类'
          if (!modules[module]) {
            modules[module] = []
          }
          modules[module].push({
            ...testCase,
            index
          })
        })

        // 閬嶅巻姣忎釜妯″潡
        Object.keys(modules).sort().forEach((moduleName, moduleIndex) => {
          const moduleCases = modules[moduleName]
          md += `### ${moduleName}\n\n`

          moduleCases.forEach((testCase, caseIndexInModule) => {
            // 楠岃瘉鐐瑰氨鏄祴璇曞満鏅?
            const verificationPoint = testCase.scenario || '未命名'
            md += `- ${verificationPoint}\n`

            // 鎿嶄綔姝ラ浣滀负楠岃瘉鐐圭殑瀛愯妭鐐?
            const steps = this.formatTextForList(testCase.steps || '')
            if (steps && steps.trim()) {
              const stepText = steps.split('\n').filter(line => line.trim()).join(' ').trim()
              md += `  - 鎿嶄綔姝ラ锛?{stepText}\n`

              // 棰勬湡缁撴灉浣滀负鎿嶄綔姝ラ鐨勫瓙鑺傜偣锛堢缉杩涙洿娣变竴灞傦級
              const expected = this.formatTextForList(testCase.expected || '')
              if (expected && expected.trim()) {
                const expectedText = expected.split('\n').filter(line => line.trim()).join(' ').trim()
                md += `    - 棰勬湡缁撴灉锛?{expectedText}\n`
              }
            }

            md += '\n'
          })
        })

        // 鐢熸垚鏂囦欢鍚嶅苟涓嬭浇
        const dateStr = new Date().toISOString().slice(0, 10)
        const fileName = `娴嬭瘯鐢ㄤ緥_${this.taskId}_${dateStr}.md`
        this.downloadFile(md, fileName, 'text/markdown;charset=utf-8')

        ElMessage.success(this.$t('taskDetail.exportMarkdownSuccess'))
      } catch (error) {
        console.error('Export Markdown failed:', error)
        ElMessage.error(this.$t('taskDetail.exportFailed') + ': ' + (error.message || ''))
      } finally {
        this.isExporting = false
      }
    },

    // 瀵煎嚭涓?OPML 鏍煎紡
    exportToOPML() {
      if (this.testCases.length === 0) {
        ElMessage.warning(this.$t('taskDetail.noCasesToExport'))
        return
      }

      this.isExporting = true

      try {
        // 闇€姹傛枃妗ｇ殑鍚嶇О
        const requirementName = this.task?.title || this.task?.name || this.task?.requirement_name || '测试需求'

        // 鎸夋ā鍧楀垎缁?
        const modules = {}
        this.testCases.forEach((testCase, index) => {
          const module = testCase.module || '未分类'
          if (!modules[module]) {
            modules[module] = []
          }
          modules[module].push({
            ...testCase,
            index
          })
        })

        // 鏋勫缓 OPML 鍐呭
        let opml = '<?xml version="1.0" encoding="UTF-8"?>\n'
        opml += '<opml version="2.0">\n'
        opml += '  <head>\n'
        opml += '    <title>' + this.escapeXml(requirementName) + '</title>\n'
        opml += '    <dateCreated>' + new Date().toISOString() + '</dateCreated>\n'
        opml += '  </head>\n'
        opml += '  <body>\n'

        // 椤跺眰锛氶渶姹傚悕绉?
        opml += '    <outline text="' + this.escapeXml(requirementName) + '">\n'

        // 娣诲姞姣忎釜妯″潡浣滀负瀛愯妭鐐?
        Object.keys(modules).sort().forEach(moduleName => {
          opml += '      <outline text="' + this.escapeXml(moduleName) + '">\n'

          modules[moduleName].forEach(testCase => {
            // 楠岃瘉鐐癸紙娴嬭瘯鍦烘櫙锛変綔涓烘ā鍧楃殑瀛愯妭鐐?
            const verificationPoint = this.escapeXml(testCase.scenario || '未命名')
            opml += '        <outline text="' + verificationPoint + '">\n'

            // 鎿嶄綔姝ラ浣滀负楠岃瘉鐐圭殑瀛愯妭鐐?
            const steps = this.formatTextForList(testCase.steps || '')
            if (steps && steps.trim()) {
              const stepText = steps.split('\n').filter(line => line.trim()).join(' ').trim()
              opml += '          <outline text="操作步骤：' + this.escapeXml(stepText) + '">\n'

              // 棰勬湡缁撴灉浣滀负鎿嶄綔姝ラ鐨勫瓙鑺傜偣锛堝祵濂楀湪鎿嶄綔姝ラ涓嬶級
              const expected = this.formatTextForList(testCase.expected || '')
              if (expected && expected.trim()) {
                const expectedText = expected.split('\n').filter(line => line.trim()).join(' ').trim()
                opml += '            <outline text="预期结果：' + this.escapeXml(expectedText) + '" />\n'
              }

              opml += '          </outline>\n'
            }

            opml += '        </outline>\n'
          })

          opml += '      </outline>\n'
        })

        opml += '    </outline>\n'
        opml += '  </body>\n'
        opml += '</opml>'

        // 鐢熸垚鏂囦欢鍚嶅苟涓嬭浇
        const dateStr = new Date().toISOString().slice(0, 10)
        const fileName = `娴嬭瘯鐢ㄤ緥_${this.taskId}_${dateStr}.opml`
        this.downloadFile(opml, fileName, 'text/xml;charset=utf-8')

        ElMessage.success(this.$t('taskDetail.exportOPMLSuccess'))
      } catch (error) {
        console.error('Export OPML failed:', error)
        ElMessage.error(this.$t('taskDetail.exportFailed') + ': ' + (error.message || ''))
      } finally {
        this.isExporting = false
      }
    },

    // 涓嬭浇鏂囦欢宸ュ叿鏂规硶
    downloadFile(content, fileName, contentType) {
      const blob = new Blob([content], { type: contentType })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = fileName
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      URL.revokeObjectURL(url)
    },

    // 杞箟 Markdown 鐗规畩瀛楃
    escapeMarkdown(text) {
      return text
        .replace(/\\/g, '\\\\')
        .replace(/\|/g, '\\|')
        .replace(/\n/g, '\\n')
    },

    // 杞箟 XML 鐗规畩瀛楃
    escapeXml(text) {
      return text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&apos;')
    }
  }
}
</script>

<style scoped>
.task-detail {
  padding: 20px;
  max-width: 1400px;
  margin: 0 auto;
}

.task-intelligence-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(320px, 0.9fr);
  gap: 20px;
  margin-bottom: 20px;
}

.intelligence-card,
.decision-log-card {
  background:
    radial-gradient(circle at top right, rgba(15, 118, 110, 0.10), transparent 28%),
    linear-gradient(180deg, #ffffff 0%, #f7fafc 100%);
  border: 1px solid #dbe7ee;
  border-radius: 18px;
  box-shadow: 0 12px 32px rgba(15, 23, 42, 0.06);
  padding: 22px;
}

.final-deliverable-block {
  display: flex;
  flex-direction: column;
  gap: 0;
}

.section-flash {
  animation: sectionFlashPulse 1.8s ease;
}

@keyframes sectionFlashPulse {
  0% {
    box-shadow: 0 0 0 0 rgba(15, 118, 110, 0.24);
    transform: translateY(0);
  }

  25% {
    box-shadow: 0 0 0 6px rgba(15, 118, 110, 0.14);
    transform: translateY(-2px);
  }

  100% {
    box-shadow: 0 0 0 0 rgba(15, 118, 110, 0);
    transform: translateY(0);
  }
}

.intelligence-card__header,
.decision-log-card__header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
  margin-bottom: 18px;
}

.intelligence-card__eyebrow {
  margin: 0 0 6px;
  font-size: 12px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: #0f766e;
  font-weight: 700;
}

.intelligence-card__header h3,
.decision-log-card__header h3 {
  margin: 0;
  font-size: 22px;
  color: #102a43;
}

.intelligence-card__desc {
  margin: 8px 0 0;
  color: #52606d;
  line-height: 1.6;
  font-size: 13px;
}

.delivery-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 88px;
  padding: 8px 12px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
}

.summary-metric-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.summary-metric {
  padding: 16px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid #e6eef5;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.summary-metric__label {
  font-size: 12px;
  color: #7b8794;
}

.summary-metric__value {
  font-size: 24px;
  color: #102a43;
  line-height: 1.1;
}

.summary-metric__hint {
  font-size: 12px;
  color: #52606d;
}

.signal-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 16px;
}

.signal-pill {
  flex: 1 1 160px;
  min-width: 0;
  border-radius: 14px;
  padding: 12px 14px;
  border: 1px solid transparent;
  display: flex;
  justify-content: space-between;
  gap: 8px;
  align-items: center;
}

.signal-pill__label {
  font-size: 12px;
  color: #486581;
}

.signal-pill__value {
  font-size: 14px;
  font-weight: 700;
  color: #102a43;
}

.deliverable-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.deliverable-item {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
  padding: 14px;
  border-radius: 14px;
  border: 1px solid #e6eef5;
  background: rgba(255, 255, 255, 0.92);
}

.deliverable-item.is-ready {
  border-color: rgba(15, 118, 110, 0.30);
  box-shadow: inset 0 0 0 1px rgba(15, 118, 110, 0.04);
}

.deliverable-item__meta strong {
  color: #102a43;
}

.deliverable-item__meta p {
  margin: 6px 0 0;
  font-size: 12px;
  color: #52606d;
  line-height: 1.5;
}

.deliverable-item__title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.deliverable-status {
  font-size: 11px;
  border-radius: 999px;
  padding: 4px 8px;
  font-weight: 700;
}

.deliverable-status.is-ready {
  background: #e6fffa;
  color: #0f766e;
}

.deliverable-status.is-waiting {
  background: #fff7ed;
  color: #c05621;
}

.deliverable-item__actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

.mini-action-btn {
  border: none;
  border-radius: 10px;
  padding: 9px 12px;
  background: #0f766e;
  color: #fff;
  cursor: pointer;
  font-weight: 600;
  transition: transform 0.2s ease, opacity 0.2s ease;
}

.mini-action-btn:hover:not(:disabled) {
  transform: translateY(-1px);
}

.mini-action-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.mini-action-btn--ghost {
  background: #e6fffa;
  color: #0f766e;
}

.decision-timeline {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.timeline-item {
  display: grid;
  grid-template-columns: 18px minmax(0, 1fr);
  gap: 14px;
  align-items: flex-start;
}

.timeline-item__dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  margin-top: 5px;
  box-shadow: 0 0 0 4px rgba(15, 118, 110, 0.08);
}

.timeline-item__content {
  padding-bottom: 14px;
  border-bottom: 1px dashed #d9e2ec;
}

.timeline-item:last-child .timeline-item__content {
  border-bottom: none;
  padding-bottom: 0;
}

.timeline-item__row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
  margin-bottom: 6px;
}

.timeline-item__row strong {
  color: #102a43;
}

.timeline-item__row span {
  font-size: 12px;
  color: #7b8794;
}

.timeline-item__content p {
  margin: 0;
  color: #52606d;
  line-height: 1.6;
  font-size: 13px;
}

.tone-good {
  background: #e6fffa;
  color: #0f766e;
}

.tone-warn {
  background: #fff7ed;
  color: #c05621;
}

.tone-risk {
  background: #fef2f2;
  color: #c53030;
}

.tone-neutral {
  background: #f4f6f8;
  color: #52606d;
}

.timeline-item__dot.tone-good {
  background: #0f766e;
}

.timeline-item__dot.tone-warn {
  background: #dd6b20;
}

.timeline-item__dot.tone-risk {
  background: #e53e3e;
}

.timeline-item__dot.tone-neutral {
  background: #7b8794;
}

/* ==================== 鐢熸垚涓繘搴﹂潰鏉?==================== */
.generation-progress-panel {
  background: linear-gradient(135deg, #f6f9ff 0%, #eef4ff 100%);
  border: 1px solid #d6e4ff;
  border-radius: 12px;
  padding: 24px 28px;
  margin-bottom: 20px;
  box-shadow: 0 4px 16px rgba(64, 128, 255, 0.08);
}

.gen-progress-header {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 18px;
}

.gen-progress-icon {
  flex-shrink: 0;
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: linear-gradient(135deg, #4080ff 0%, #6699ff 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  box-shadow: 0 4px 12px rgba(64, 128, 255, 0.3);
  animation: gen-icon-pulse 1.6s ease-in-out infinite;
}

@keyframes gen-icon-pulse {
  0%, 100% { transform: scale(1); box-shadow: 0 4px 12px rgba(64, 128, 255, 0.3); }
  50% { transform: scale(1.05); box-shadow: 0 6px 20px rgba(64, 128, 255, 0.5); }
}

.gen-progress-title-wrap {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.gen-progress-title {
  font-size: 16px;
  font-weight: 600;
  color: #1f3a5f;
}

.gen-progress-subtitle {
  font-size: 13px;
  color: #5a7090;
}

.gen-progress-percent {
  font-size: 22px;
  font-weight: 700;
  color: #4080ff;
  font-variant-numeric: tabular-nums;
  min-width: 60px;
  text-align: right;
}

.gen-progress-bar {
  margin-bottom: 20px;
}

.gen-progress-steps {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}

.gen-step {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 10px 8px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.6);
  border: 1px solid #e0e8f5;
  font-size: 12px;
  color: #8a9bb5;
  font-weight: 500;
  transition: all 0.3s ease;
  gap: 6px;
}

.gen-step .step-num {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: rgba(138, 155, 181, 0.15);
  font-size: 11px;
  font-weight: 700;
}

.gen-step.active .step-num {
  background: rgba(64, 128, 255, 0.15);
  color: #4080ff;
}

.gen-step.done .step-num {
  background: rgba(255, 255, 255, 0.3);
  color: #fff;
}

.gen-step.active {
  background: #fff;
  border-color: #4080ff;
  color: #4080ff;
  box-shadow: 0 2px 8px rgba(64, 128, 255, 0.15);
  font-weight: 600;
}

.gen-step.done {
  background: linear-gradient(135deg, #52c41a 0%, #73d13d 100%);
  border-color: #52c41a;
  color: #fff;
  box-shadow: 0 2px 8px rgba(82, 196, 26, 0.25);
}

.gen-stream-preview {
  margin-top: 18px;
  padding-top: 16px;
  border-top: 1px dashed #c8d6f0;
}

.gen-stream-header {
  font-size: 12px;
  color: #5a7090;
  font-weight: 600;
  margin-bottom: 8px;
  letter-spacing: 0.5px;
}

.gen-stream-body {
  background: rgba(255, 255, 255, 0.7);
  border: 1px solid #e0e8f5;
  border-radius: 6px;
  padding: 10px 12px;
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 12px;
  color: #4a5870;
  line-height: 1.6;
  max-height: 400px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-all;
}

.gen-stream-body :deep(table) {
  border-collapse: collapse;
  width: 100%;
  font-size: 12px;
}

.gen-stream-body :deep(th),
.gen-stream-body :deep(td) {
  border: 1px solid #e0e8f5;
  padding: 4px 8px;
  text-align: left;
}

.gen-stream-body :deep(th) {
  background: #f5f7fa;
  font-weight: 600;
}

@media (max-width: 1100px) {
  .task-intelligence-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 768px) {
  .summary-metric-grid {
    grid-template-columns: 1fr;
  }

  .deliverable-item {
    flex-direction: column;
    align-items: stretch;
  }

  .deliverable-item__actions {
    width: 100%;
  }

  .mini-action-btn {
    flex: 1;
  }

  .timeline-item__row {
    flex-direction: column;
    align-items: flex-start;
  }
}

/* 娴佸紡鍐呭棰勮鍖哄煙锛堟浛浠ｇ┖鐘舵€侊紝鏄剧ず鍘熷娴佸紡鏂囨湰锛?*/
/* ===== 4琛ㄦ牸鐎戝竷娴佹牱寮?===== */
.four-tables-waterfall {
  display: flex;
  flex-direction: column;
  gap: 20px;
  margin-top: 20px;
}

.waterfall-card {
  background: #fff;
  border: 1px solid #e8e8e8;
  border-radius: 10px;
  overflow: hidden;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04);
  animation: cardFadeIn 0.35s ease-out;
}

.waterfall-card-table4 {
  border-bottom: none;
  border-radius: 10px 10px 0 0;
  margin-bottom: -1px;
}

@keyframes cardFadeIn {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}

.waterfall-card-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 18px;
  background: linear-gradient(135deg, #f8faff 0%, #f0f5ff 100%);
  border-bottom: 1px solid #e8effa;
}

.waterfall-card-icon {
  font-size: 18px;
  flex-shrink: 0;
}

.waterfall-card-title {
  font-size: 15px;
  font-weight: 600;
  color: #1a1a2e;
  flex-grow: 1;
}

.waterfall-card-badge {
  font-size: 12px;
  padding: 3px 10px;
  border-radius: 20px;
  font-weight: 500;
  white-space: nowrap;
}

.badge-done {
  background: #e8fdf4;
  color: #00a86b;
}

.badge-active {
  background: #fff7e6;
  color: #d48806;
  animation: pulse 1.5s infinite;
}

.badge-waiting {
  background: #f0f0f0;
  color: #888;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.waterfall-card-body {
  padding: 16px 18px;
  font-size: 13.5px;
  line-height: 1.7;
  color: #333;
}

.waterfall-card-body.stream-body {
  max-height: 600px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: -apple-system, 'SF Mono', Consolas, monospace;
  font-size: 13px;
  line-height: 1.65;
}

.card-loading {
  text-align: center;
  color: #999;
  padding: 30px 18px !important;
}

.card-empty {
  text-align: center;
  color: #6b7280;
  padding: 30px 18px !important;
}

.loading-dots {
  display: inline-flex;
  gap: 4px;
  margin-right: 6px;
}

.loading-dots i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #bbb;
  animation: dotBounce 1.4s ease-in-out infinite;
}

.loading-dots i:nth-child(2) { animation-delay: 0.16s; }
.loading-dots i:nth-child(3) { animation-delay: 0.32s; }

@keyframes dotBounce {
  0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; }
  40% { transform: scale(1); opacity: 1; }
}

/* 鐎戝竷娴佸唴宓岃〃鏍?*/
.waterfall-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
}

.waterfall-table th,
.waterfall-table td {
  padding: 9px 10px;
  text-align: left;
  border-bottom: 1px solid #eee;
  white-space: normal;
  vertical-align: top;
}

.waterfall-table th {
  background: #fafbfc;
  font-weight: 600;
  color: #555;
  position: sticky;
  top: 0;
  z-index: 1;
}

.waterfall-table td .cell-steps {
  max-width: 250px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.waterfall-table tr:hover td {
  background: #f8fbff;
}

/* ===== 鍘熸湁娴佸紡棰勮鏍峰紡锛堜繚鐣欏吋瀹癸級 ===== */
.stream-content-preview {
  background: linear-gradient(135deg, #fafbff 0%, #f0f5ff 100%);
  border: 1px solid #d6e4ff;
  border-radius: 10px;
  padding: 20px;
  margin-top: 16px;
  animation: streamFadeIn 0.3s ease-out;
}

@keyframes streamFadeIn {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

.stream-preview-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 14px;
  padding-bottom: 10px;
  border-bottom: 1px solid #e8effa;
}

.stream-preview-header span:first-child {
  font-size: 14px;
  font-weight: 600;
  color: #2b5aed;
}

.stream-char-count {
  font-size: 12px;
  color: #8899aa;
  background: #f0f4fa;
  padding: 2px 10px;
  border-radius: 10px;
}

.stream-preview-body {
  font-size: 13.5px;
  line-height: 1.8;
  color: #334155;
  /* 涓嶉檺鍒堕珮搴︼紝璁╃€戝竷娴佽嚜鐒舵祦娣?*/
}

.stream-preview-body :deep(table) {
  border-collapse: collapse;
  width: 100%;
  margin: 10px 0;
}

.stream-preview-body :deep(th),
.stream-preview-body :deep(td) {
  border: 1px solid #d0dbe8;
  padding: 6px 10px;
  text-align: left;
  font-size: 12.5px;
}

.stream-preview-body :deep(th) {
  background: #e8f0fe;
  font-weight: 600;
  color: #374151;
}

.stream-preview-body :deep(tr:hover) {
  background: #f5f8ff;
}

/* 闇€姹傛弿杩版姌鍙犲崱鐗?*/
.requirement-description-card {
  margin-bottom: 20px;
  background: white;
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  overflow: hidden;
}

.collapse-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  font-weight: 500;
  position: relative;
  padding-left: 20px;
}

/* 闅愯棌宸︿晶鍙兘瀛樺湪鐨凟lement Plus榛樿绠ご */
.collapse-title::before {
  content: none;
}

.title-icon {
  font-size: 18px;
}

.title-text {
  color: #303133;
  font-weight: 600;
}

.title-hint {
  font-size: 13px;
  color: #909399;
  font-weight: normal;
}

.requirement-content {
  padding: 16px 0;
}

.requirement-text {
  background: #f5f7fa;
  border-radius: 6px;
  padding: 16px;
  line-height: 1.8;
  color: #606266;
  white-space: pre-wrap;
  word-wrap: break-word;
  max-height: 400px;
  overflow-y: auto;
  font-family: 'Courier New', Courier, monospace;
  font-size: 14px;
  border-left: 4px solid #409eff;
}

.requirement-images {
  margin-top: 16px;
}

.requirement-images__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
  color: #303133;
}

.requirement-images__header span {
  font-size: 12px;
  color: #909399;
}

.requirement-images__grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
}

.requirement-image-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px;
  border: 1px solid #e4e7ed;
  border-radius: 10px;
  background: #fff;
  text-decoration: none;
  transition: border-color 0.2s ease, box-shadow 0.2s ease, transform 0.2s ease;
}

.requirement-image-card:hover {
  border-color: #409eff;
  box-shadow: 0 8px 24px rgba(64, 158, 255, 0.12);
  transform: translateY(-1px);
}

.requirement-image-card__img {
  width: 100%;
  height: 140px;
  object-fit: cover;
  border-radius: 8px;
  background: #f5f7fa;
}

.requirement-image-card__label {
  font-size: 12px;
  color: #606266;
  text-align: center;
}

.requirement-actions {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
}

/* 鑷畾涔夋姌鍙犻潰鏉挎牱寮?*/
.requirement-description-card :deep(.el-collapse) {
  border: none;
}

.requirement-description-card :deep(.el-collapse-item__header) {
  background: #fafafa;
  border-bottom: 1px solid #e4e7ed;
  padding: 16px 20px;
  font-size: 15px;
}

/* 闅愯棌Element Plus榛樿鐨勭澶村浘鏍?*/
.requirement-description-card :deep(.el-collapse-item__header .el-icon) {
  display: none !important;
}

.requirement-description-card :deep(.el-collapse-item__arrow) {
  display: none !important;
}

.requirement-description-card :deep(.el-collapse-item__wrap) {
  border-bottom: none;
}

.requirement-description-card :deep(.el-collapse-item__content) {
  padding: 0 20px 16px;
}

.page-header {
  margin-bottom: 20px;
  padding-bottom: 15px;
  border-bottom: 1px solid #eee;
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}

.header-left {
  flex: 1;
}

.page-header h2 {
  color: #2c3e50;
  margin: 0 0 10px 0;
}

.task-info {
  display: flex;
  gap: 20px;
  align-items: center;
}

.task-id {
  color: #666;
  font-family: monospace;
}

.task-status {
  padding: 4px 12px;
  border-radius: 4px;
  font-size: 0.9rem;
  font-weight: bold;
}

.task-status.completed {
  background: #e8f5e8;
  color: #388e3c;
}

.header-actions {
  display: flex;
  gap: 10px;
}

.export-btn {
  background: #27ae60;
  color: white;
  border: none;
  padding: 10px 20px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 0.9rem;
  transition: background 0.3s ease;
  white-space: nowrap;
  display: flex;
  align-items: center;
  gap: 8px;
}

.export-btn:hover:not(:disabled) {
  background: #229954;
}

.export-btn:disabled {
  background: #bdc3c7;
  cursor: not-allowed;
}

.export-arrow {
  font-size: 0.7rem;
  margin-left: 4px;
}

.export-dropdown {
  position: relative;
}

.export-menu {
  position: absolute;
  top: 100%;
  right: 0;
  margin-top: 4px;
  background: white;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.15);
  z-index: 1000;
  min-width: 150px;
  overflow: hidden;
}

.export-menu button {
  display: block;
  width: 100%;
  padding: 10px 16px;
  border: none;
  background: none;
  text-align: left;
  cursor: pointer;
  font-size: 0.9rem;
  color: #303133;
  transition: background 0.2s;
}

.export-menu button:hover {
  background: #f5f7fa;
  color: #27ae60;
}

.export-menu button:not(:last-child) {
  border-bottom: 1px solid #ebeef5;
}

.batch-actions {
  display: grid !important;
  grid-template-columns: 1fr auto !important;
  gap: 15px;
  align-items: center;
  background: white;
  border-radius: 8px;
  padding: 20px;
  margin-bottom: 20px;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
}

.selection-info {
  display: flex;
  align-items: center;
  gap: 15px;
}

.select-all {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}

.selected-count {
  color: #3498db;
  font-weight: bold;
}

.batch-buttons {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-left: auto !important;
}

.module-filter-select {
  padding: 8px 12px;
  border: 1px solid #dcdfe6;
  border-radius: 6px;
  font-size: 0.9rem;
  color: #606266;
  background: #fff;
  cursor: pointer;
  min-width: 180px;
  transition: border-color 0.2s;
}

.module-filter-select:focus {
  border-color: #409eff;
  outline: none;
}

.module-tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 0.78rem;
  background: #ecf5ff;
  color: #409eff;
  white-space: nowrap;
}

.batch-adopt-btn, .batch-discard-btn {
  padding: 8px 16px;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-size: 0.9rem;
  transition: all 0.2s ease;
}

.batch-adopt-btn {
  background: #27ae60;
  color: white;
}

.batch-adopt-btn:hover:not(:disabled) {
  background: #229954;
}

.batch-discard-btn {
  background: #e74c3c;
  color: white;
}

.batch-discard-btn:hover:not(:disabled) {
  background: #c0392b;
}

.batch-adopt-btn:disabled, .batch-discard-btn:disabled {
  background: #bdc3c7;
  cursor: not-allowed;
}

.testcases-table {
  background: white;
  border-radius: 8px;
  /* 绉婚櫎 overflow: hidden锛屽惁鍒欒〃澶?sticky 涓嶇敓鏁?*/
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
}

.table-header {
  display: grid;
  grid-template-columns: 60px 160px 1fr 1fr 1fr 1fr 80px 100px 150px;
  background: #f8f9fa;
  font-weight: bold;
  color: #2c3e50;
  border-radius: 8px 8px 0 0;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
}

.table-body .table-row {
  display: grid;
  grid-template-columns: 60px 160px 1fr 1fr 1fr 1fr 80px 100px 150px;
  border-bottom: 1px solid #eee;
  transition: background 0.2s ease;
}

/* 妯″潡鏍囩锛氶槻姝㈡孩鍑哄鑷翠笌涓嬩竴鍒楅噸鍙?*/
.module-tag {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  word-break: break-all;
}

.table-row:hover {
  background: #f8f9fa;
}

.header-cell, .body-cell {
  padding: 16px 8px;
  display: flex;
  align-items: flex-start; /* 鏀逛负椤堕儴瀵归綈,閬垮厤鍐呭琚鍓?*/
  border-right: 1px solid #eee;
  word-break: break-word;
  min-height: 60px;
}

/* 鏂囨湰鎴柇鏍峰紡 */
.text-truncate {
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  white-space: pre-wrap;
  line-height: 1.6;
  word-break: break-word;
}

.checkbox-cell {
  justify-content: center;
}

.header-cell:last-child, .body-cell:last-child {
  border-right: none;
}

.priority-tag {
  padding: 4px 8px;
  border-radius: 4px;
  font-size: 0.8rem;
  font-weight: bold;
}

.priority-tag.low {
  background: #e8f5e8;
  color: #388e3c;
}

.priority-tag.p3 {
  background: #e8f5e8;
  color: #388e3c;
}

.priority-tag.medium {
  background: #e3f2fd;
  color: #1976d2;
}

.priority-tag.p2 {
  background: #e3f2fd;
  color: #1976d2;
}

.priority-tag.high {
  background: #fff3e0;
  color: #f57c00;
}

.priority-tag.p1 {
  background: #fff3e0;
  color: #f57c00;
}

.priority-tag.critical {
  background: #ffebee;
  color: #d32f2f;
}

.priority-tag.p0 {
  background: #ffebee;
  color: #d32f2f;
}

.action-buttons {
  display: flex;
  gap: 5px;
  flex-direction: row;
  justify-content: center;
  flex-wrap: nowrap;
}

.view-btn, .adopt-btn, .discard-btn {
  padding: 4px 8px;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.8rem;
  transition: all 0.2s ease;
}

.view-btn {
  background: #3498db;
  color: white;
}

.view-btn:hover {
  background: #2980b9;
}

.adopt-btn {
  background: #27ae60;
  color: white;
}

.adopt-btn:hover {
  background: #229954;
}

.discard-btn {
  background: #e74c3c;
  color: white;
}

.discard-btn:hover {
  background: #c0392b;
}

.pagination-section {
  margin-top: 20px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: white;
  padding: 15px;
  border-radius: 8px;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
}

.pagination-controls {
  display: flex;
  align-items: center;
  gap: 20px;
}

.page-size-selector {
  display: flex;
  align-items: center;
  gap: 8px;
}

.pagination-buttons {
  display: flex;
  align-items: center;
  gap: 15px;
}

.pagination-buttons button {
  padding: 6px 12px;
  border: 1px solid #ddd;
  background: white;
  cursor: pointer;
  border-radius: 4px;
  transition: all 0.2s ease;
}

.pagination-buttons button:hover:not(:disabled) {
  background: #f0f0f0;
}

.pagination-buttons button:disabled {
  color: #ccc;
  cursor: not-allowed;
}

.case-detail-modal {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal-content {
  background: white;
  border-radius: 12px;
  max-width: 800px;
  width: 90%;
  max-height: 80vh;
  overflow-y: auto;
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20px 30px;
  border-bottom: 1px solid #eee;
}

.modal-header h3 {
  margin: 0;
  color: #2c3e50;
}

.close-btn {
  background: none;
  border: none;
  font-size: 1.5rem;
  cursor: pointer;
  color: #666;
}

.modal-body {
  padding: 30px;
}

.detail-item {
  margin-bottom: 20px;
}

.detail-item label {
  font-weight: bold;
  color: #2c3e50;
  display: block;
  margin-bottom: 8px;
}

.detail-item span, .detail-item p {
  color: #666;
  line-height: 1.6;
}

.test-steps {
  white-space: pre-line;
  background: #f8f9fa;
  padding: 15px;
  border-radius: 6px;
  border-left: 4px solid #3498db;
}

.loading-state, .error-state, .empty-state {
  text-align: center;
  padding: 60px 20px;
  color: #666;
}

.error-state h3, .empty-state h3 {
  color: #2c3e50;
  margin-bottom: 10px;
}

.error-state a {
  color: #3498db;
  text-decoration: none;
}

.error-state a:hover {
  text-decoration: underline;
}

/* 缂栬緫妯″紡鏍峰紡 */
.edit-mode {
  .form-item {
    margin-bottom: 20px;
  }

  .form-item label {
    font-weight: bold;
    color: #2c3e50;
    display: block;
    margin-bottom: 8px;
  }

  .readonly-field {
    color: #666;
    padding: 8px 12px;
    background: #f5f5f5;
    border-radius: 4px;
    display: inline-block;
  }
}

/* 搴曢儴鎿嶄綔鏍?*/
.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding: 20px 30px;
  border-top: 1px solid #eee;
  background: #f9f9f9;
  border-radius: 0 0 12px 12px;
}

.action-btn {
  padding: 10px 20px;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
  font-weight: 500;
  transition: all 0.3s;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.edit-btn {
  background: #409eff;
  color: white;
}

.edit-btn:hover {
  background: #66b1ff;
}

.save-btn {
  background: #67c23a;
  color: white;
}

.save-btn:hover:not(:disabled) {
  background: #85ce61;
}

.save-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.cancel-btn {
  background: #909399;
  color: white;
}

.cancel-btn:hover:not(:disabled) {
  background: #a6a9ad;
}

.close-btn-footer {
  background: #e4e7ed;
  color: #606266;
}

.close-btn-footer:hover {
  background: #ecf5ff;
}

/* ==================== 闇€姹傛緞娓呭璇濋潰鏉?==================== */
/* ===== Clarification Panel (refined) ===== */
.clarification-panel {
  background: #ffffff;
  border: 1px solid #ebeef5;
  border-radius: 12px;
  margin-bottom: 20px;
  box-shadow: 0 4px 20px rgba(64, 158, 255, 0.06);
  overflow: hidden;
}
.clarification-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 22px;
  background: linear-gradient(135deg, #f5f9ff 0%, #ecf5ff 100%);
  border-bottom: 1px solid #ebeef5;
}
.clarification-header-left {
  display: flex;
  align-items: center;
  gap: 14px;
}
.clarification-icon-wrap {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  background: linear-gradient(135deg, #409eff 0%, #5dadff 100%);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 4px 12px rgba(64, 158, 255, 0.3);
  flex-shrink: 0;
}
.clarification-header-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.clarification-title {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
  line-height: 1.3;
}
.clarification-subtitle {
  font-size: 12px;
  color: #909399;
  line-height: 1.4;
}
.clarification-status-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background: #f0f9eb;
  color: #67c23a;
  border-radius: 20px;
  font-size: 12px;
  font-weight: 500;
  border: 1px solid #d4edc4;
}

/* messages area */
.clarification-messages {
  max-height: 480px;
  min-height: 140px;
  overflow-y: auto;
  padding: 20px 22px;
  background: #fafbfc;
}
.clarification-messages::-webkit-scrollbar {
  width: 6px;
}
.clarification-messages::-webkit-scrollbar-thumb {
  background: #dcdfe6;
  border-radius: 3px;
}
.clarification-messages::-webkit-scrollbar-thumb:hover {
  background: #c0c4cc;
}

.clarification-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 30px 0;
  color: #909399;
  font-size: 13px;
}
.loading-spinner {
  width: 24px;
  height: 24px;
  border: 2.5px solid #ebeef5;
  border-top-color: #409eff;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}
.clarification-empty {
  text-align: center;
  color: #909399;
  padding: 30px 0;
  font-size: 13px;
}

/* chat message */
.chat-message {
  display: flex;
  gap: 10px;
  margin-bottom: 18px;
  animation: fadeIn 0.3s ease;
}
.chat-message:last-child {
  margin-bottom: 0;
}
@keyframes fadeIn {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}
.message-ai {
  flex-direction: row;
}
.message-user {
  flex-direction: row-reverse;
}
.message-avatar {
  flex-shrink: 0;
  width: 34px;
  height: 34px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.08);
}
.message-ai .message-avatar {
  background: linear-gradient(135deg, #67c23a 0%, #85ce61 100%);
}
.message-user .message-avatar {
  background: linear-gradient(135deg, #409eff 0%, #5dadff 100%);
}
.message-bubble-wrap {
  max-width: 78%;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.message-user .message-bubble-wrap {
  align-items: flex-end;
}
.message-bubble {
  padding: 10px 14px;
  border-radius: 12px;
  background: #fff;
  border: 1px solid #ebeef5;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
  position: relative;
  word-break: break-word;
}
.message-ai .message-bubble {
  border-top-left-radius: 4px;
}
.message-user .message-bubble {
  background: linear-gradient(135deg, #409eff 0%, #5dadff 100%);
  border-color: transparent;
  color: #fff;
  border-top-right-radius: 4px;
  box-shadow: 0 2px 8px rgba(64, 158, 255, 0.25);
}
.message-content {
  font-size: 13.5px;
  line-height: 1.65;
  word-break: break-word;
  white-space: normal;
}
.message-content :deep(p) {
  margin: 0 0 6px 0;
}
.message-content :deep(p:last-child) {
  margin-bottom: 0;
}
.message-content :deep(ul),
.message-content :deep(ol) {
  margin: 6px 0;
  padding-left: 20px;
}
.message-content :deep(code) {
  background: rgba(0, 0, 0, 0.06);
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 0.9em;
}
.message-user .message-content :deep(code) {
  background: rgba(255, 255, 255, 0.2);
}

/* AI clarification structured markdown */
.message-ai .message-content :deep(.clari-h) {
  font-size: 14.5px;
  font-weight: 600;
  color: #2c3e50;
  margin: 14px 0 8px 0;
  padding: 6px 10px;
  background: linear-gradient(90deg, rgba(64, 158, 255, 0.08) 0%, rgba(64, 158, 255, 0) 100%);
  border-left: 3px solid #409eff;
  border-radius: 0 4px 4px 0;
  line-height: 1.4;
}
.message-ai .message-content :deep(.clari-h:first-child) {
  margin-top: 0;
}
.message-ai .message-content :deep(.clari-ol),
.message-ai .message-content :deep(.clari-ul) {
  margin: 8px 0 12px 0;
  padding-left: 24px;
}
.message-ai .message-content :deep(.clari-ol li),
.message-ai .message-content :deep(.clari-ul li) {
  margin-bottom: 7px;
  line-height: 1.7;
  padding-left: 4px;
}
.message-ai .message-content :deep(.clari-ol li:last-child),
.message-ai .message-content :deep(.clari-ul li:last-child) {
  margin-bottom: 0;
}
.message-ai .message-content :deep(.clari-ol li::marker) {
  color: #409eff;
  font-weight: 600;
}
.message-ai .message-content :deep(.clari-ul li::marker) {
  color: #409eff;
}
.message-ai .message-content :deep(p) {
  margin: 6px 0 10px 0;
  line-height: 1.7;
}
.message-ai .message-content :deep(p:last-child) {
  margin-bottom: 0;
}
.message-ai .message-content :deep(strong) {
  color: #303133;
  font-weight: 600;
}
.message-ai .message-content :deep(em) {
  color: #606266;
  font-style: italic;
}
.message-ai .message-content :deep(.clari-done-badge) {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin-top: 14px;
  padding: 8px 14px;
  background: linear-gradient(135deg, #f0f9eb 0%, #e1f3d8 100%);
  border: 1px solid #b8e1a3;
  border-radius: 8px;
  font-size: 13px;
  color: #67c23a;
  font-weight: 500;
}
.message-ai .message-content :deep(.clari-done-dot) {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #67c23a;
  box-shadow: 0 0 0 3px rgba(103, 194, 58, 0.2);
  animation: clari-done-pulse 1.6s ease-in-out infinite;
}
@keyframes clari-done-pulse {
  0%, 100% { box-shadow: 0 0 0 3px rgba(103, 194, 58, 0.2); }
  50% { box-shadow: 0 0 0 6px rgba(103, 194, 58, 0); }
}
.message-meta {
  font-size: 11px;
  color: #c0c4cc;
  padding: 0 4px;
}
.message-content.typing {
  display: flex;
  gap: 5px;
  align-items: center;
  padding: 4px 2px;
}
.typing-dot {
  width: 7px;
  height: 7px;
  background: #c0c4cc;
  border-radius: 50%;
  animation: typing 1.4s infinite;
}
.typing-dot:nth-child(2) { animation-delay: 0.2s; }
.typing-dot:nth-child(3) { animation-delay: 0.4s; }
@keyframes typing {
  0%, 60%, 100% { transform: translateY(0); opacity: 0.4; }
  30% { transform: translateY(-5px); opacity: 1; }
}

/* footer */
.clarification-footer {
  border-top: 1px solid #ebeef5;
  padding: 16px 22px;
  background: #fff;
}
.clarification-input-area {
  margin-bottom: 12px;
}
.clarification-input-area :deep(.el-textarea__inner) {
  border-radius: 8px;
  border-color: #dcdfe6;
  padding: 10px 12px;
  font-size: 13.5px;
  line-height: 1.6;
  transition: border-color 0.2s, box-shadow 0.2s;
}
.clarification-input-area :deep(.el-textarea__inner:focus) {
  border-color: #409eff;
  box-shadow: 0 0 0 3px rgba(64, 158, 255, 0.1);
}
.clarification-input-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 10px;
  gap: 12px;
}
.clarification-input-hint {
  font-size: 12px;
  color: #909399;
}
.clarification-actions {
  display: flex;
  gap: 10px;
  justify-content: flex-end;
  flex-wrap: wrap;
  padding-top: 12px;
  border-top: 1px dashed #ebeef5;
}
.clarification-finalize-bar {
  padding: 16px 22px;
  background: #f0f9eb;
  border-top: 1px solid #d4edc4;
  display: flex;
  justify-content: flex-end;
}

/* unified buttons */
.btn-primary,
.btn-success,
.btn-ghost {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border-radius: 8px;
  border: 1px solid transparent;
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
  font-family: inherit;
  transition: all 0.2s;
  white-space: nowrap;
  line-height: 1;
}
.btn-primary {
  background: linear-gradient(135deg, #409eff 0%, #5dadff 100%);
  color: #fff;
  box-shadow: 0 2px 6px rgba(64, 158, 255, 0.25);
}
.btn-primary:hover:not(:disabled) {
  background: linear-gradient(135deg, #66b1ff 0%, #7dbeff 100%);
  box-shadow: 0 4px 10px rgba(64, 158, 255, 0.35);
  transform: translateY(-1px);
}
.btn-success {
  background: linear-gradient(135deg, #67c23a 0%, #85ce61 100%);
  color: #fff;
  box-shadow: 0 2px 6px rgba(103, 194, 58, 0.25);
}
.btn-success:hover:not(:disabled) {
  background: linear-gradient(135deg, #85ce61 0%, #95d674 100%);
  box-shadow: 0 4px 10px rgba(103, 194, 58, 0.35);
  transform: translateY(-1px);
}
.btn-ghost {
  background: #fff;
  color: #606266;
  border-color: #dcdfe6;
}
.btn-ghost:hover:not(:disabled) {
  background: #f5f7fa;
  color: #409eff;
  border-color: #c6e2ff;
}
.btn-primary:disabled,
.btn-success:disabled,
.btn-ghost:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  box-shadow: none;
  transform: none;
}
.btn-large {
  padding: 10px 22px;
  font-size: 14px;
}
</style>

<style>
/* 鍏ㄥ眬鏍峰紡:闅愯棌Element Plus鎶樺彔闈㈡澘鐨勯粯璁ょ澶村浘鏍?*/
.requirement-description-card .el-collapse-item__header .el-icon {
  display: none !important;
}

.requirement-description-card .el-collapse-item__arrow {
  display: none !important;
}

/* 閽堝Element Plus涓嶅悓鐗堟湰鐨勭澶村浘鏍?*/
.requirement-description-card .el-collapse-item__header .el-collapse-item__arrow {
  display: none !important;
}

.requirement-description-card .el-collapse-item__header .el-icon-arrow-right {
  display: none !important;
}

.requirement-description-card .el-collapse-item__header .el-icon-arrow-left {
  display: none !important;
}
</style>
