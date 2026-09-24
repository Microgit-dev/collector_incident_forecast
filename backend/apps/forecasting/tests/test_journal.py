from datetime import UTC, datetime, timedelta

import pytest

from apps.assets.models import Channel
from apps.forecasting.domain.contracts import ForecastResult
from apps.forecasting.models import ChannelRisk, MLModel, Prediction, RiskPolicy
from apps.forecasting.services import store_forecast
from apps.incidents.models import Alert

AS_OF = datetime(2026, 6, 30, 21, tzinfo=UTC)


@pytest.fixture
def setup(tree):
    model = MLModel.objects.create(task="sensor_failure", version="t", status="active", horizon_hours=24)
    RiskPolicy.objects.create(
        task="sensor_failure", medium_threshold=0.1, high_threshold=0.4, critical_threshold=0.7
    )
    channel = Channel.objects.create(external_id=1, node=tree["house"], name="Дым ПК1")
    return model, channel


def _result(channel, p):
    return ForecastResult(node_id=channel.node_id, channel_id=channel.pk, probability=p, horizon_hours=24)


def test_journal_dedups_and_alerts_on_crossing(setup, django_capture_on_commit_callbacks):
    model, channel = setup
    with django_capture_on_commit_callbacks(execute=True):
        low = store_forecast(model, AS_OF, [_result(channel, 0.2)])  # средний — только список наблюдения
        assert low["predictions"] == 0 and ChannelRisk.objects.get().risk_level == "medium"

        high = store_forecast(model, AS_OF, [_result(channel, 0.5)])
        again = store_forecast(model, AS_OF + timedelta(minutes=15), [_result(channel, 0.55)])
        critical = store_forecast(model, AS_OF + timedelta(minutes=30), [_result(channel, 0.8)])

    assert (high["predictions"], high["alerts"]) == (1, 1)
    assert (again["predictions"], again["alerts"]) == (0, 0)  # тот же уровень — без повторов
    assert critical["predictions"] == 0  # рост уровня обновляет действующий прогноз
    prediction = Prediction.objects.get()
    assert prediction.risk_level == "critical" and prediction.valid_until == AS_OF + timedelta(hours=24)
    assert Alert.objects.filter(source=Alert.Source.FORECAST).count() == 1


def test_backtest_writes_journal_without_incidents(setup):
    model, channel = setup
    result = store_forecast(model, AS_OF, [_result(channel, 0.9)], backtest=True)
    assert result == {"channels": 1, "levels": {"critical": 1}, "predictions": 1, "alerts": 0}
    assert Prediction.objects.get().is_backtest
    assert not Alert.objects.exists()
