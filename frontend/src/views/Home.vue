<template>
  <div class="home-page">
    <header class="home-header">
      <div class="brand-block">
        <img :src="logoImage" alt="TestHub" />
        <div>
          <h1>TestHub</h1>
          <p>{{ copy.subtitle }}</p>
        </div>
      </div>

      <div class="header-actions">
        <el-dropdown @command="handleLanguageChange">
          <button class="toolbar-button" type="button">
            {{ isChinese ? '简体中文' : 'English' }}
            <el-icon><ArrowDown /></el-icon>
          </button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="zh-cn" :disabled="isChinese">简体中文</el-dropdown-item>
              <el-dropdown-item command="en" :disabled="!isChinese">English</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>

        <el-dropdown @command="handleCommand">
          <button class="toolbar-button" type="button">
            <el-icon><User /></el-icon>
            <span>{{ userStore.user?.username || copy.user }}</span>
            <el-icon><ArrowDown /></el-icon>
          </button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="logout">{{ copy.logout }}</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </header>

    <main class="home-content">
      <section class="section-heading">
        <div>
          <h2>{{ copy.title }}</h2>
          <p>{{ copy.description }}</p>
        </div>
      </section>

      <section class="module-grid" aria-label="TestHub modules">
        <button
          v-for="module in modules"
          :key="module.route"
          class="module-entry"
          type="button"
          @click="navigateTo(module.route)"
        >
          <span class="module-icon" :style="{ color: module.color }">
            <el-icon><component :is="module.icon" /></el-icon>
          </span>
          <span class="module-copy">
            <strong>{{ module.title }}</strong>
            <small>{{ module.description }}</small>
          </span>
          <el-icon class="module-arrow"><ArrowRight /></el-icon>
        </button>
      </section>
    </main>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  AlarmClock,
  ArrowDown,
  ArrowRight,
  Cellphone,
  Cpu,
  DataAnalysis,
  DocumentChecked,
  Link,
  MagicStick,
  Monitor,
  Setting,
  TrendCharts,
  User
} from '@element-plus/icons-vue'
import { useAppStore } from '@/stores/app'
import { useUserStore } from '@/stores/user'
import logoImage from '@/assets/images/logo_home.png'

const router = useRouter()
const appStore = useAppStore()
const userStore = useUserStore()
const isChinese = computed(() => appStore.language === 'zh-cn')

const copy = computed(() => isChinese.value
  ? {
      subtitle: '智能测试管理平台',
      title: '功能中心',
      description: '直接进入测试设计、执行、报告和配置模块。',
      user: '用户',
      logout: '退出登录',
      logoutTitle: '退出登录',
      logoutConfirm: '确定退出当前账号吗？',
      confirm: '退出',
      cancel: '取消',
      logoutSuccess: '已退出登录'
    }
  : {
      subtitle: 'Intelligent Test Management',
      title: 'Modules',
      description: 'Open test design, execution, reporting and configuration directly.',
      user: 'User',
      logout: 'Logout',
      logoutTitle: 'Logout',
      logoutConfirm: 'Log out of the current account?',
      confirm: 'Logout',
      cancel: 'Cancel',
      logoutSuccess: 'Logged out'
    })

const modules = computed(() => isChinese.value
  ? [
      { title: 'AI 用例生成', description: '需求分析、用例生成与评审', route: '/ai-generation/requirement-analysis', icon: MagicStick, color: '#2563eb' },
      { title: 'AI 智能测试', description: 'AI 用例执行、录制与报告', route: '/ai-intelligent-mode/cases', icon: Cpu, color: '#7c3aed' },
      { title: '接口测试', description: '接口管理、调试、套件与定时任务', route: '/api-testing/interfaces', icon: Link, color: '#0891b2' },
      { title: '性能测试', description: 'JMeter 脚本、执行与性能报告', route: '/performance-testing/dashboard', icon: TrendCharts, color: '#9333ea' },
      { title: 'UI 自动化', description: '元素、用例、脚本、套件与执行', route: '/ui-automation/test-cases', icon: Monitor, color: '#0f766e' },
      { title: 'APP 自动化', description: '设备、元素、场景与执行记录', route: '/app-automation/test-cases', icon: Cellphone, color: '#b45309' },
      { title: '数据工厂', description: '测试数据与常用数据处理工具', route: '/data-factory', icon: DataAnalysis, color: '#475569' },
      { title: '报告中心', description: '集中查看各类型测试报告', route: '/workspace/report-center', icon: DocumentChecked, color: '#be123c' },
      { title: '调度中心', description: '定时任务和执行计划', route: '/workspace/scheduler-center', icon: AlarmClock, color: '#c2410c' },
      { title: '配置中心', description: '模型、环境和通知配置', route: '/configuration/ai-model', icon: Setting, color: '#334155' }
    ]
  : [
      { title: 'AI Case Generation', description: 'Requirements, generation and review', route: '/ai-generation/requirement-analysis', icon: MagicStick, color: '#2563eb' },
      { title: 'AI Testing', description: 'AI execution, recording and reports', route: '/ai-intelligent-mode/cases', icon: Cpu, color: '#7c3aed' },
      { title: 'API Testing', description: 'API management, debugging and schedules', route: '/api-testing/interfaces', icon: Link, color: '#0891b2' },
      { title: 'Performance Testing', description: 'JMeter scripts, executions and reports', route: '/performance-testing/dashboard', icon: TrendCharts, color: '#9333ea' },
      { title: 'UI Automation', description: 'Elements, cases, scripts and executions', route: '/ui-automation/test-cases', icon: Monitor, color: '#0f766e' },
      { title: 'APP Automation', description: 'Devices, elements, scenarios and runs', route: '/app-automation/test-cases', icon: Cellphone, color: '#b45309' },
      { title: 'Data Factory', description: 'Test data and data processing tools', route: '/data-factory', icon: DataAnalysis, color: '#475569' },
      { title: 'Reports', description: 'Review reports across test modules', route: '/workspace/report-center', icon: DocumentChecked, color: '#be123c' },
      { title: 'Schedules', description: 'Scheduled jobs and execution plans', route: '/workspace/scheduler-center', icon: AlarmClock, color: '#c2410c' },
      { title: 'Configuration', description: 'Models, environments and notifications', route: '/configuration/ai-model', icon: Setting, color: '#334155' }
    ])

const navigateTo = (route) => router.push(route)
const handleLanguageChange = (language) => appStore.setLanguage(language)

const handleCommand = (command) => {
  if (command !== 'logout') return
  ElMessageBox.confirm(copy.value.logoutConfirm, copy.value.logoutTitle, {
    confirmButtonText: copy.value.confirm,
    cancelButtonText: copy.value.cancel,
    type: 'warning'
  }).then(async () => {
    await userStore.logout()
    ElMessage.success(copy.value.logoutSuccess)
  }).catch(() => {})
}
</script>

<style scoped>
.home-page {
  min-height: 100vh;
  background: #f5f7fa;
  color: #172033;
}

.home-header {
  min-height: 68px;
  padding: 0 28px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  background: #ffffff;
  border-bottom: 1px solid #dfe3e8;
}

.brand-block,
.header-actions,
.toolbar-button,
.module-entry {
  display: flex;
  align-items: center;
}

.brand-block {
  gap: 12px;
}

.brand-block img {
  width: 36px;
  height: 36px;
  object-fit: contain;
}

.brand-block h1,
.section-heading h2 {
  margin: 0;
  letter-spacing: 0;
}

.brand-block h1 {
  font-size: 20px;
}

.brand-block p,
.section-heading p {
  margin: 3px 0 0;
  color: #667085;
  font-size: 13px;
}

.header-actions {
  gap: 8px;
}

.toolbar-button {
  gap: 7px;
  min-height: 36px;
  padding: 0 10px;
  border: 1px solid #d8dde5;
  border-radius: 6px;
  background: #ffffff;
  color: #344054;
  cursor: pointer;
}

.toolbar-button:hover {
  background: #f8fafc;
  border-color: #b9c1cc;
}

.home-content {
  width: min(1180px, calc(100% - 40px));
  margin: 0 auto;
  padding: 32px 0 48px;
}

.section-heading {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  margin-bottom: 18px;
}

.section-heading h2 {
  font-size: 22px;
}

.module-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  border-top: 1px solid #dfe3e8;
  border-left: 1px solid #dfe3e8;
  background: #ffffff;
}

.module-entry {
  min-width: 0;
  min-height: 92px;
  padding: 16px;
  gap: 13px;
  text-align: left;
  background: #ffffff;
  border: 0;
  border-right: 1px solid #dfe3e8;
  border-bottom: 1px solid #dfe3e8;
  cursor: pointer;
}

.module-entry:hover {
  background: #f8fafc;
}

.module-entry:focus-visible {
  outline: 2px solid #2563eb;
  outline-offset: -2px;
}

.module-icon {
  flex: 0 0 36px;
  width: 36px;
  height: 36px;
  display: grid;
  place-items: center;
  background: #f1f5f9;
  border-radius: 6px;
  font-size: 20px;
}

.module-copy {
  min-width: 0;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.module-copy strong {
  font-size: 15px;
  font-weight: 600;
}

.module-copy small {
  color: #667085;
  font-size: 12px;
  line-height: 1.45;
}

.module-arrow {
  flex: 0 0 auto;
  color: #98a2b3;
}

@media (max-width: 900px) {
  .module-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 620px) {
  .home-header {
    padding: 12px 16px;
    align-items: flex-start;
  }

  .brand-block p,
  .toolbar-button span {
    display: none;
  }

  .home-content {
    width: min(100% - 24px, 1180px);
    padding-top: 24px;
  }

  .module-grid {
    grid-template-columns: 1fr;
  }
}
</style>
