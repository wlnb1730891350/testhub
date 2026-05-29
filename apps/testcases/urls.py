from django.urls import path
from . import views

urlpatterns = [
    # 测试用例相关
    path('', views.TestCaseListCreateView.as_view(), name='testcase-list'),
    path('<int:pk>/', views.TestCaseDetailView.as_view(), name='testcase-detail'),
    # 批量导入
    path('import/preview/', views.import_testcases_preview, name='testcase-import-preview'),
    path('import/execute/', views.import_testcases_execute, name='testcase-import-execute'),
]