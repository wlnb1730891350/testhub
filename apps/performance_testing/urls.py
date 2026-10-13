from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    JMXImportConfirmView,
    JMXImportPreviewView,
    PerformanceDashboardViewSet,
    PerformanceDatasetViewSet,
    PerformanceExecutionViewSet,
    PerformanceProjectViewSet,
    PerformanceScriptViewSet,
)

router = DefaultRouter()
router.register(r'dashboard', PerformanceDashboardViewSet, basename='performance-dashboard')
router.register(r'projects', PerformanceProjectViewSet, basename='performance-project')
router.register(r'scripts', PerformanceScriptViewSet, basename='performance-script')
router.register(r'datasets', PerformanceDatasetViewSet, basename='performance-dataset')
router.register(r'executions', PerformanceExecutionViewSet, basename='performance-execution')

urlpatterns = [
    path('import/preview/', JMXImportPreviewView.as_view(), name='performance-import-preview'),
    path('import/confirm/', JMXImportConfirmView.as_view(), name='performance-import-confirm'),
    path('', include(router.urls)),
]
