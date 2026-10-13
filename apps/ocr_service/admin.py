# # -*- coding: utf-8 -*-
# from django.contrib import admin
# from .models import OCRConfig, OCRTask
#
#
# @admin.register(OCRConfig)
# class OCRConfigAdmin(admin.ModelAdmin):
#     list_display = ['name', 'provider', 'language', 'is_active', 'is_default', 'created_at']
#     list_filter = ['provider', 'is_active', 'is_default']
#     search_fields = ['name']
#     readonly_fields = ['created_at', 'updated_at']
#
#     fieldsets = (
#         ('基本信息', {
#             'fields': ('name', 'provider', 'is_active', 'is_default')
#         }),
#         ('API 配置', {
#             'fields': ('api_key', 'base_url', 'model_name'),
#             'classes': ('collapse',),
#         }),
#         ('识别配置', {
#             'fields': ('language', 'min_confidence', 'extra_config'),
#         }),
#         ('元信息', {
#             'fields': ('created_by', 'created_at', 'updated_at'),
#             'classes': ('collapse',),
#         }),
#     )
#
#
# @admin.register(OCRTask)
# class OCRTaskAdmin(admin.ModelAdmin):
#     list_display = ['task_id', 'config', 'status', 'confidence', 'processing_time', 'created_at']
#     list_filter = ['status', 'config']
#     search_fields = ['task_id', 'image_path']
#     readonly_fields = ['task_id', 'created_at', 'completed_at']
#
#     fieldsets = (
#         ('任务信息', {
#             'fields': ('task_id', 'config', 'image_path', 'status')
#         }),
#         ('识别结果', {
#             'fields': ('result_text', 'result_data', 'confidence', 'processing_time'),
#         }),
#         ('错误信息', {
#             'fields': ('error_message',),
#             'classes': ('collapse',),
#         }),
#         ('时间信息', {
#             'fields': ('created_at', 'completed_at'),
#         }),
#     )
