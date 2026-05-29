<template>
  <div class="home-shell">
    <section class="hero-panel">
      <div class="hero-topbar">
        <div class="hero-brand">
          <div class="hero-brand__mark">
            <img :src="logoImage" alt="TestHub" />
          </div>
          <div>
            <p class="hero-brand__eyebrow">{{ pageCopy.eyebrow }}</p>
            <h1>{{ pageCopy.brandTitle }}</h1>
          </div>
        </div>

        <div class="hero-actions">
          <el-dropdown @command="handleLanguageChange">
            <button class="ghost-pill" type="button">
              <span>{{ currentLanguageLabel }}</span>
              <el-icon><ArrowDown /></el-icon>
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="zh-cn" :disabled="currentLanguage === 'zh-cn'">
                  简体中文
                </el-dropdown-item>
                <el-dropdown-item command="en" :disabled="currentLanguage === 'en'">
                  English
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>

          <el-dropdown @command="handleCommand">
            <button class="ghost-pill" type="button">
              <el-avatar :size="28" :icon="UserFilled" />
              <span>{{ userStore.user?.username || pageCopy.userFallback }}</span>
              <el-icon><ArrowDown /></el-icon>
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="logout">{{ pageCopy.logout }}</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </div>

      <div class="hero-content">
        <div class="hero-copy">
          <span class="hero-badge">{{ pageCopy.badge }}</span>
          <h2>{{ pageCopy.title }}</h2>
          <p>{{ pageCopy.description }}</p>

          <div class="hero-cta">
            <el-button size="large" @click="navigateTo('/workspace/command-center')">
              {{ pageCopy.workspaceAction }}
            </el-button>
            <el-button type="primary" size="large" @click="navigateTo('/ai-generation/requirement-analysis')">
              {{ pageCopy.primaryAction }}
            </el-button>
            <el-button size="large" @click="navigateTo('/ui-automation/dashboard')">
              {{ pageCopy.secondaryAction }}
            </el-button>
          </div>

          <div class="hero-highlights">
            <span v-for="item in pageCopy.highlights" :key="item">{{ item }}</span>
          </div>
        </div>

        <div class="hero-summary">
          <div class="summary-card summary-card--primary">
            <p>{{ pageCopy.summaryTitle }}</p>
            <strong>{{ pageCopy.summaryValue }}</strong>
            <span>{{ pageCopy.summaryDescription }}</span>
          </div>

          <div class="summary-grid">
            <div v-for="metric in metrics" :key="metric.label" class="summary-card">
              <span>{{ metric.label }}</span>
              <strong>{{ metric.value }}</strong>
              <p>{{ metric.description }}</p>
            </div>
          </div>
        </div>
      </div>
    </section>

    <section class="section-block">
      <div class="section-heading">
        <div>
          <p>{{ pageCopy.moduleEyebrow }}</p>
          <h3>{{ pageCopy.moduleTitle }}</h3>
        </div>
        <span>{{ pageCopy.moduleHint }}</span>
      </div>

      <div class="module-grid">
        <article
          v-for="card in platformCards"
          :key="card.route"
          class="module-card"
          role="button"
          tabindex="0"
          @click="navigateTo(card.route)"
          @keyup.enter="navigateTo(card.route)"
        >
          <div class="module-card__top">
            <div class="module-card__icon" :style="{ '--accent': card.color }">
              <el-icon><component :is="card.icon" /></el-icon>
            </div>
            <span class="module-card__status">{{ card.status }}</span>
          </div>
          <h4>{{ card.title }}</h4>
          <p>{{ card.description }}</p>
          <div class="module-card__footer">
            <span>{{ card.routeLabel }}</span>
            <el-icon><Right /></el-icon>
          </div>
        </article>
      </div>
    </section>

    <section class="section-block section-block--split">
      <div class="journey-panel">
        <div class="section-heading">
          <div>
            <p>{{ pageCopy.journeyEyebrow }}</p>
            <h3>{{ pageCopy.journeyTitle }}</h3>
          </div>
        </div>

        <div class="journey-list">
          <div v-for="step in workflowSteps" :key="step.index" class="journey-item">
            <span class="journey-item__index">{{ step.index }}</span>
            <div>
              <h4>{{ step.title }}</h4>
              <p>{{ step.description }}</p>
            </div>
          </div>
        </div>
      </div>

      <div class="insight-panel">
        <div class="section-heading">
          <div>
            <p>{{ pageCopy.recommendationEyebrow }}</p>
            <h3>{{ pageCopy.recommendationTitle }}</h3>
          </div>
        </div>

        <div class="insight-list">
          <button
            v-for="action in quickActions"
            :key="action.title"
            class="insight-item"
            type="button"
            @click="navigateTo(action.route)"
          >
            <div class="insight-item__icon" :style="{ '--accent': action.color }">
              <el-icon><component :is="action.icon" /></el-icon>
            </div>
            <div>
              <h4>{{ action.title }}</h4>
              <p>{{ action.description }}</p>
            </div>
          </button>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { useAppStore } from '@/stores/app'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ArrowDown,
  UserFilled,
  MagicStick,
  Link,
  Monitor,
  DataLine,
  Cpu,
  Setting,
  ChatDotRound,
  Cellphone,
  Histogram,
  Right,
  Calendar,
  DocumentChecked,
  Promotion
} from '@element-plus/icons-vue'
import logoImage from '@/assets/images/logo_home.png'

const router = useRouter()
const userStore = useUserStore()
const appStore = useAppStore()

const currentLanguage = computed(() => appStore.language)
const isChinese = computed(() => currentLanguage.value === 'zh-cn')
const currentLanguageLabel = computed(() => (isChinese.value ? '简体中文' : 'English'))

const pageCopy = computed(() =>
  isChinese.value
    ? {
        eyebrow: 'Unified AI Testing Workspace',
        brandTitle: 'TestHub 测试集成平台',
        userFallback: '用户',
        logout: '退出登录',
        badge: '覆盖需求、接口、UI、APP 与 AI 协作的一体化测试入口',
        title: '把测试设计、执行编排和结果回收统一到一个工作台',
        description:
          '不再依赖零散页面和分离工具，团队可以从需求分析出发，串起自动化执行、报告沉淀、资产复用和 AI 协同。',
        workspaceAction: '进入平台工作台',
        primaryAction: '开始需求分析',
        secondaryAction: '查看自动化总览',
        highlights: ['统一入口', '跨模块协作', '可沉淀测试资产'],
        summaryTitle: '推荐起点',
        summaryValue: '先完成需求分析与用例沉淀',
        summaryDescription: '先把测试资产做厚，再逐步放大自动化执行和报告闭环。',
        moduleEyebrow: 'Platform Modules',
        moduleTitle: '平台能力矩阵',
        moduleHint: '围绕真实测试流转设计，而不是简单堆叠功能页面',
        journeyEyebrow: 'Recommended Flow',
        journeyTitle: '建议使用路径',
        recommendationEyebrow: 'Quick Start',
        recommendationTitle: '下一步值得优先增强的能力',
        logoutConfirm: '确定要退出登录吗？',
        logoutTitle: '提示',
        confirm: '确定',
        cancel: '取消',
        logoutSuccess: '已退出登录'
      }
    : {
        eyebrow: 'Unified AI Testing Workspace',
        brandTitle: 'TestHub Testing Platform',
        userFallback: 'User',
        logout: 'Logout',
        badge: 'A single surface for requirements, API, UI, APP and AI-assisted testing',
        title: 'Bring design, orchestration and execution evidence into one workspace',
        description:
          'Move the team away from scattered tools and connect requirement analysis, automation, reporting, reusable assets and AI collaboration in one platform.',
        workspaceAction: 'Open command center',
        primaryAction: 'Start requirement analysis',
        secondaryAction: 'Open automation overview',
        highlights: ['Unified entry point', 'Cross-module collaboration', 'Reusable testing assets'],
        summaryTitle: 'Suggested start',
        summaryValue: 'Begin with requirement analysis and case creation',
        summaryDescription: 'Create a strong asset base first, then scale automation and reporting.',
        moduleEyebrow: 'Platform Modules',
        moduleTitle: 'Capability map',
        moduleHint: 'Structured around delivery flow instead of isolated pages',
        journeyEyebrow: 'Recommended Flow',
        journeyTitle: 'Suggested journey through TestHub',
        recommendationEyebrow: 'Quick Start',
        recommendationTitle: 'High-value upgrades to push next',
        logoutConfirm: 'Are you sure you want to log out?',
        logoutTitle: 'Notice',
        confirm: 'Confirm',
        cancel: 'Cancel',
        logoutSuccess: 'Logged out successfully'
      }
)

const metrics = computed(() =>
  isChinese.value
    ? [
        { label: '核心模块', value: '8', description: '覆盖主测试链路与协作场景' },
        { label: '执行通道', value: '4', description: '需求 / API / UI / APP' },
        { label: '统一门户', value: '1', description: '登录后即可直达平台全部能力' }
      ]
    : [
        { label: 'Core modules', value: '8', description: 'Covering the main testing workflow' },
        { label: 'Execution lanes', value: '4', description: 'Requirements / API / UI / APP' },
        { label: 'Unified portal', value: '1', description: 'One operating surface after sign-in' }
      ]
)

const statusText = computed(() =>
  isChinese.value
    ? { ready: '可立即使用', scale: '建议增强', explore: '适合扩展' }
    : { ready: 'Ready', scale: 'Needs upgrade', explore: 'Expandable' }
)

const platformCards = computed(() => [
  {
    title: isChinese.value ? 'AI 用例生成' : 'AI Case Generation',
    description: isChinese.value
      ? '从需求分析出发，自动生成测试用例并沉淀评审资产。'
      : 'Turn requirement analysis into generated test cases and reusable review assets.',
    route: '/ai-generation/requirement-analysis',
    routeLabel: isChinese.value ? '进入需求分析' : 'Open requirement analysis',
    icon: MagicStick,
    color: '#0f766e',
    status: statusText.value.ready
  },
  {
    title: isChinese.value ? '接口测试' : 'API Testing',
    description: isChinese.value
      ? '统一管理接口、环境、自动化任务、请求历史和测试报告。'
      : 'Manage interfaces, environments, automation runs, history and reporting together.',
    route: '/api-testing/dashboard',
    routeLabel: isChinese.value ? '进入接口测试' : 'Open API workspace',
    icon: Link,
    color: '#1d4ed8',
    status: statusText.value.ready
  },
  {
    title: isChinese.value ? 'UI 自动化测试' : 'UI Automation',
    description: isChinese.value
      ? '围绕元素、脚本、套件、执行记录和报告组织桌面端自动化。'
      : 'Organize UI automation around elements, scripts, suites, execution records and reports.',
    route: '/ui-automation/dashboard',
    routeLabel: isChinese.value ? '进入 UI 自动化' : 'Open UI automation',
    icon: Monitor,
    color: '#b45309',
    status: statusText.value.ready
  },
  {
    title: isChinese.value ? 'APP 自动化测试' : 'APP Automation',
    description: isChinese.value
      ? '按设备、场景、测试包和执行记录串起移动端自动化链路。'
      : 'Drive mobile automation with devices, scenarios, app packages and execution records.',
    route: '/app-automation/dashboard',
    routeLabel: isChinese.value ? '进入 APP 自动化' : 'Open APP automation',
    icon: Cellphone,
    color: '#0f172a',
    status: statusText.value.scale
  },
  {
    title: isChinese.value ? '数据工厂' : 'Data Factory',
    description: isChinese.value
      ? '集中构造和分发测试数据，给多模块协作提供统一支撑。'
      : 'Create and distribute testing data for shared use across modules.',
    route: '/data-factory',
    routeLabel: isChinese.value ? '管理测试数据' : 'Open data factory',
    icon: DataLine,
    color: '#0f766e',
    status: statusText.value.explore
  },
  {
    title: isChinese.value ? 'AI 智能模式' : 'AI Intelligent Mode',
    description: isChinese.value
      ? '聚焦 AI 驱动的执行、案例管理和过程追踪。'
      : 'Focus on AI-driven execution, case management and operational tracking.',
    route: '/ai-intelligent-mode/testing',
    routeLabel: isChinese.value ? '进入 AI 模式' : 'Open AI mode',
    icon: Cpu,
    color: '#7c3aed',
    status: statusText.value.scale
  },
  {
    title: isChinese.value ? 'AI 助手' : 'AI Assistant',
    description: isChinese.value
      ? '让 AI 参与生成、改写、分析和协作沟通，而不只是回答问题。'
      : 'Use AI for generation, rewriting, analysis and collaborative follow-up.',
    route: '/ai-generation/assistant',
    routeLabel: isChinese.value ? '打开 AI 助手' : 'Open AI assistant',
    icon: ChatDotRound,
    color: '#c2410c',
    status: statusText.value.explore
  },
  {
    title: isChinese.value ? '配置中心' : 'Configuration Center',
    description: isChinese.value
      ? '统一管理模型、环境、通知、调度和平台配置。'
      : 'Manage models, environments, schedules, notifications and platform setup together.',
    route: '/configuration/ai-model',
    routeLabel: isChinese.value ? '进入配置中心' : 'Open configuration',
    icon: Setting,
    color: '#334155',
    status: statusText.value.ready
  }
])

const workflowSteps = computed(() =>
  isChinese.value
    ? [
        {
          index: '01',
          title: '先把需求变成可复用测试资产',
          description: '从需求、版本、评审和 AI 生成用例开始，让平台先拥有稳定的测试设计输入。'
        },
        {
          index: '02',
          title: '再把执行落到合适的自动化通道',
          description: '根据测试类型进入 API、UI 或 APP 模块，逐步补齐环境、脚本、调度与执行记录。'
        },
        {
          index: '03',
          title: '最后用报告和配置形成闭环',
          description: '把报告、通知和 AI 配置串起来，让结果回收、复盘和优化变成平台能力。'
        }
      ]
    : [
        {
          index: '01',
          title: 'Turn requirements into reusable test assets',
          description: 'Start with requirements, versions, reviews and generated cases so the platform owns strong design input.'
        },
        {
          index: '02',
          title: 'Route execution into the right automation lane',
          description: 'Move into API, UI or APP automation and complete environments, scripts, schedules and execution records.'
        },
        {
          index: '03',
          title: 'Close the loop with reporting and configuration',
          description: 'Use reports, notifications and AI setup to turn separate runs into a real operating workflow.'
        }
      ]
)

const quickActions = computed(() =>
  isChinese.value
    ? [
        {
          title: '统一报告出口',
          description: '优先整合 API、UI 和 APP 的报告视图，平台感会明显提升。',
          route: '/ui-automation/reports',
          icon: Histogram,
          color: '#1d4ed8'
        },
        {
          title: '强化任务编排入口',
          description: '把计划、调度和通知串成一条清晰路径，更容易体现平台级能力。',
          route: '/api-testing/scheduled-tasks',
          icon: Calendar,
          color: '#0f766e'
        },
        {
          title: '沉淀测试资产库',
          description: '把项目、用例、脚本、元素和环境串联起来，复用性会显著增强。',
          route: '/ui-automation/test-cases',
          icon: DocumentChecked,
          color: '#b45309'
        },
        {
          title: '把 AI 助手升级为工作台',
          description: '让 AI 负责生成、改写、分析和跟进动作，而不是只做对话入口。',
          route: '/ai-generation/assistant',
          icon: Promotion,
          color: '#c2410c'
        }
      ]
    : [
        {
          title: 'Unify the reporting surface',
          description: 'Consolidate API, UI and APP outputs into a stronger shared reporting center.',
          route: '/ui-automation/reports',
          icon: Histogram,
          color: '#1d4ed8'
        },
        {
          title: 'Strengthen task orchestration',
          description: 'Create one clear path for plans, schedules and notifications.',
          route: '/api-testing/scheduled-tasks',
          icon: Calendar,
          color: '#0f766e'
        },
        {
          title: 'Build a testing asset library',
          description: 'Link projects, cases, scripts, elements and environments to improve reuse across modules.',
          route: '/ui-automation/test-cases',
          icon: DocumentChecked,
          color: '#b45309'
        },
        {
          title: 'Turn AI assistant into a workbench',
          description: 'Let AI drive generation, rewriting, analysis and follow-up actions.',
          route: '/ai-generation/assistant',
          icon: Promotion,
          color: '#c2410c'
        }
      ]
)

const handleLanguageChange = (lang) => {
  appStore.setLanguage(lang)
}

const handleCommand = (command) => {
  if (command !== 'logout') return

  ElMessageBox.confirm(pageCopy.value.logoutConfirm, pageCopy.value.logoutTitle, {
    confirmButtonText: pageCopy.value.confirm,
    cancelButtonText: pageCopy.value.cancel,
    type: 'warning'
  })
    .then(async () => {
      await userStore.logout()
      ElMessage.success(pageCopy.value.logoutSuccess)
    })
    .catch(() => {})
}

const navigateTo = (path) => {
  router.push(path)
}
</script>

<style scoped lang="scss">
.home-shell {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.hero-panel,
.section-block {
  position: relative;
  overflow: hidden;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 28px;
  background:
    radial-gradient(circle at top left, rgba(14, 165, 233, 0.16), transparent 30%),
    radial-gradient(circle at bottom right, rgba(15, 118, 110, 0.16), transparent 35%),
    linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(248, 250, 252, 0.92));
  box-shadow: 0 24px 70px rgba(15, 23, 42, 0.08);
}

.hero-panel {
  padding: 28px;
}

.hero-topbar,
.hero-content,
.section-block--split {
  display: grid;
  gap: 24px;
}

.hero-topbar {
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  margin-bottom: 28px;
}

.hero-brand {
  display: flex;
  align-items: center;
  gap: 16px;

  h1 {
    margin: 6px 0 0;
    font-size: clamp(2rem, 3vw, 2.8rem);
    line-height: 1;
    color: #0f172a;
  }
}

.hero-brand__mark {
  width: 72px;
  height: 72px;
  display: grid;
  place-items: center;
  border-radius: 24px;
  background: linear-gradient(135deg, rgba(29, 78, 216, 0.14), rgba(15, 118, 110, 0.2));
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.6);
  padding: 14px;
}

.hero-brand__eyebrow {
  margin: 0;
  color: #0f766e;
  font-size: 0.78rem;
  font-weight: 700;
  letter-spacing: 0.18em;
  text-transform: uppercase;
}

.hero-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
  flex-wrap: wrap;
}

.ghost-pill {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 44px;
  padding: 0 16px;
  border: 1px solid rgba(148, 163, 184, 0.24);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.8);
  color: #0f172a;
  cursor: pointer;
  transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;
}

.ghost-pill:hover {
  transform: translateY(-1px);
  border-color: rgba(29, 78, 216, 0.28);
  box-shadow: 0 12px 28px rgba(15, 23, 42, 0.08);
}

.hero-content,
.section-block--split {
  grid-template-columns: minmax(0, 1.2fr) minmax(0, 0.8fr);
}

.hero-copy h2,
.section-heading h3,
.journey-item h4,
.insight-item h4,
.module-card h4 {
  margin: 0;
  color: #0f172a;
}

.hero-copy h2 {
  margin-top: 18px;
  font-size: clamp(2rem, 4vw, 3.3rem);
  line-height: 1.08;
}

.hero-copy p {
  margin: 16px 0 0;
  max-width: 720px;
  color: #475569;
  font-size: 1rem;
  line-height: 1.75;
}

.hero-badge {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  background: rgba(15, 118, 110, 0.12);
  color: #0f766e;
  padding: 8px 14px;
  font-size: 0.92rem;
  font-weight: 600;
}

.hero-cta {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  margin-top: 24px;
}

.hero-highlights {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 24px;
}

.hero-highlights span {
  padding: 10px 14px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.72);
  color: #334155;
  font-weight: 600;
}

.hero-summary,
.summary-grid,
.journey-list,
.insight-list {
  display: grid;
  gap: 16px;
}

.summary-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.summary-card {
  padding: 22px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.82);
  backdrop-filter: blur(14px);
}

.summary-card--primary {
  background: linear-gradient(135deg, rgba(29, 78, 216, 0.92), rgba(15, 118, 110, 0.92));
  color: #fff;
}

.summary-card p,
.summary-card span {
  margin: 0;
  color: inherit;
}

.summary-card p {
  font-size: 0.92rem;
  opacity: 0.9;
}

.summary-card strong {
  display: block;
  margin: 12px 0 10px;
  font-size: 1.5rem;
  line-height: 1.2;
}

.section-block {
  padding: 26px;
}

.section-heading {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 22px;
}

.section-heading p {
  margin: 0 0 8px;
  color: #0f766e;
  font-size: 0.8rem;
  font-weight: 700;
  letter-spacing: 0.16em;
  text-transform: uppercase;
}

.section-heading span {
  color: #64748b;
}

.module-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 18px;
}

.module-card,
.insight-item {
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.8);
  text-align: left;
  transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;
}

.module-card {
  padding: 22px;
  cursor: pointer;
}

.module-card:hover,
.module-card:focus-visible,
.insight-item:hover,
.insight-item:focus-visible {
  transform: translateY(-4px);
  border-color: rgba(29, 78, 216, 0.22);
  box-shadow: 0 18px 36px rgba(15, 23, 42, 0.08);
  outline: none;
}

.module-card__top,
.module-card__footer,
.insight-item {
  display: flex;
  align-items: center;
}

.module-card__top,
.module-card__footer {
  justify-content: space-between;
}

.module-card__icon,
.insight-item__icon {
  width: 48px;
  height: 48px;
  display: grid;
  place-items: center;
  border-radius: 16px;
  background: color-mix(in srgb, var(--accent) 14%, white);
  color: var(--accent);
  font-size: 1.2rem;
}

.module-card__status {
  padding: 7px 12px;
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.06);
  color: #334155;
  font-size: 0.82rem;
  font-weight: 700;
}

.module-card h4 {
  margin-top: 18px;
  font-size: 1.05rem;
}

.module-card p,
.journey-item p,
.insight-item p {
  margin: 10px 0 0;
  color: #475569;
  line-height: 1.7;
}

.module-card__footer {
  margin-top: 18px;
  color: #1d4ed8;
  font-weight: 600;
}

.journey-panel,
.insight-panel {
  min-width: 0;
}

.journey-item {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 14px;
  align-items: flex-start;
  padding: 18px 0;
  border-top: 1px solid rgba(148, 163, 184, 0.14);
}

.journey-item:first-child {
  border-top: none;
  padding-top: 0;
}

.journey-item__index {
  width: 44px;
  height: 44px;
  display: grid;
  place-items: center;
  border-radius: 14px;
  background: rgba(29, 78, 216, 0.1);
  color: #1d4ed8;
  font-weight: 800;
}

.insight-list {
  grid-template-columns: 1fr;
}

.insight-item {
  width: 100%;
  gap: 16px;
  padding: 18px;
  cursor: pointer;
}

.insight-item__icon {
  flex: 0 0 auto;
}

@media (max-width: 1200px) {
  .module-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 900px) {
  .hero-topbar,
  .hero-content,
  .section-block--split {
    grid-template-columns: 1fr;
  }

  .hero-actions,
  .section-heading {
    justify-content: flex-start;
  }
}

@media (max-width: 640px) {
  .hero-panel,
  .section-block {
    padding: 18px;
    border-radius: 22px;
  }

  .hero-brand {
    align-items: flex-start;
  }

  .hero-brand__mark {
    width: 60px;
    height: 60px;
    border-radius: 18px;
  }

  .summary-grid,
  .module-grid {
    grid-template-columns: 1fr;
  }

  .ghost-pill {
    width: 100%;
    justify-content: center;
  }
}
</style>
