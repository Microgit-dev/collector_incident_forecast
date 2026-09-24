from django.db.models import Count

from apps.forecasting.models import Prediction
from apps.incidents.models import Incident
from apps.telemetry.models import ChannelState
from apps.topology.selectors import scope_queryset


def overview(user) -> dict:
    """Сводка для дашборда: открытые инциденты, состояние парка датчиков, активные прогнозы."""
    incidents = scope_queryset(Incident.objects.filter(status__in=Incident.OPEN_STATUSES), user, "node")
    states = scope_queryset(ChannelState.objects.filter(facet="primary"), user, "channel__node")
    predictions = scope_queryset(
        Prediction.objects.filter(outcome=Prediction.Outcome.PENDING, is_backtest=False), user, "node"
    )

    def grouped(qs, field):
        return {row[field]: row["n"] for row in qs.values(field).annotate(n=Count("pk")).order_by()}

    return {
        "incidents_open": incidents.count(),
        "incidents_by_severity": grouped(incidents, "severity"),
        "incidents_by_type": grouped(incidents, "type"),
        "incidents_unassigned": incidents.filter(assigned_to=None).count(),
        "incidents_escalated": incidents.filter(escalation_level__gt=0).count(),
        "channels_by_state": grouped(states, "state"),
        "predictions_by_risk": grouped(predictions, "risk_level"),
    }
