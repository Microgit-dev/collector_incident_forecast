"""Поставляемые модели и обучение без истории в базе."""

import pytest

from apps.forecasting import pretrained, specs
from apps.forecasting.channel_model import ChannelForecaster, NotEnoughData
from apps.forecasting.models import MLModel, TrainingRun
from apps.forecasting.training import execute


@pytest.mark.django_db
def test_install_activates_shipped_models_once():
    installed = pretrained.install()
    assert {line.split()[0] for line in installed} == {"sensor_failure", "flood", "gas"}
    active = MLModel.objects.filter(status=MLModel.Status.ACTIVE)
    assert active.count() == 3
    assert all(m.params["trigger"] == "pretrained" and m.metrics["levels"] for m in active)
    assert pretrained.install() == []  # активные модели уже есть — ничего не меняется
    model = active.get(task="flood")
    forecaster = ChannelForecaster(specs.get("flood"), model.artifact_path, 0.3)
    assert forecaster.booster.num_feature() == len(forecaster.meta["columns"]) == len(model.features)


@pytest.mark.django_db
def test_training_without_history_fails_with_clear_reason():
    run = TrainingRun.objects.create(task="sensor_failure", params={})
    with pytest.raises(NotEnoughData):
        execute(run)
    run.refresh_from_db()
    assert run.status == TrainingRun.Status.FAILED
    assert run.stage == "Недостаточно данных"
    assert "Недостаточно истории" in run.log and "LightGBM" not in run.log
