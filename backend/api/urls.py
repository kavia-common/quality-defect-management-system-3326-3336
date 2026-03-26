from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    CorrectiveActionViewSet,
    DashboardViewSet,
    DefectHistoryViewSet,
    DefectViewSet,
    FiveWhyAnalysisViewSet,
    WorkflowStatusViewSet,
    health,
)

router = DefaultRouter()
router.register(r"workflow-statuses", WorkflowStatusViewSet, basename="workflow-statuses")
router.register(r"defects", DefectViewSet, basename="defects")
router.register(r"five-whys", FiveWhyAnalysisViewSet, basename="five-whys")
router.register(r"actions", CorrectiveActionViewSet, basename="actions")
router.register(r"history", DefectHistoryViewSet, basename="history")
router.register(r"dashboard", DashboardViewSet, basename="dashboard")

urlpatterns = [
    path("health/", health, name="Health"),
    path("", include(router.urls)),
]
