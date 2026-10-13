<template>
  <div class="layout-shell">
    <transition name="fade">
      <div v-if="showMobileNav" class="layout-overlay" @click="closeAside"></div>
    </transition>

    <aside :class="['layout-aside', { 'is-open': showMobileNav }]">
      <button class="layout-logo" type="button" @click="router.push('/home')">
        <div class="layout-logo__mark">
          <img :src="logoImage" alt="TestHub" />
        </div>
        <div class="layout-logo__text">
          <strong>TestHub</strong>
          <span>{{ moduleName || shellCopy.platformName }}</span>
        </div>
      </button>

      <el-scrollbar class="layout-menu-scroll">
        <el-menu
          :default-active="activeMenuPath"
          :default-openeds="openedMenus"
          router
          class="layout-menu"
          @select="handleMenuSelect"
        >
          <template v-for="item in currentMenu" :key="item.index">
            <el-sub-menu v-if="item.children" :index="item.index">
              <template #title>
                <el-icon><component :is="item.icon" /></el-icon>
                <span>{{ item.label }}</span>
              </template>
              <el-menu-item v-for="child in item.children" :key="child.index" :index="child.index">
                {{ child.label }}
              </el-menu-item>
            </el-sub-menu>
            <el-menu-item v-else :index="item.index">
              <el-icon><component :is="item.icon" /></el-icon>
              <span>{{ item.label }}</span>
            </el-menu-item>
          </template>
        </el-menu>
      </el-scrollbar>
    </aside>

    <div class="layout-main">
      <header class="layout-header">
        <div class="layout-header__left">
          <button class="icon-button mobile-only" type="button" @click="toggleAside">
            <el-icon><Operation /></el-icon>
          </button>

          <button class="icon-button" type="button" @click="router.push('/home')">
            <el-icon><House /></el-icon>
          </button>

          <div class="header-title">
            <div class="header-title__meta">
              <span class="module-chip">{{ moduleName || shellCopy.workspace }}</span>
              <span class="header-title__path">{{ breadcrumbTitle }}</span>
            </div>
          </div>
        </div>

        <div class="layout-header__right">
          <el-dropdown @command="handleLanguageChange">
            <button class="header-pill" type="button">
              <span>{{ currentLanguageLabel }}</span>
              <el-icon><ArrowDown /></el-icon>
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="zh-cn" :disabled="appStore.language === 'zh-cn'">
                  简体中文
                </el-dropdown-item>
                <el-dropdown-item command="en" :disabled="appStore.language === 'en'">
                  English
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>

          <el-dropdown @command="handleCommand">
            <button class="header-pill" type="button">
              <el-avatar :size="30" :icon="UserFilled" />
              <span>{{ userStore.user?.username || shellCopy.profile }}</span>
              <el-icon><ArrowDown /></el-icon>
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="profile">{{ shellCopy.profile }}</el-dropdown-item>
                <el-dropdown-item command="logout">{{ shellCopy.logout }}</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </header>

      <main class="layout-content">
        <router-view />
      </main>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useUserStore } from '@/stores/user'
import { useAppStore } from '@/stores/app'
import { ElMessage } from 'element-plus'
import {
  Monitor,
  Folder,
  Document,
  Flag,
  Check,
  Collection,
  VideoPlay,
  DataAnalysis,
  ChatDotRound,
  DocumentCopy,
  Link,
  MagicStick,
  Odometer,
  Timer,
  Setting,
  AlarmClock,
  Bell,
  Aim,
  Edit,
  Cpu,
  ArrowDown,
  Cellphone,
  Connection,
  FolderOpened,
  UserFilled,
  Operation,
  House,
  VideoCamera,
  TrendCharts
} from '@element-plus/icons-vue'
import logoImage from '@/assets/images/logo_home.png'

const router = useRouter()
const route = useRoute()
const { t } = useI18n()
const userStore = useUserStore()
const appStore = useAppStore()

const viewportWidth = ref(typeof window !== 'undefined' ? window.innerWidth : 1440)
const showMobileNav = ref(false)

const isChinese = computed(() => appStore.language === 'zh-cn')
const currentLanguageLabel = computed(() => (isChinese.value ? '简体中文' : 'English'))
const isMobile = computed(() => viewportWidth.value <= 960)

const shellCopy = computed(() =>
  isChinese.value
    ? {
        platformName: '测试平台',
        workspace: '工作台',
        profile: '个人中心',
        logout: '退出登录',
        languageSwitched: '已切换为中文界面',
        defaultHeader: '统一管理平台能力、导航入口和测试流转。'
      }
    : {
        platformName: 'Testing Platform',
        workspace: 'Workspace',
        profile: 'Profile',
        logout: 'Logout',
        languageSwitched: 'Language switched to English',
        defaultHeader: 'Coordinate navigation, platform capabilities and delivery flow.'
      }
)

const moduleKey = computed(() => {
  if (route.path.startsWith('/workspace')) return 'workspace'
  if (route.path.startsWith('/ai-generation')) return 'ai-generation'
  if (route.path.startsWith('/api-testing')) return 'api-testing'
  if (route.path.startsWith('/performance-testing')) return 'performance-testing'
  if (route.path.startsWith('/ui-automation')) return 'ui-automation'
  if (route.path.startsWith('/app-automation')) return 'app-automation'
  if (route.path.startsWith('/ai-intelligent-mode')) return 'ai-intelligent-mode'
  if (route.path.startsWith('/configuration')) return 'configuration'
  if (route.path.startsWith('/data-factory')) return 'data-factory'
  return ''
})

const moduleName = computed(() => {
  const names = {
    'ai-generation': t('modules.aiGeneration'),
    workspace: isChinese.value ? '平台工作台' : 'Platform Workspace',
    'api-testing': t('modules.apiTesting'),
    'performance-testing': isChinese.value ? '性能测试' : 'Performance Testing',
    'ui-automation': t('modules.uiAutomation'),
    'app-automation': isChinese.value ? 'APP 自动化测试' : 'APP Automation Testing',
    'ai-intelligent-mode': t('modules.aiIntelligentMode'),
    configuration: t('modules.configuration'),
    'data-factory': isChinese.value ? '数据工厂' : 'Data Factory'
  }

  return names[moduleKey.value] || ''
})

const menuByModule = computed(() => ({
  workspace: [
    { index: '/workspace/report-center', label: isChinese.value ? '统一报告中心' : 'Unified Reports', icon: DataAnalysis },
    { index: '/workspace/scheduler-center', label: isChinese.value ? '统一调度中心' : 'Unified Scheduler', icon: AlarmClock }
  ],
  'ai-generation': [
    {
      index: 'requirement',
      label: t('menu.intelligentCaseGeneration'),
      icon: MagicStick,
      children: [
        { index: '/ai-generation/requirement-analysis', label: t('menu.aiCaseGeneration') },
        { index: '/ai-generation/generated-testcases', label: t('menu.aiGeneratedTestcases') }
      ]
    },
    { index: '/ai-generation/projects', label: t('menu.projectManagement'), icon: Folder },
    { index: '/ai-generation/testcases', label: t('menu.testCases'), icon: Document },
    { index: '/ai-generation/versions', label: t('menu.versionManagement'), icon: Flag },
    {
      index: 'reviews',
      label: t('menu.reviewManagement'),
      icon: Check,
      children: [
        { index: '/ai-generation/reviews', label: t('menu.reviewList') },
        { index: '/ai-generation/review-templates', label: t('menu.reviewTemplates') }
      ]
    },
    { index: '/ai-generation/executions', label: t('menu.testPlan'), icon: VideoPlay },
    { index: '/ai-generation/reports', label: t('menu.testReport'), icon: DataAnalysis }
  ],
  'api-testing': [
    { index: '/api-testing/dashboard', label: t('menu.dashboard'), icon: Odometer },
    { index: '/api-testing/projects', label: t('menu.projectManagement'), icon: Folder },
    { index: '/api-testing/interfaces', label: t('menu.interfaceManagement'), icon: Link },
    { index: '/api-testing/automation', label: t('menu.automationTesting'), icon: VideoPlay },
    { index: '/api-testing/history', label: t('menu.requestHistory'), icon: Timer },
    { index: '/api-testing/environments', label: t('menu.environmentManagement'), icon: Setting },
    { index: '/api-testing/reports', label: t('menu.testReport'), icon: DataAnalysis },
    { index: '/api-testing/scheduled-tasks', label: t('menu.scheduledTasks'), icon: AlarmClock },
    { index: '/api-testing/notification-logs', label: t('menu.notificationList'), icon: Bell }
  ],
  'performance-testing': [
    { index: '/performance-testing/dashboard', label: isChinese.value ? '概览' : 'Dashboard', icon: Odometer },
    { index: '/performance-testing/projects', label: isChinese.value ? '性能项目' : 'Projects', icon: Folder },
    { index: '/performance-testing/scripts', label: isChinese.value ? '脚本编排' : 'Script Builder', icon: Edit },
    { index: '/performance-testing/executions', label: isChinese.value ? '执行记录' : 'Executions', icon: VideoPlay },
    { index: '/performance-testing/reports', label: isChinese.value ? '性能报告' : 'Reports', icon: TrendCharts }
  ],
  'ui-automation': [
    { index: '/ui-automation/dashboard', label: t('menu.dashboard'), icon: Odometer },
    { index: '/ui-automation/projects', label: t('menu.projectManagement'), icon: Folder },
    { index: '/ui-automation/elements-enhanced', label: t('menu.elementManagement'), icon: Aim },
    { index: '/ui-automation/test-cases', label: t('menu.caseManagement'), icon: Document },
    { index: '/ui-automation/scripts-enhanced', label: t('menu.scriptGeneration'), icon: Edit },
    { index: '/ui-automation/scripts', label: t('menu.scriptList'), icon: DocumentCopy },
    { index: '/ui-automation/suites', label: t('menu.suiteManagement'), icon: Collection },
    { index: '/ui-automation/executions', label: t('menu.executionRecords'), icon: VideoPlay },
    { index: '/ui-automation/reports', label: t('menu.testReport'), icon: DataAnalysis },
    { index: '/ui-automation/scheduled-tasks', label: t('menu.scheduledTasks'), icon: AlarmClock },
    { index: '/ui-automation/notification-logs', label: t('menu.notificationList'), icon: Bell }
  ],
  'app-automation': [
    { index: '/app-automation/dashboard', label: 'Dashboard', icon: Odometer },
    { index: '/app-automation/projects', label: isChinese.value ? '项目管理' : 'Project Management', icon: Folder },
    { index: '/app-automation/devices', label: isChinese.value ? '设备管理' : 'Device Management', icon: Cellphone },
    { index: '/app-automation/packages', label: isChinese.value ? '应用包管理' : 'Package Management', icon: Collection },
    { index: '/app-automation/elements', label: isChinese.value ? '元素管理' : 'Element Management', icon: Aim },
    { index: '/app-automation/scene-builder', label: isChinese.value ? '场景编排' : 'Scene Builder', icon: Connection },
    { index: '/app-automation/test-cases', label: isChinese.value ? '测试用例' : 'Test Cases', icon: Document },
    { index: '/app-automation/test-suites', label: isChinese.value ? '测试套件' : 'Test Suites', icon: FolderOpened },
    { index: '/app-automation/executions', label: isChinese.value ? '执行记录' : 'Execution Records', icon: VideoPlay },
    { index: '/app-automation/reports', label: isChinese.value ? '测试报告' : 'Test Reports', icon: DataAnalysis },
    { index: '/app-automation/scheduled-tasks', label: isChinese.value ? '定时任务' : 'Scheduled Tasks', icon: AlarmClock },
    { index: '/app-automation/notification-logs', label: isChinese.value ? '通知日志' : 'Notification Logs', icon: Bell }
  ],
  'ai-intelligent-mode': [
    { index: '/ai-intelligent-mode/testing', label: t('menu.aiIntelligentTesting'), icon: VideoPlay },
    { index: '/ai-intelligent-mode/cases', label: t('menu.aiCaseManagement'), icon: Document },
    { index: '/ai-intelligent-mode/execution-records', label: t('menu.aiExecutionRecords'), icon: Timer }
  ],
  configuration: [
    {
      index: 'ai-case-generation',
      label: t('menu.aiCaseGenerationConfig'),
      icon: MagicStick,
      children: [
        { index: '/configuration/ai-model', label: t('menu.aiModelConfig') },
        { index: '/configuration/prompt-config', label: t('menu.promptConfig') },
        { index: '/configuration/generation-config', label: t('menu.generationConfig') }
      ]
    },
    { index: '/configuration/ui-env', label: t('menu.uiEnvConfig'), icon: Monitor },
    { index: '/configuration/app-env', label: isChinese.value ? 'APP 环境配置' : 'APP Environment', icon: Cellphone },
    { index: '/configuration/ai-mode', label: t('menu.aiModeConfig'), icon: Cpu },
    { index: '/configuration/scheduled-task', label: t('menu.scheduledTaskConfig'), icon: Timer },
    { index: '/configuration/ocr', label: isChinese.value ? 'OCR 配置' : 'OCR Configuration', icon: Aim },
    { index: '/configuration/dify', label: t('menu.difyConfig'), icon: ChatDotRound }
  ],
  'data-factory': []
}))

const currentMenu = computed(() => menuByModule.value[moduleKey.value] || [])
const openedMenus = computed(() => currentMenu.value.filter(item => item.children).map(item => item.index))

const activeMenuPath = computed(() => {
  const items = flattenMenu(currentMenu.value)
  const exactMatch = items.find(item => item.index === route.path)
  if (exactMatch) return exactMatch.index

  const partialMatch = items.find(item => route.path.startsWith(item.index))
  return partialMatch?.index || route.path
})

const breadcrumbTitle = computed(() => {
  const exactMatch = flattenMenu(currentMenu.value).find(item => item.index === route.path)
  if (exactMatch) return exactMatch.label

  const routeName = route.name ? String(route.name) : ''
  return route.meta.title || routeName || route.path
})

const updateViewportWidth = () => {
  viewportWidth.value = window.innerWidth
  if (!isMobile.value) {
    showMobileNav.value = false
  }
}

const closeAside = () => {
  showMobileNav.value = false
}

const toggleAside = () => {
  showMobileNav.value = !showMobileNav.value
}

const handleMenuSelect = () => {
  if (isMobile.value) {
    closeAside()
  }
}

const handleLanguageChange = (lang) => {
  appStore.setLanguage(lang)
  ElMessage.success(lang === 'zh-cn' ? '已切换为中文界面' : 'Language switched to English')
}

const handleCommand = async (command) => {
  if (command === 'logout') {
    await userStore.logout()
    return
  }

  if (command === 'profile') {
    router.push('/ai-generation/profile')
  }
}

watch(
  () => route.fullPath,
  () => {
    closeAside()
  }
)

onMounted(() => {
  window.addEventListener('resize', updateViewportWidth)
})

onUnmounted(() => {
  window.removeEventListener('resize', updateViewportWidth)
})

function flattenMenu(items) {
  return items.flatMap(item => (item.children ? item.children : [item]))
}
</script>

<style lang="scss" scoped>
.layout-shell {
  display: grid;
  grid-template-columns: 240px minmax(0, 1fr);
  min-height: 100vh;
  background: #f5f7fa;
}

.layout-overlay {
  position: fixed;
  inset: 0;
  z-index: 40;
  background: rgba(15, 23, 42, 0.48);
  backdrop-filter: blur(2px);
}

.layout-aside {
  position: sticky;
  top: 0;
  z-index: 50;
  display: flex;
  flex-direction: column;
  gap: 10px;
  height: 100vh;
  padding: 14px 12px;
  border-right: 1px solid #1f2937;
  background: #111827;
}

.layout-logo {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 8px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: white;
  text-align: left;
  cursor: pointer;
}

.layout-logo__mark {
  width: 38px;
  height: 38px;
  display: grid;
  place-items: center;
  border-radius: 6px;
  background: #1f2937;

  img {
    width: 28px;
    height: 28px;
  }
}

.layout-logo__text {
  display: flex;
  flex-direction: column;
  gap: 4px;

  strong {
    font-size: 1.1rem;
  }

  span {
    color: rgba(226, 232, 240, 0.78);
    font-size: 0.82rem;
  }
}

.layout-menu-scroll {
  flex: 1;
  min-height: 0;
}

.layout-menu {
  border: 0;
  background: transparent;

  :deep(.el-menu),
  :deep(.el-menu-item),
  :deep(.el-sub-menu__title) {
    background: transparent;
  }

  :deep(.el-menu-item),
  :deep(.el-sub-menu__title) {
    height: 40px;
    margin-bottom: 3px;
    border-radius: 6px;
    color: rgba(226, 232, 240, 0.84);
  }

  :deep(.el-menu-item:hover),
  :deep(.el-sub-menu__title:hover) {
    color: white;
    background: rgba(255, 255, 255, 0.08);
  }

  :deep(.el-menu-item.is-active) {
    color: white;
    background: #2563eb;
  }
}

.layout-main {
  min-width: 0;
  display: flex;
  flex-direction: column;
  min-height: 100vh;
}

.layout-header {
  position: sticky;
  top: 0;
  z-index: 20;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  min-height: 56px;
  padding: 0 20px;
  border-bottom: 1px solid #dfe3e8;
  background: #ffffff;
}

.layout-header__left,
.layout-header__right,
.header-title__meta,
.header-pill,
.icon-button {
  display: flex;
  align-items: center;
}

.layout-header__left {
  gap: 12px;
  min-width: 0;
}

.layout-header__right {
  gap: 12px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.icon-button,
.header-pill {
  min-height: 34px;
  border: 1px solid #d8dde5;
  background: #ffffff;
  color: #0f172a;
  cursor: pointer;
}

.icon-button {
  width: 34px;
  justify-content: center;
  border-radius: 6px;
}

.header-pill {
  gap: 10px;
  padding: 0 14px;
  border-radius: 6px;
}

.header-title {
  min-width: 0;

  strong {
    display: block;
    margin-top: 6px;
    color: #334155;
    font-size: 0.96rem;
    font-weight: 600;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
}

.header-title__meta {
  gap: 10px;
  min-width: 0;
}

.module-chip {
  flex-shrink: 0;
  padding: 4px 8px;
  border-radius: 4px;
  background: #eef2ff;
  color: #3730a3;
  font-size: 0.78rem;
  font-weight: 700;
}

.header-title__path {
  color: #0f172a;
  font-weight: 700;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.layout-content {
  flex: 1;
  min-width: 0;
  padding: 20px;
}

.mobile-only {
  display: none;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

@media (max-width: 960px) {
  .layout-shell {
    grid-template-columns: 1fr;
  }

  .layout-aside {
    position: fixed;
    top: 0;
    left: 0;
    width: min(84vw, 320px);
    transform: translateX(-110%);
    transition: transform 0.24s ease;
  }

  .layout-aside.is-open {
    transform: translateX(0);
  }

  .layout-header {
    padding: 16px;
  }

  .layout-content {
    padding: 16px;
  }

  .mobile-only {
    display: inline-flex;
  }
}

@media (max-width: 640px) {
  .layout-header {
    flex-direction: column;
    align-items: flex-start;
  }

  .layout-header__left,
  .layout-header__right {
    width: 100%;
  }

  .layout-header__right {
    justify-content: space-between;
  }

  .header-pill {
    flex: 1;
    justify-content: center;
  }

  .layout-content {
    padding: 12px;
  }
}
</style>
