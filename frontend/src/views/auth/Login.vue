<template>
  <div class="login-shell">
    <header class="login-header">
      <div class="brand-lockup">
        <img :src="logoImage" alt="TestHub" />
        <div>
          <strong>TestHub</strong>
          <span>{{ heroCopy.subtitle }}</span>
        </div>
      </div>

      <el-dropdown @command="handleLanguageChange">
        <button class="language-button" type="button">
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
    </header>

    <main class="login-main">
      <section class="login-card">
        <div class="form-header">
          <h1>{{ $t('auth.welcomeBack') }}</h1>
          <p>{{ $t('auth.loginSubtitle') }}</p>
        </div>

        <el-form
          ref="formRef"
          :model="form"
          :rules="rules"
          class="login-form"
          @submit.prevent="handleLogin"
        >
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
      </section>
    </main>
  </div>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import {
  User,
  Lock,
  ArrowDown
} from '@element-plus/icons-vue'
import { useUserStore } from '@/stores/user'
import { useAppStore } from '@/stores/app'
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
const form = reactive({
  username: '',
  password: ''
})

const heroCopy = computed(() =>
  isChinese.value
    ? {
        subtitle: '测试管理平台'
      }
    : {
        subtitle: 'Testing Platform'
      }
)

const rules = computed(() => ({
  username: [{ required: true, message: t('auth.usernameRequired'), trigger: 'blur' }],
  password: [
    { required: true, message: t('auth.passwordRequired'), trigger: 'blur' },
    { min: 6, message: t('auth.passwordLength'), trigger: 'blur' }
  ]
}))

const handleLanguageChange = (lang) => {
  appStore.setLanguage(lang)
}

const handleLogin = async () => {
  if (!formRef.value) return

  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  loading.value = true

  try {
    await userStore.login({
      username: form.username.trim(),
      password: form.password
    })

    ElMessage.success(t('auth.loginSuccess'))
    await router.replace('/home')
  } catch (error) {
    ElMessage.error(error.response?.data?.error || t('auth.loginFailed'))
  } finally {
    loading.value = false
  }
}

</script>

<style lang="scss" scoped>
.login-shell {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background: #f5f7fa;
  color: #172033;
}

.login-header,
.brand-lockup,
.language-button {
  display: flex;
  align-items: center;
}

.login-header {
  min-height: 64px;
  padding: 0 28px;
  justify-content: space-between;
  gap: 16px;
  border-bottom: 1px solid #dfe3e8;
  background: #ffffff;
}

.brand-lockup {
  gap: 10px;

  img {
    width: 34px;
    height: 34px;
    object-fit: contain;
  }

  strong {
    display: block;
    font-size: 18px;
    line-height: 1.2;
  }

  span {
    color: #667085;
    font-size: 12px;
  }
}

.language-button {
  min-height: 36px;
  padding: 0 10px;
  gap: 7px;
  border: 1px solid #d8dde5;
  border-radius: 6px;
  background: #ffffff;
  color: #344054;
  cursor: pointer;
}

.login-main {
  flex: 1;
  display: grid;
  place-items: center;
  padding: 32px 20px;
}

.login-card {
  width: min(420px, 100%);
  padding: 30px;
  border: 1px solid #dfe3e8;
  border-radius: 8px;
  background: #ffffff;
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.06);
}

.form-header {
  margin-bottom: 24px;

  h1 {
    margin: 0 0 8px;
    color: #172033;
    font-size: 24px;
    letter-spacing: 0;
  }

  p {
    margin: 0;
    color: #667085;
    line-height: 1.6;
  }
}

.mode-tabs {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 4px;
  padding: 4px;
  margin-bottom: 24px;
  border-radius: 6px;
  background: #f1f3f5;
}

.mode-tab {
  min-height: 38px;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: #667085;
  font-weight: 600;
  cursor: pointer;

  &.active {
    background: #ffffff;
    color: #2563eb;
  }
}

.login-form {
  :deep(.el-form-item) {
    margin-bottom: 20px;
  }

  :deep(.el-input__wrapper) {
    min-height: 46px;
  }
}

.captcha-img {
  width: 100%;
  height: 46px;
  border: 1px solid #d8dde5;
  border-radius: 4px;
  object-fit: cover;
  background: #f8fafc;
  cursor: pointer;
}

.login-button {
  width: 100%;
  height: 46px;
  border-radius: 4px;
  background: #2563eb;
}

.form-footer {
  margin-top: 20px;
  text-align: center;

  .register-link {
    color: #667085;
    text-decoration: none;

    span {
      margin-left: 4px;
      color: #2563eb;
      font-weight: 600;
    }
  }

  p {
    margin: 24px 0 0;
    color: #98a2b3;
    font-size: 12px;
  }
}

@media (max-width: 640px) {
  .login-header {
    padding: 0 16px;
  }

  .login-main {
    padding: 20px 12px;
  }

  .login-card {
    padding: 24px 20px;
  }
}
</style>
