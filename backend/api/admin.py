from django.contrib import admin

from .models import CorrectiveAction, Defect, DefectHistory, FiveWhyAnalysis, WorkflowStatus


@admin.register(WorkflowStatus)
class WorkflowStatusAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "sort_order", "is_terminal", "is_active")
    list_filter = ("is_terminal", "is_active")
    search_fields = ("code", "name")


@admin.register(Defect)
class DefectAdmin(admin.ModelAdmin):
    list_display = ("id", "defect_key", "title", "severity", "priority", "status", "due_date", "closed_at", "created_at")
    list_filter = ("severity", "priority", "status")
    search_fields = ("defect_key", "title", "reported_by", "assigned_to", "area", "source")
    autocomplete_fields = ("status",)


@admin.register(FiveWhyAnalysis)
class FiveWhyAnalysisAdmin(admin.ModelAdmin):
    list_display = ("id", "defect", "created_by", "created_at", "updated_at")
    search_fields = ("defect__title", "root_cause", "created_by")


@admin.register(CorrectiveAction)
class CorrectiveActionAdmin(admin.ModelAdmin):
    list_display = ("id", "defect", "title", "owner", "status", "due_date", "completed_at", "created_at")
    list_filter = ("status",)
    search_fields = ("title", "owner", "defect__title")


@admin.register(DefectHistory)
class DefectHistoryAdmin(admin.ModelAdmin):
    list_display = ("id", "defect", "event_type", "actor", "created_at")
    list_filter = ("event_type",)
    search_fields = ("message", "actor", "defect__title")
