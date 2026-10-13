from .views import AIAssertionView, AITestCaseExecutionView
from .views.speech_views import SpeechTranscribeView, SpeechParseView, SpeechElementLocateView
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from rest_framework.routers import DefaultRouter
from .views import (
    RecordingSessionViewSet,
    UiProjectViewSet,
    LocatorStrategyViewSet,
    ElementGroupViewSet,
    ElementViewSet,
    TestScriptViewSet,
    PageObjectViewSet,
    ScriptStepViewSet,
    TestSuiteViewSet,
    TestExecutionViewSet,
    ScreenshotViewSet,
    TestCaseViewSet,
    TestCaseStepViewSet,
    TestCaseExecutionViewSet,
    UiScheduledTaskViewSet,
    AIExecutionRecordViewSet,
    AICaseCategoryViewSet,
    DesktopAppProfileViewSet,
    AICaseViewSet,
    UiNotificationLogViewSet,
    OperationRecordViewSet,
    UiDashboardViewSet,
    SetupTemplateViewSet
)
from .views_config import EnvironmentConfigViewSet, AIIntelligentModeConfigViewSet

router = DefaultRouter()
router.register(r'dashboard', UiDashboardViewSet, basename='dashboard')
router.register(r'projects', UiProjectViewSet)
router.register(r'locator-strategies', LocatorStrategyViewSet)
router.register(r'element-groups', ElementGroupViewSet)
router.register(r'elements', ElementViewSet)
router.register(r'test-scripts', TestScriptViewSet)
router.register(r'page-objects', PageObjectViewSet)
router.register(r'steps', ScriptStepViewSet)
router.register(r'test-suites', TestSuiteViewSet)
router.register(r'test-executions', TestExecutionViewSet)
router.register(r'screenshots', ScreenshotViewSet)
router.register(r'test-cases', TestCaseViewSet)
router.register(r'test-case-steps', TestCaseStepViewSet)
router.register(r'test-case-executions', TestCaseExecutionViewSet)
router.register(r'scheduled-tasks', UiScheduledTaskViewSet)
router.register(r'ai-execution-records', AIExecutionRecordViewSet)
router.register(r'ai-case-categories', AICaseCategoryViewSet, basename='ai-case-categories')
router.register(r'desktop-app-profiles', DesktopAppProfileViewSet, basename='desktop-app-profiles')
router.register(r'ai-cases', AICaseViewSet, basename='ai-cases')
router.register(r'ai-case-generation', AICaseViewSet, basename='ai-case-generation')
router.register(r'notification-logs', UiNotificationLogViewSet)
router.register(r'operation-records', OperationRecordViewSet)
router.register(r'recording', RecordingSessionViewSet, basename='recording')


# Configuration Center APIs
router.register(r'config/environment', EnvironmentConfigViewSet, basename='config-environment')
router.register(r'config/ai-mode', AIIntelligentModeConfigViewSet, basename='config-ai-mode')
router.register(r'ai-models', AIIntelligentModeConfigViewSet, basename='ai-models')
router.register(r'setup-templates', SetupTemplateViewSet, basename='setup-templates')

urlpatterns = [
    path('', include(router.urls)),
    path('ai-assertion/', AIAssertionView.as_view(), name='ai-assertion'),
    path('ai-run-execution/', AITestCaseExecutionView.as_view(), name='ai-run-execution'),
    path('ai-run-execution/<int:test_case_id>/', AITestCaseExecutionView.as_view(), name='ai-run-execution-with-id'),
    path('speech/transcribe/', SpeechTranscribeView.as_view(), name='speech-transcribe'),
    path('speech/parse/', SpeechParseView.as_view(), name='speech-parse'),
    path('speech/locate/', SpeechElementLocateView.as_view(), name='speech-locate'),
]

# 添加媒体文件路由
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
