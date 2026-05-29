<template>
  <div class="login-shell">
    <section class="login-showcase">
      <div class="login-showcase__topbar">
        <div class="brand-lockup">
          <div class="brand-lockup__mark">
            <img :src="logoImage" alt="TestHub" />
          </div>
          <div>
            <strong>TestHub</strong>
            <span>{{ heroCopy.subtitle }}</span>
          </div>
        </div>

        <el-dropdown @command="handleLanguageChange">
          <button class="language-pill" type="button">
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
      </div>

      <div class="login-showcase__content">
        <span class="showcase-badge">{{ heroCopy.badge }}</span>
        <h1>{{ heroCopy.title }}</h1>
        <p>{{ heroCopy.description }}</p>

        <div class="showcase-metrics">
          <div v-for="metric in heroMetrics" :key="metric.label" class="metric-card">
            <span>{{ metric.label }}</span>
            <strong>{{ metric.value }}</strong>
            <p>{{ metric.description }}</p>
          </div>
        </div>

        <div class="showcase-features">
          <article v-for="feature in features" :key="feature.title" class="feature-card">
            <div class="feature-card__icon" :style="{ '--accent': feature.color }">
              <el-icon><component :is="feature.icon" /></el-icon>
            </div>
            <div>
              <h3>{{ feature.title }}</h3>
              <p>{{ feature.description }}</p>
            </div>
          </article>
        </div>

        <div class="showcase-tags">
          <span v-for="tag in heroTags" :key="tag">{{ tag }}</span>
        </div>
      </div>
    </section>

    <section class="login-panel">
      <div class="login-panel__card">
        <div class="form-header">
          <span class="form-header__eyebrow">{{ heroCopy.formEyebrow }}</span>
          <h2>{{ $t('auth.welcomeBack') }}</h2>
          <p>{{ $t('auth.loginSubtitle') }}</p>
        </div>

        <div class="mode-tabs">
          <button
            type="button"
            class="mode-tab"
            :class="{ active: loginMode === 'password' }"
            @click="loginMode = 'password'"
          >
            {{ modeText.password }}
          </button>
          <button
            type="button"
            class="mode-tab"
            :class="{ active: loginMode === 'sms' }"
            @click="loginMode = 'sms'; refreshCaptcha()"
          >
            {{ modeText.sms }}
          </button>
        </div>

        <el-form
          ref="formRef"
          :model="form"
          :rules="rules"
          class="login-form"
          @submit.prevent="handleLogin"
        >
          <template v-if="loginMode === 'password'">
            <el-form-item prop="username">
              <el-input
                v-model="form.username"
                :placeholder="$t('auth.usernamePlaceholder')"
                size="large"
                :prefix-icon="User"
              />
            </el-form-item>

            <el-form-item prop="password">
              <el-input
                v-model="form.password"
                type="password"
                :placeholder="$t('auth.passwordPlaceholder')"
                size="large"
                :prefix-icon="Lock"
                show-password
                @keyup.enter="handleLogin"
              />
            </el-form-item>
          </template>

          <template v-else>
            <el-form-item prop="phone">
              <el-input
                v-model="form.phone"
                :placeholder="modeText.phonePlaceholder"
                size="large"
                :prefix-icon="Phone"
                maxlength="11"
              />
            </el-form-item>

            <el-row :gutter="12">
              <el-col :span="14">
                <el-form-item prop="captcha_code">
                  <el-input
                    v-model="form.captcha_code"
                    :placeholder="modeText.captchaPlaceholder"
                    size="large"
                    maxlength="4"
                  />
                </el-form-item>
              </el-col>
              <el-col :span="10">
                <img
                  :src="captchaImage"
                  :alt="modeText.captchaAlt"
                  class="captcha-img"
                  @click="refreshCaptcha"
                />
              </el-col>
            </el-row>

            <el-form-item prop="verify_code">
              <el-input
                v-model="form.verify_code"
                :placeholder="modeText.smsPlaceholder"
                size="large"
                maxlength="6"
              >
                <template #append>
                  <el-button
                    :disabled="smsCountdown > 0 || !form.phone || !form.captcha_code"
                    :loading="sendingSms"
                    @click="sendVerifyCode"
                  >
                    {{ smsCountdown > 0 ? `${smsCountdown}s` : modeText.sendCode }}
                  </el-button>
                </template>
              </el-input>
            </el-form-item>
          </template>

          <el-form-item>
            <el-button type="primary" size="large" :loading="loading" class="login-button" @click="handleLogin">
              {{ loading ? $t('auth.loggingIn') : $t('auth.login') }}
            </el-button>
          </el-form-item>
        </el-form>

        <div class="form-footer">
          <router-link to="/register" class="register-link">
            {{ $t('auth.noAccount') }}<span>{{ $t('auth.signUpNow') }}</span>
          </router-link>
          <p>{{ $t('auth.copyright') }}</p>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import {
  User,
  Lock,
  Phone,
  MagicStick,
  TrendCharts,
  Connection,
  DataLine,
  ArrowDown
} from '@element-plus/icons-vue'
import { useUserStore } from '@/stores/user'
import { useAppStore } from '@/stores/app'
import api from '@/utils/api'
import logoImage from '@/assets/images/logo_home.png'

const router = useRouter()
const userStore = useUserStore()
const appStore = useAppStore()
const { t } = useI18n()

const currentLanguage = computed(() => appStore.language)
const isChinese = computed(() => currentLanguage.value === 'zh-cn')
const currentLanguageLabel = computed(() => (isChinese.value ? '简体中文' : 'English'))

const formRef = ref()
const loading = ref(false)
const loginMode = ref('password')
const captchaImage = ref('')
const captchaToken = ref('')
const sendingSms = ref(false)
const smsCountdown = ref(0)
let countdownTimer = null

const form = reactive({
  username: '',
  password: '',
  phone: '',
  captcha_code: '',
  verify_code: '',
  verify_code_token: ''
})

const heroCopy = computed(() =>
  isChinese.value
    ? {
        subtitle: 'AI 一体化测试平台',
        badge: '统一测试入口',
        title: '从需求到执行结果，把测试链路放进同一个工作台。',
        description:
          'TestHub 把 AI 用例生成、接口测试、UI 自动化、APP 自动化和配置中心串成一个完整平台，降低团队切换成本。',
        formEyebrow: 'Sign in'
      }
    : {
        subtitle: 'AI Testing Platform',
        badge: 'Unified testing entry',
        title: 'Run the whole testing workflow from one operating surface.',
        description:
          'TestHub brings AI case generation, API testing, UI automation, APP automation and configuration into one consistent platform.',
        formEyebrow: 'Sign in'
      }
)

const heroMetrics = computed(() =>
  isChinese.value
    ? [
        { label: '能力域', value: '8', description: '覆盖核心测试模块' },
        { label: '协作入口', value: '1', description: '统一登录与切换入口' },
        { label: '扩展方向', value: '∞', description: '适合继续产品化打磨' }
      ]
    : [
        { label: 'Capability areas', value: '8', description: 'Covering core testing modules' },
        { label: 'Unified entry', value: '1', description: 'One sign-in for the whole platform' },
        { label: 'Expansion room', value: '∞', description: 'A strong base for further productization' }
      ]
)

const features = computed(() => [
  {
    title: t('auth.aiCaseGeneration'),
    description: t('auth.aiCaseGenerationDesc'),
    icon: MagicStick,
    color: '#0f766e'
  },
  {
    title: t('auth.aiIntelligentTesting'),
    description: t('auth.aiIntelligentTestingDesc'),
    icon: TrendCharts,
    color: '#1d4ed8'
  },
  {
    title: t('auth.multiTypeTesting'),
    description: t('auth.multiTypeTestingDesc'),
    icon: Connection,
    color: '#b45309'
  },
  {
    title: t('auth.dataAnalysis'),
    description: t('auth.dataAnalysisDesc'),
    icon: DataLine,
    color: '#334155'
  }
])

const heroTags = computed(() =>
  isChinese.value
    ? ['需求分析', '自动化执行', '调度通知', '报告中心']
    : ['Requirement analysis', 'Automated execution', 'Scheduling', 'Reporting']
)

const modeText = computed(() =>
  isChinese.value
    ? {
        password: '密码登录',
        sms: '短信登录',
        phonePlaceholder: '请输入手机号',
        captchaPlaceholder: '图形验证码',
        captchaAlt: '验证码',
        smsPlaceholder: '短信验证码',
        sendCode: '发送验证码',
        phoneRequired: '请输入手机号',
        phoneInvalid: '手机号格式不正确',
        captchaRequired: '请输入图形验证码',
        codeRequired: '请输入短信验证码',
        sendPhoneFirst: '请先输入手机号',
        sendCaptchaFirst: '请先输入图形验证码',
        codeSent: '验证码已发送',
        codeSendFailed: '验证码发送失败'
      }
    : {
        password: 'Password login',
        sms: 'SMS login',
        phonePlaceholder: 'Enter phone number',
        captchaPlaceholder: 'Captcha',
        captchaAlt: 'Captcha image',
        smsPlaceholder: 'SMS code',
        sendCode: 'Send code',
        phoneRequired: 'Please enter phone number',
        phoneInvalid: 'Invalid phone number format',
        captchaRequired: 'Please enter captcha',
        codeRequired: 'Please enter SMS code',
        sendPhoneFirst: 'Enter phone number first',
        sendCaptchaFirst: 'Enter captcha first',
        codeSent: 'Verification code sent',
        codeSendFailed: 'Failed to send verification code'
      }
)

const validatePhone = (rule, value, callback) => {
  if (!value) {
    callback(new Error(modeText.value.phoneRequired))
  } else if (!/^1[3-9]\d{9}$/.test(value)) {
    callback(new Error(modeText.value.phoneInvalid))
  } else {
    callback()
  }
}

const rules = computed(() => ({
  username: [{ required: true, message: t('auth.usernameRequired'), trigger: 'blur' }],
  password: [
    { required: true, message: t('auth.passwordRequired'), trigger: 'blur' },
    { min: 6, message: t('auth.passwordLength'), trigger: 'blur' }
  ],
  phone: [{ required: true, validator: validatePhone, trigger: 'blur' }],
  captcha_code: [{ required: true, message: modeText.value.captchaRequired, trigger: 'blur' }],
  verify_code: [{ required: true, message: modeText.value.codeRequired, trigger: 'blur' }]
}))

const handleLanguageChange = (lang) => {
  appStore.setLanguage(lang)
}

const refreshCaptcha = async () => {
  try {
    const response = await api.get('/auth/captcha/')
    captchaImage.value = response.data.image
    captchaToken.value = response.data.token
    form.captcha_code = ''
  } catch (error) {
    // Keep silent so login remains usable even if captcha refresh fails.
  }
}

const sendVerifyCode = async () => {
  if (!form.phone) {
    ElMessage.warning(modeText.value.sendPhoneFirst)
    return
  }

  if (!form.captcha_code) {
    ElMessage.warning(modeText.value.sendCaptchaFirst)
    return
  }

  sendingSms.value = true

  try {
    const response = await api.post('/auth/send-register-code/', {
      phone: form.phone,
      captcha_token: captchaToken.value,
      captcha_code: form.captcha_code,
      mode: 'login'
    })

    form.verify_code_token = response.data.verify_code_token
    ElMessage.success(modeText.value.codeSent)

    smsCountdown.value = 60
    countdownTimer = setInterval(() => {
      smsCountdown.value -= 1
      if (smsCountdown.value <= 0) {
        clearInterval(countdownTimer)
        countdownTimer = null
      }
    }, 1000)
  } catch (error) {
    ElMessage.error(error.response?.data?.error || modeText.value.codeSendFailed)
    refreshCaptcha()
  } finally {
    sendingSms.value = false
  }
}

const handleLogin = async () => {
  if (!formRef.value) return

  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  loading.value = true

  try {
    if (loginMode.value === 'sms') {
      await userStore.smsLogin({
        phone: form.phone,
        verify_code: form.verify_code,
        verify_code_token: form.verify_code_token
      })
    } else {
      await userStore.login(form)
    }

    ElMessage.success(t('auth.loginSuccess'))
    await router.replace('/home')
  } catch (error) {
    ElMessage.error(error.response?.data?.error || t('auth.loginFailed'))
    if (loginMode.value === 'sms') {
      refreshCaptcha()
    }
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  if (loginMode.value === 'sms') {
    refreshCaptcha()
  }
})

onUnmounted(() => {
  if (countdownTimer) {
    clearInterval(countdownTimer)
    countdownTimer = null
  }
})
</script>

<style lang="scss" scoped>
.login-shell {
  min-height: 100vh;
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(420px, 0.8fr);
  background:
    radial-gradient(circle at top left, rgba(14, 165, 233, 0.12), transparent 20%),
    linear-gradient(180deg, #f8fafc, #f1f5f9);
}

.login-showcase {
  position: relative;
  overflow: hidden;
  padding: 28px;
  background:
    radial-gradient(circle at top left, rgba(56, 189, 248, 0.18), transparent 24%),
    radial-gradient(circle at bottom right, rgba(15, 118, 110, 0.2), transparent 24%),
    linear-gradient(160deg, #0f172a 0%, #0f3d5e 44%, #115e59 100%);
  color: white;
}

.login-showcase__topbar,
.brand-lockup,
.language-pill,
.feature-card {
  display: flex;
  align-items: center;
}

.login-showcase__topbar {
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 48px;
}

.brand-lockup {
  gap: 14px;

  strong {
    display: block;
    font-size: 2rem;
    line-height: 1;
  }

  span {
    color: rgba(226, 232, 240, 0.76);
  }
}

.brand-lockup__mark {
  width: 62px;
  height: 62px;
  display: grid;
  place-items: center;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.12);
  backdrop-filter: blur(12px);

  img {
    width: 40px;
    height: 40px;
  }
}

.language-pill {
  gap: 10px;
  min-height: 42px;
  padding: 0 14px;
  border: 1px solid rgba(255, 255, 255, 0.16);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.08);
  color: white;
  cursor: pointer;
}

.login-showcase__content {
  max-width: 760px;

  h1 {
    max-width: 720px;
    margin: 0 0 16px;
    font-size: clamp(2.6rem, 4vw, 4.5rem);
    line-height: 1.05;
  }

  p {
    max-width: 660px;
    margin: 0;
    color: rgba(226, 232, 240, 0.84);
    line-height: 1.75;
    font-size: 1rem;
  }
}

.showcase-badge {
  display: inline-flex;
  margin-bottom: 18px;
  padding: 8px 14px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.12);
  color: white;
  font-size: 0.88rem;
  font-weight: 700;
}

.showcase-metrics,
.showcase-features {
  display: grid;
  gap: 16px;
}

.showcase-metrics {
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin: 28px 0;
}

.metric-card,
.feature-card {
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: rgba(255, 255, 255, 0.08);
  backdrop-filter: blur(14px);
}

.metric-card {
  padding: 18px;
  border-radius: 22px;

  span,
  p {
    display: block;
    color: rgba(226, 232, 240, 0.78);
  }

  strong {
    display: block;
    margin: 10px 0 8px;
    font-size: 2rem;
    color: white;
  }
}

.showcase-features {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.feature-card {
  gap: 16px;
  padding: 20px;
  border-radius: 24px;

  h3 {
    margin: 0 0 6px;
    font-size: 1.05rem;
  }

  p {
    color: rgba(226, 232, 240, 0.76);
    font-size: 0.94rem;
  }
}

.feature-card__icon {
  width: 52px;
  height: 52px;
  display: grid;
  place-items: center;
  border-radius: 16px;
  background: color-mix(in srgb, var(--accent) 18%, white);
  color: white;
  font-size: 1.35rem;
  flex-shrink: 0;
}

.showcase-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 24px;

  span {
    padding: 10px 14px;
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.1);
    color: white;
    font-size: 0.88rem;
    font-weight: 600;
  }
}

.login-panel {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 32px;
}

.login-panel__card {
  width: min(460px, 100%);
  padding: 36px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 28px;
  background: rgba(255, 255, 255, 0.92);
  box-shadow: 0 28px 64px rgba(15, 23, 42, 0.1);
}

.form-header {
  margin-bottom: 24px;

  h2 {
    margin: 8px 0 10px;
    font-size: 2rem;
    color: #0f172a;
  }

  p {
    margin: 0;
    color: #64748b;
    line-height: 1.7;
  }
}

.form-header__eyebrow {
  display: inline-flex;
  color: #0f766e;
  font-size: 0.78rem;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.mode-tabs {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  padding: 6px;
  border-radius: 18px;
  background: #eff4f8;
  margin-bottom: 24px;
}

.mode-tab {
  min-height: 42px;
  border: 0;
  border-radius: 14px;
  background: transparent;
  color: #64748b;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;

  &.active {
    background: white;
    color: #0f766e;
    box-shadow: 0 10px 20px rgba(15, 23, 42, 0.08);
  }
}

.login-form {
  :deep(.el-form-item) {
    margin-bottom: 20px;
  }

  :deep(.el-input__wrapper) {
    min-height: 48px;
    box-shadow: 0 0 0 1px rgba(148, 163, 184, 0.35) inset;
  }

  :deep(.el-input__wrapper.is-focus) {
    box-shadow: 0 0 0 1px #0f766e inset;
  }
}

.captcha-img {
  width: 100%;
  height: 48px;
  border-radius: 14px;
  border: 1px solid rgba(148, 163, 184, 0.3);
  object-fit: cover;
  background: #f8fafc;
  cursor: pointer;
}

.login-button {
  width: 100%;
  height: 48px;
  border: 0;
  border-radius: 16px;
  background: linear-gradient(135deg, #0f766e, #1d4ed8);
}

.form-footer {
  margin-top: 24px;
  text-align: center;

  .register-link {
    color: #64748b;
    text-decoration: none;

    span {
      color: #0f766e;
      font-weight: 700;
    }
  }

  p {
    margin: 28px 0 0;
    color: #94a3b8;
    font-size: 0.86rem;
  }
}

@media (max-width: 1180px) {
  .login-shell {
    grid-template-columns: 1fr;
  }

  .showcase-metrics {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 820px) {
  .login-showcase,
  .login-panel {
    padding: 20px;
  }

  .showcase-metrics,
  .showcase-features {
    grid-template-columns: 1fr;
  }

  .login-panel__card {
    padding: 24px;
  }
}

@media (max-width: 640px) {
  .login-showcase__topbar {
    flex-direction: column;
    align-items: flex-start;
  }

  .language-pill {
    width: 100%;
    justify-content: center;
  }

  .login-panel {
    padding-top: 0;
  }

  .login-panel__card {
    width: 100%;
    border-radius: 24px;
  }
}
</style>
