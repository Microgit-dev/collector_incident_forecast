from datetime import UTC, date, datetime

import polars as pl
import pytest

from apps.assets.models import Channel
from apps.forecasting.domain.feedback import apply_labels
from apps.forecasting.feedback import labels_from_decision, seed_rules
from apps.forecasting.models import FeedbackLabel, LearningSettings, MLModel
from apps.forecasting.training import challenger_verdict
from apps.incidents import services
from apps.incidents.models import Alert, DecisionOutcome, DecisionReason, IncidentType


def _frame():
    return pl.DataFrame(
        {
            "channel_id": [1, 1, 1, 2],
            "day": [date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 2)],
            "y": [False, True, False, False],
        }
    )


def _labels(rows):
    return pl.DataFrame(
        rows,
        schema={
            "label_id": pl.Int64,
            "channel_id": pl.Int64,
            "label_date": pl.Date,
            "effect": pl.String,
            "weight": pl.Float64,
        },
        orient="row",
    )


def test_labels_flip_and_exclude_rows_within_horizon():
    labels = _labels([(10, 1, date(2024, 1, 3), "negative", 2.0), (11, 2, date(2024, 1, 3), "exclude", 1.0)])
    out, stats, per_label = apply_labels(_frame(), labels, horizon_days=1)
    # метка на 03.01 затрагивает строку 02.01 (прогноз на конец суток про следующие сутки)
    row = out.filter((pl.col("channel_id") == 1) & (pl.col("day") == date(2024, 1, 2))).row(0, named=True)
    assert row["y"] is False and row["y_orig"] is True and row["fb_weight"] == 2.0 and row["fb"]
    assert out.filter(pl.col("channel_id") == 2).is_empty()
    assert stats["negative"] == {"rows": 1, "flipped": 1, "positives_removed": 0}
    assert per_label == {10: 1, 11: 1}


def test_exclude_wins_over_positive_on_same_row():
    labels = _labels([(1, 1, date(2024, 1, 2), "positive", 3.0), (2, 1, date(2024, 1, 2), "exclude", 1.0)])
    out, _, _ = apply_labels(_frame(), labels, horizon_days=1)
    assert date(2024, 1, 1) not in out.filter(pl.col("channel_id") == 1)["day"].to_list()


@pytest.fixture
def reasons(db):
    for code, name, outcome in [
        ("false-sensor-fault", "Ложное: неисправность датчика", DecisionOutcome.FALSE_ALARM),
        ("resolved-onsite", "Устранено на месте", DecisionOutcome.RESOLVED),
    ]:
        DecisionReason.objects.create(code=code, name=name, outcome=outcome)
    seed_rules()


def test_decision_creates_labels_per_channel(tree, make_user, reasons):
    user = make_user("disp", "unit_dispatcher", tree["house"])
    channels = [Channel.objects.create(external_id=i, node=tree["house"], name=f"Дым {i}") for i in (1, 2)]
    ts = datetime(2026, 6, 30, 22, 0, tzinfo=UTC)  # 01.07 по Москве
    for ch in channels:
        services.raise_alert(
            type=IncidentType.FIRE,
            severity="critical",
            node=tree["house"],
            channel=ch,
            title="Пожар",
            source=Alert.Source.RULE,
            raised_at=ts,
        )
    incident = channels[0].alerts.first().incident
    services.take(incident, user)
    services.decide(
        incident,
        user,
        outcome=DecisionOutcome.FALSE_ALARM,
        reason=DecisionReason.objects.get(code="false-sensor-fault"),
    )
    labels = FeedbackLabel.objects.order_by("channel_id")
    assert labels.count() == 2
    assert {lab.effect for lab in labels} == {"positive"} and labels[0].status == "accepted"
    assert (
        labels[0].label_date == date(2026, 7, 1) and labels[0].weight == 3.0 and labels[0].decided_by == user
    )


def test_rule_requiring_review_leaves_label_pending(tree, make_user, reasons):
    user = make_user("disp", "unit_dispatcher", tree["house"])
    ch = Channel.objects.create(external_id=5, node=tree["house"], name="Дым 5")
    incident = services.raise_alert(
        type=IncidentType.SENSOR_FAILURE,
        severity="medium",
        node=tree["house"],
        channel=ch,
        title="Сбой",
        source=Alert.Source.RULE,
    ).incident
    services.take(incident, user)
    decision = services.decide(
        incident,
        user,
        outcome=DecisionOutcome.RESOLVED,
        reason=DecisionReason.objects.get(code="resolved-onsite"),
    )
    assert FeedbackLabel.objects.get(decision=decision).status == "pending"
    assert labels_from_decision(decision) == 1  # повторно — без дублей
    assert FeedbackLabel.objects.count() == 1


def test_challenger_needs_to_beat_champion_on_same_validation(db):
    settings = LearningSettings.load()
    champion = MLModel.objects.create(
        task="sensor_failure", version="a", horizon_hours=24, metrics={"valid": {"pr_auc": 0.14}}
    )
    worse = MLModel(
        task="sensor_failure",
        version="b",
        horizon_hours=24,
        metrics={"comparison": {"valid_pr_auc": 0.13, "champion_valid_pr_auc": 0.15}},
    )
    better = MLModel(
        task="sensor_failure",
        version="c",
        horizon_hours=24,
        metrics={"comparison": {"valid_pr_auc": 0.16, "champion_valid_pr_auc": 0.15}},
    )
    assert challenger_verdict(worse, champion, settings)[0] is False
    assert challenger_verdict(better, champion, settings)[0] is True
    settings.auto_activate = False
    assert challenger_verdict(better, champion, settings) == (
        False,
        "лучше действующей (0.1600 против 0.1500), ждёт активации аналитиком",
    )


def test_analyst_reviews_labels_in_bulk_and_dispatcher_cannot(tree, make_user, reasons):
    from rest_framework.test import APIClient

    dispatcher = make_user("disp", "unit_dispatcher", tree["house"])
    analyst = make_user("an", "analyst", tree["district"])
    ch = Channel.objects.create(external_id=7, node=tree["house"], name="Дым 7")
    incident = services.raise_alert(
        type=IncidentType.SENSOR_FAILURE,
        severity="medium",
        node=tree["house"],
        channel=ch,
        title="Сбой",
        source=Alert.Source.RULE,
    ).incident
    services.take(incident, dispatcher)
    services.decide(
        incident,
        dispatcher,
        outcome=DecisionOutcome.FALSE_ALARM,
        reason=DecisionReason.objects.get(code="false-sensor-fault"),
    )

    client = APIClient()
    client.force_authenticate(dispatcher)
    assert client.get("/api/v1/forecasting/feedback-labels/").status_code == 403
    client.force_authenticate(analyst)
    response = client.post(
        "/api/v1/forecasting/feedback-labels/review/",
        {"decided_by": dispatcher.pk, "status": "rejected", "comment": "проверка"},
        format="json",
    )
    assert response.json() == {"changed": 1}
    assert FeedbackLabel.objects.get().status == "rejected"
    summary = client.get("/api/v1/forecasting/feedback-labels/summary/").json()
    assert summary["by_status"] == {"rejected": 1} and summary["by_dispatcher"][0]["rejected"] == 1
    rule = client.get("/api/v1/forecasting/feedback-rules/").json()[0]
    patched = client.patch(
        f"/api/v1/forecasting/feedback-rules/{rule['id']}/", {"enabled": False}, format="json"
    )
    assert patched.status_code == 200
    settings = client.patch("/api/v1/forecasting/learning-settings/", {"auto_activate": False}, format="json")
    assert settings.json()["auto_activate"] is False
