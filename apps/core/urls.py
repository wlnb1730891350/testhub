"""
Core application routes.
"""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import UnifiedNotificationConfigViewSet, WorkspaceViewSet

router = DefaultRouter()
router.register(r'notification-configs', UnifiedNotificationConfigViewSet, basename='unified-notification-config')
router.register(r'workspace', WorkspaceViewSet, basename='workspace')

urlpatterns = [
    path('', include(router.urls)),
]
