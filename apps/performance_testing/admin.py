from django.contrib import admin

from .models import PerformanceDataset, PerformanceExecution, PerformanceProject, PerformanceScript


@admin.register(PerformanceProject)
class PerformanceProjectAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'status', 'owner', 'created_at')
    search_fields = ('name', 'description')
    list_filter = ('status',)


@admin.register(PerformanceScript)
class PerformanceScriptAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'project', 'script_type', 'status', 'version', 'updated_at')
    search_fields = ('name', 'description')
    list_filter = ('script_type', 'status')


@admin.register(PerformanceDataset)
class PerformanceDatasetAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'project', 'row_count', 'created_at')
    search_fields = ('name', 'description')


@admin.register(PerformanceExecution)
class PerformanceExecutionAdmin(admin.ModelAdmin):
    list_display = ('id', 'script', 'project', 'status', 'report_status', 'started_at', 'finished_at')
    search_fields = ('script__name', 'project__name')
    list_filter = ('status', 'report_status')
