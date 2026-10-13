# -*- coding: utf-8 -*-
from django.urls import path
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'configs', views.OCRConfigViewSet, basename='ocr-config')
router.register(r'tasks', views.OCRTaskViewSet, basename='ocr-task')

urlpatterns = [
    path('recognize/', views.OCRRecognizeView.as_view(), name='ocr-recognize'),
    path('recognize-batch/', views.OCRBatchRecognizeView.as_view(), name='ocr-recognize-batch'),
    path('recognize-base64/', views.OCRRecognizeBase64View.as_view(), name='ocr-recognize-base64'),
    path('engines/', views.ocr_engines, name='ocr-engines'),
    path('check-installation/', views.ocr_check_installation, name='ocr-check-installation'),
]

urlpatterns += router.urls
