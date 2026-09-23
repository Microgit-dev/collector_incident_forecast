from rest_framework.routers import DefaultRouter

from .views import AlertViewSet, DecisionReasonViewSet, EscalationPolicyViewSet, IncidentViewSet

router = DefaultRouter()
router.register("incidents/items", IncidentViewSet)
router.register("incidents/alerts", AlertViewSet)
router.register("incidents/reasons", DecisionReasonViewSet)
router.register("incidents/escalation-policies", EscalationPolicyViewSet)

urlpatterns = router.urls
