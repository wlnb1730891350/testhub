<template>
  <div class="command-center page-container">
    <section class="command-hero">
      <div class="command-hero__copy">
        <span class="hero-kicker">{{ copy.kicker }}</span>
        <h1>{{ copy.title }}</h1>
        <p>{{ copy.description }}</p>

        <div class="hero-actions">
          <el-button type="primary" size="large" @click="go('/ai-generation/requirement-analysis')">
            {{ copy.primaryAction }}
          </el-button>
          <el-button size="large" @click="go('/workspace/report-center')">
            {{ copy.secondaryAction }}
          </el-button>
          <el-button size="large" @click="go('/workspace/scheduler-center')">
            {{ copy.schedulerAction }}
          </el-button>
        </div>
      </div>

      <div class="command-hero__panel">
        <div class="hero-focus">
          <span>{{ copy.focusLabel }}</span>
          <strong>{{ focusTitle }}</strong>
          <p>{{ focusDescription }}</p>
        </div>

        <div class="hero-metrics">
          <article v-for="metric in metrics" :key="metric.label" class="metric-card">
            <span>{{ metric.label }}</span>
            <strong>{{ metric.value }}</strong>
            <p>{{ metric.description }}</p>
          </article>
        </div>
      </div>
    </section>

    <section class="card-section">
      <div class="section-header">
        <div>
          <p>{{ copy.roleEyebrow }}</p>
          <h2>{{ copy.roleTitle }}</h2>
        </div>
      </div>

      <div class="role-grid">
        <article v-for="role in roleCards" :key="role.title" class="role-card">
          <div class="role-card__icon" :style="{ '--accent': role.color }">
            <el-icon><component :is="role.icon" /></el-icon>
          </div>
          <h3>{{ role.title }}</h3>
          <p>{{ role.description }}</p>
          <ul>
            <li v-for="item in role.points" :key="item">{{ item }}</li>
          </ul>
        </article>
      </div>
    </section>

    <section class="card-section workflow-section">
      <div class="section-header">
        <div>
          <p>{{ copy.workflowEyebrow }}</p>
          <h2>{{ copy.workflowTitle }}</h2>
        </div>
        <span>{{ copy.workflowHint }}</span>
      </div>

      <div class="workflow-grid">
        <button
          v-for="step in workflow"
          :key="step.index"
          class="workflow-card"
          type="button"
          @click="go(step.route)"
        >
          <span class="workflow-card__index">{{ step.index }}</span>
          <h3>{{ step.title }}</h3>
          <p>{{ step.description }}</p>
          <strong>{{ step.routeLabel }}</strong>
        </button>
      </div>
    </section>

    <section class="card-section">
      <div class="section-header">
        <div>
          <p>{{ copy.activityEyebrow }}</p>
          <h2>{{ copy.activityTitle }}</h2>
        </div>
        <span v-if="loading">{{ copy.loading }}</span>
        <span v-else-if="loadError">{{ copy.loadError }}</span>
      </div>

      <div v-if="recentActivities.length" class="activity-list">
        <button
          v-for="item in recentActivities"
          :key="`${item.type}-${item.time}-${item.title}`"
          class="activity-card"
          type="button"
          @click="go(item.route)"
        >
          <div class="activity-card__meta">
            <span>{{ item.module }}</span>
            <strong>{{ formatStatus(item.status) }}</strong>
          </div>
          <h3>{{ item.title }}</h3>
          <p>{{ formatTime(item.time) }}</p>
        </button>
      </div>

      <div v-else class="activity-empty">
        {{ copy.activityEmpty }}
      </div>
    </section>

    <section class="card-section">
      <div class="section-header">
        <div>
          <p>{{ copy.matrixEyebrow }}</p>
          <h2>{{ copy.matrixTitle }}</h2>
        </div>
      </div>

      <div class="module-grid">
        <article
          v-for="card in modules"
          :key="card.route"
          class="module-card"
          role="button"
          tabindex="0"
          @click="go(card.route)"
          @keyup.enter="go(card.route)"
        >
          <div class="module-card__top">
            <div class="module-card__icon" :style="{ '--accent': card.color }">
              <el-icon><component :is="card.icon" /></el-icon>
            </div>
            <span class="module-card__tag">{{ card.tag }}</span>
          </div>
          <h3>{{ card.title }}</h3>
          <p>{{ card.description }}</p>
        </article>
      </div>
    </section>

    <section class="card-section roadmap-section">
      <div class="section-header">
        <div>
          <p>{{ copy.roadmapEyebrow }}</p>
          <h2>{{ copy.roadmapTitle }}</h2>
        </div>
      </div>

      <div class="roadmap-list">
        <article v-for="item in roadmap" :key="item.version" class="roadmap-card">
          <span>{{ item.version }}</span>
          <strong>{{ item.title }}</strong>
          <p>{{ item.description }}</p>
        </article>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAppStore } from '@/stores/app'
import dayjs from 'dayjs'
import api from '@/utils/api'
import {
  DataLine,
  Cpu,
  Monitor,
  Link,
  MagicStick,
  ChatDotRound,
  Setting,
  Cellphone,
  User,
  UserFilled,
  Promotion,
  Histogram,
  DocumentChecked
} from '@element-plus/icons-vue'

const router = useRouter()
const appStore = useAppStore()
const loading = ref(false)
const loadError = ref(false)
const workspaceData = ref(null)

const isChinese = computed(() => appStore.language === 'zh-cn')

const copy = computed(() =>
  isChinese.value
    ? {
        kicker: 'Platform Command Center',
        title: 'TestHub 平台工作台',
        description:
          '把需求、资产、执行、报告和 AI 协同放进一个统一指挥台，让团队先知道“现在该做什么”，再进入具体模块。',
        primaryAction: '进入需求分析',
        secondaryAction: '查看报告中心',
        schedulerAction: '进入调度中心',
        focusLabel: '本周重点',
        focusTitle: '先建立统一测试资产，再扩大自动化覆盖',
        focusDescription: '当前平台最适合优先强化需求分析、资产沉淀、统一报告与调度编排。',
        roleEyebrow: 'Roles',
        roleTitle: '按角色理解平台价值',
        activityEyebrow: 'Activity',
        activityTitle: '最近平台动态',
        activityEmpty: '当前还没有可展示的最新动态。',
        loading: '正在加载实时数据',
        loadError: '实时数据加载失败，当前展示静态规划视图',
        workflowEyebrow: 'Workflow',
        workflowTitle: '建议交付路径',
        workflowHint: '用交付流程组织平台，而不是按零散功能理解',
        matrixEyebrow: 'Modules',
        matrixTitle: '能力矩阵',
        roadmapEyebrow: 'Roadmap',
        roadmapTitle: '版本升级路线'
      }
    : {
        kicker: 'Platform Command Center',
        title: 'TestHub Command Center',
        description:
          'Unify requirements, assets, execution, reporting and AI collaboration in one operating surface so teams know what to do next immediately.',
        primaryAction: 'Open requirement analysis',
        secondaryAction: 'Open reporting center',
        schedulerAction: 'Open scheduler center',
        focusLabel: 'This week focus',
        focusTitle: 'Build shared testing assets before scaling automation',
        focusDescription: 'The strongest next step is to deepen requirement analysis, shared assets, unified reporting and orchestration.',
        roleEyebrow: 'Roles',
        roleTitle: 'Platform value by role',
        activityEyebrow: 'Activity',
        activityTitle: 'Recent platform activity',
        activityEmpty: 'No recent activity is available yet.',
        loading: 'Loading live data',
        loadError: 'Live data failed to load, showing planning view',
        workflowEyebrow: 'Workflow',
        workflowTitle: 'Suggested delivery path',
        workflowHint: 'Organized around delivery flow instead of isolated functions',
        matrixEyebrow: 'Modules',
        matrixTitle: 'Capability map',
        roadmapEyebrow: 'Roadmap',
        roadmapTitle: 'Upgrade roadmap'
      }
)

const metrics = computed(() =>
  isChinese.value
    ? [
        {
          label: '活跃项目',
          value: String(workspaceData.value?.metrics?.active_project_count ?? 0),
          description: `项目总数 ${workspaceData.value?.metrics?.project_count ?? 0}`
        },
        {
          label: '需求资产',
          value: String(workspaceData.value?.metrics?.requirement_doc_count ?? 0),
          description: `已生成用例 ${workspaceData.value?.metrics?.generated_case_count ?? 0}`
        },
        {
          label: '待处理评审',
          value: String(workspaceData.value?.metrics?.pending_review_count ?? 0),
          description: `报告总数 ${workspaceData.value?.metrics?.report_count ?? 0}`
        },
        {
          label: '运行中调度',
          value: String(workspaceData.value?.metrics?.active_schedule_count ?? 0),
          description: `执行通道 ${workspaceData.value?.metrics?.execution_lane_count ?? 4}`
        }
      ]
    : [
        {
          label: 'Active projects',
          value: String(workspaceData.value?.metrics?.active_project_count ?? 0),
          description: `Total projects ${workspaceData.value?.metrics?.project_count ?? 0}`
        },
        {
          label: 'Requirement assets',
          value: String(workspaceData.value?.metrics?.requirement_doc_count ?? 0),
          description: `Generated cases ${workspaceData.value?.metrics?.generated_case_count ?? 0}`
        },
        {
          label: 'Pending reviews',
          value: String(workspaceData.value?.metrics?.pending_review_count ?? 0),
          description: `Reports ${workspaceData.value?.metrics?.report_count ?? 0}`
        },
        {
          label: 'Active schedules',
          value: String(workspaceData.value?.metrics?.active_schedule_count ?? 0),
          description: `Execution lanes ${workspaceData.value?.metrics?.execution_lane_count ?? 4}`
        }
      ]
)

const focusTitle = computed(() => {
  const focus = workspaceData.value?.focus
  if (!focus) {
    return copy.value.focusTitle
  }

  return isChinese.value
    ? `近 7 天新增 ${focus.recent_generation_count} 次资产生成，执行 ${focus.recent_execution_count} 次`
    : `${focus.recent_generation_count} asset runs and ${focus.recent_execution_count} executions in the last 7 days`
})

const focusDescription = computed(() => {
  const focus = workspaceData.value?.focus
  if (!focus) {
    return copy.value.focusDescription
  }

  return isChinese.value
    ? `当前累计 API 执行 ${focus.api_execution_count} 次，UI 执行 ${focus.ui_execution_count} 次，APP 执行 ${focus.app_execution_count} 次，报告新增 ${focus.recent_report_count} 份。`
    : `Current totals: ${focus.api_execution_count} API executions, ${focus.ui_execution_count} UI executions, ${focus.app_execution_count} APP executions and ${focus.recent_report_count} new reports.`
})

const recentActivities = computed(() => workspaceData.value?.recent_activities ?? [])

const roleCards = computed(() =>
  isChinese.value
    ? [
        {
          title: '测试负责人',
          description: '更快看到平台状态、交付进度和能力短板。',
          points: ['先看工作台，再决定优先推进哪个模块', '用统一报告和调度入口管理节奏', '关注平台建设而不是单页操作'],
          icon: UserFilled,
          color: '#1d4ed8'
        },
        {
          title: '测试工程师',
          description: '明确从需求到执行的下一步动作，减少找入口成本。',
          points: ['先沉淀需求和用例资产', '再进入 API、UI、APP 自动化执行', '最后回收报告和失败信息'],
          icon: User,
          color: '#0f766e'
        }
      ]
    : [
        {
          title: 'Test leads',
          description: 'Get a faster view of delivery status, platform maturity and risk.',
          points: ['Start from the command center', 'Use unified reporting and orchestration', 'Operate the platform instead of isolated pages'],
          icon: UserFilled,
          color: '#1d4ed8'
        },
        {
          title: 'Test engineers',
          description: 'Know the next move in the workflow without hunting through menus.',
          points: ['Build requirement and case assets first', 'Move into API, UI and APP execution', 'Close the loop through reports and failures'],
          icon: User,
          color: '#0f766e'
        }
      ]
)

const workflow = computed(() =>
  isChinese.value
    ? [
        {
          index: '01',
          title: '需求分析',
          description: '从需求文档和版本信息中提取可执行测试输入。',
          route: '/ai-generation/requirement-analysis',
          routeLabel: '进入分析模块'
        },
        {
          index: '02',
          title: '测试资产沉淀',
          description: '生成并评审测试用例，形成可复用资产。',
          route: '/ai-generation/generated-testcases',
          routeLabel: '查看生成结果'
        },
        {
          index: '03',
          title: '自动化执行',
          description: '根据类型进入 API、UI、APP 或 AI 智能执行通道。',
          route: '/ui-automation/dashboard',
          routeLabel: '进入执行模块'
        },
        {
          index: '04',
          title: '报告与治理',
          description: '通过报告、通知、调度和配置形成闭环。',
          route: '/configuration/ai-model',
          routeLabel: '进入治理中心'
        }
      ]
    : [
        {
          index: '01',
          title: 'Requirement analysis',
          description: 'Extract executable testing inputs from requirement documents and versions.',
          route: '/ai-generation/requirement-analysis',
          routeLabel: 'Open analysis module'
        },
        {
          index: '02',
          title: 'Testing asset creation',
          description: 'Generate and review cases to create reusable testing assets.',
          route: '/ai-generation/generated-testcases',
          routeLabel: 'Review generated assets'
        },
        {
          index: '03',
          title: 'Automation execution',
          description: 'Route work into API, UI, APP or AI-driven execution lanes.',
          route: '/ui-automation/dashboard',
          routeLabel: 'Open execution modules'
        },
        {
          index: '04',
          title: 'Reporting and governance',
          description: 'Close the loop through reporting, notifications, orchestration and configuration.',
          route: '/configuration/ai-model',
          routeLabel: 'Open governance center'
        }
      ]
)

const modules = computed(() => [
  {
    title: isChinese.value ? 'AI 用例生成' : 'AI Case Generation',
    description: isChinese.value ? '需求分析、用例生成与评审沉淀。' : 'Requirement analysis, case generation and review.',
    route: '/ai-generation/requirement-analysis',
    tag: isChinese.value ? '资产生产线' : 'Asset pipeline',
    icon: MagicStick,
    color: '#0f766e'
  },
  {
    title: isChinese.value ? '接口测试' : 'API Testing',
    description: isChinese.value ? '接口、环境、自动化、历史和报告。' : 'Interfaces, environments, automation, history and reporting.',
    route: '/api-testing/dashboard',
    tag: 'API',
    icon: Link,
    color: '#1d4ed8'
  },
  {
    title: isChinese.value ? 'UI 自动化' : 'UI Automation',
    description: isChinese.value ? '元素、脚本、套件、执行与报告。' : 'Elements, scripts, suites, execution and reporting.',
    route: '/ui-automation/dashboard',
    tag: 'UI',
    icon: Monitor,
    color: '#b45309'
  },
  {
    title: isChinese.value ? 'APP 自动化' : 'APP Automation',
    description: isChinese.value ? '设备、场景、测试包和移动执行。' : 'Devices, scenarios, packages and mobile execution.',
    route: '/app-automation/dashboard',
    tag: 'APP',
    icon: Cellphone,
    color: '#0f172a'
  },
  {
    title: isChinese.value ? '数据工厂' : 'Data Factory',
    description: isChinese.value ? '为多模块提供统一测试数据。' : 'Shared testing data for multiple modules.',
    route: '/data-factory',
    tag: isChinese.value ? '底座能力' : 'Foundation',
    icon: DataLine,
    color: '#0f766e'
  },
  {
    title: isChinese.value ? 'AI 智能模式' : 'AI Mode',
    description: isChinese.value ? 'AI 驱动执行、案例和追踪。' : 'AI-driven execution, case handling and tracking.',
    route: '/ai-intelligent-mode/testing',
    tag: 'AI',
    icon: Cpu,
    color: '#7c3aed'
  },
  {
    title: isChinese.value ? 'AI 助手' : 'AI Assistant',
    description: isChinese.value ? '让 AI 参与分析、改写和协作。' : 'Use AI for analysis, rewriting and collaboration.',
    route: '/ai-generation/assistant',
    tag: isChinese.value ? '协同能力' : 'Collaboration',
    icon: ChatDotRound,
    color: '#c2410c'
  },
  {
    title: isChinese.value ? '配置中心' : 'Configuration Center',
    description: isChinese.value ? '模型、环境、调度和通知管理。' : 'Models, environments, schedules and notifications.',
    route: '/configuration/ai-model',
    tag: isChinese.value ? '治理能力' : 'Governance',
    icon: Setting,
    color: '#334155'
  }
])

const roadmap = computed(() =>
  isChinese.value
    ? [
        { version: 'V2.1', title: '统一平台入口', description: '完成首页升级、平台工作台和统一外壳表达。' },
        { version: 'V2.2', title: '接入真实平台统计', description: '把任务、执行、报告和风险数据接入工作台。' },
        { version: 'V2.3', title: '交付闭环平台化', description: '统一报告、调度、提醒和资产关联，形成平台闭环。' }
      ]
    : [
        { version: 'V2.1', title: 'Unified platform entry', description: 'Upgrade the home experience, command center and shell language.' },
        { version: 'V2.2', title: 'Real platform metrics', description: 'Bring task, execution, report and risk data into the command center.' },
        { version: 'V2.3', title: 'Delivery loop platformization', description: 'Unify reporting, orchestration, reminders and asset linkage.' }
      ]
)

const loadWorkspace = async () => {
  loading.value = true
  loadError.value = false

  try {
    const response = await api.get('/core/workspace/')
    workspaceData.value = response.data
  } catch (error) {
    console.error('Failed to load workspace dashboard:', error)
    loadError.value = true
  } finally {
    loading.value = false
  }
}

const formatTime = (value) => {
  if (!value) return ''
  return dayjs(value).format('YYYY-MM-DD HH:mm')
}

const formatStatus = (value) => {
  if (!value) return isChinese.value ? '未知状态' : 'Unknown'

  const map = {
    pending: isChinese.value ? '待处理' : 'Pending',
    in_progress: isChinese.value ? '进行中' : 'In Progress',
    generating: isChinese.value ? '生成中' : 'Generating',
    reviewing: isChinese.value ? '评审中' : 'Reviewing',
    revising: isChinese.value ? '修订中' : 'Revising',
    completed: isChinese.value ? '已完成' : 'Completed',
    failed: isChinese.value ? '失败' : 'Failed',
    PENDING: isChinese.value ? '待执行' : 'Pending',
    RUNNING: isChinese.value ? '执行中' : 'Running',
    COMPLETED: isChinese.value ? '已完成' : 'Completed',
    FAILED: isChinese.value ? '失败' : 'Failed'
  }

  return map[value] || value
}

const go = (path) => {
  router.push(path)
}

onMounted(() => {
  loadWorkspace()
})
</script>

<style scoped lang="scss">
.command-center {
  gap: 24px;
}

.command-hero,
.card-section {
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 28px;
  background:
    radial-gradient(circle at top left, rgba(56, 189, 248, 0.14), transparent 28%),
    radial-gradient(circle at bottom right, rgba(20, 184, 166, 0.14), transparent 32%),
    linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(248, 250, 252, 0.92));
  box-shadow: 0 24px 70px rgba(15, 23, 42, 0.08);
}

.command-hero {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(0, 0.8fr);
  gap: 24px;
  padding: 28px;
}

.hero-kicker,
.section-header p {
  margin: 0 0 10px;
  color: #0f766e;
  font-size: 0.8rem;
  font-weight: 700;
  letter-spacing: 0.16em;
  text-transform: uppercase;
}

.command-hero__copy h1,
.section-header h2,
.role-card h3,
.workflow-card h3,
.module-card h3 {
  margin: 0;
  color: #0f172a;
}

.command-hero__copy h1 {
  font-size: clamp(2rem, 4vw, 3.1rem);
  line-height: 1.06;
}

.command-hero__copy p {
  margin: 16px 0 0;
  max-width: 740px;
  color: #475569;
  font-size: 1rem;
  line-height: 1.75;
}

.hero-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  margin-top: 24px;
}

.command-hero__panel,
.hero-metrics,
.roadmap-list,
.activity-list {
  display: grid;
  gap: 16px;
}

.hero-focus,
.metric-card,
.role-card,
.workflow-card,
.module-card,
.roadmap-card,
.activity-card {
  border: 1px solid rgba(148, 163, 184, 0.14);
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.84);
}

.hero-focus {
  padding: 22px;
  background: linear-gradient(135deg, rgba(29, 78, 216, 0.94), rgba(15, 118, 110, 0.94));
  color: white;
}

.hero-focus span,
.metric-card span,
.roadmap-card span {
  font-size: 0.82rem;
  font-weight: 700;
}

.hero-focus strong,
.metric-card strong,
.roadmap-card strong {
  display: block;
  margin-top: 10px;
  font-size: 1.18rem;
}

.hero-focus p,
.metric-card p,
.roadmap-card p,
.role-card p,
.workflow-card p,
.module-card p {
  margin: 10px 0 0;
  color: inherit;
  line-height: 1.65;
}

.hero-metrics {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.metric-card {
  padding: 18px;
}

.card-section {
  padding: 26px;
}

.section-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 22px;
}

.section-header span {
  color: #64748b;
}

.role-grid,
.workflow-grid,
.module-grid {
  display: grid;
  gap: 18px;
}

.role-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.workflow-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.module-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.role-card,
.module-card {
  padding: 22px;
}

.workflow-card {
  padding: 20px;
  text-align: left;
  cursor: pointer;
}

.workflow-card,
.module-card,
.activity-card {
  transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;
}

.workflow-card:hover,
.module-card:hover,
.module-card:focus-visible,
.activity-card:hover,
.activity-card:focus-visible {
  transform: translateY(-3px);
  border-color: rgba(29, 78, 216, 0.22);
  box-shadow: 0 18px 36px rgba(15, 23, 42, 0.08);
  outline: none;
}

.role-card__icon,
.module-card__icon {
  width: 48px;
  height: 48px;
  display: grid;
  place-items: center;
  border-radius: 16px;
  background: color-mix(in srgb, var(--accent) 14%, white);
  color: var(--accent);
  font-size: 1.2rem;
}

.role-card ul {
  margin: 14px 0 0;
  padding-left: 18px;
  color: #334155;
}

.role-card li + li {
  margin-top: 8px;
}

.workflow-card__index {
  display: inline-grid;
  place-items: center;
  width: 44px;
  height: 44px;
  border-radius: 14px;
  background: rgba(29, 78, 216, 0.1);
  color: #1d4ed8;
  font-weight: 800;
}

.workflow-card strong {
  display: inline-block;
  margin-top: 16px;
  color: #1d4ed8;
}

.module-card__top {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.module-card__tag {
  padding: 7px 12px;
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.06);
  color: #334155;
  font-size: 0.78rem;
  font-weight: 700;
}

.roadmap-list {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.activity-list {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.roadmap-card {
  padding: 20px;
}

.activity-card {
  padding: 18px;
  text-align: left;
  cursor: pointer;
}

.activity-card__meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  color: #64748b;
}

.activity-card h3 {
  margin-top: 12px;
  color: #0f172a;
}

.activity-empty {
  padding: 18px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.72);
  color: #64748b;
}

@media (max-width: 1200px) {
  .workflow-grid,
  .module-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 900px) {
  .command-hero,
  .role-grid,
  .roadmap-list,
  .activity-list {
    grid-template-columns: 1fr;
  }

  .hero-metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .command-hero,
  .card-section {
    padding: 18px;
    border-radius: 22px;
  }

  .hero-metrics,
  .workflow-grid,
  .module-grid {
    grid-template-columns: 1fr;
  }

  .hero-actions {
    flex-direction: column;
  }
}
</style>
