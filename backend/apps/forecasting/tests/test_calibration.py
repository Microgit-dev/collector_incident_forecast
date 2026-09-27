"""Калибровка индекса пожара и НСД в вероятность проявления угрозы."""

from django.utils import timezone

from apps.forecasting.domain import calibration as cal


def test_fit_is_monotone_and_shrinks_small_bins():
    samples = [(0.2, False)] * 90 + [(0.2, True)] * 10  # 10 %
    samples += [(0.35, True)] * 40 + [(0.35, False)] * 60  # 40 %
    samples += [(0.55, True)] * 1 + [(0.55, False)] * 3  # 25 % на 4 случаях — ниже соседа слева
    samples += [(0.8, True)] * 30 + [(0.8, False)] * 20  # 60 %
    fitted = cal.fit(samples)
    probs = [b["p"] for b in fitted["bins"]]
    assert probs == sorted(probs), "больший индекс не может давать меньшую вероятность"
    assert fitted["n"] == 254 and fitted["k"] == 81
    first = fitted["bins"][0]
    assert first["n"] == 100 and 0.1 < first["p"] < fitted["base_rate"]  # сглажено к общей частоте
    # пустой интервал получает сглаженную частоту, а не 0 или 100 %
    assert 0 < cal.probability(fitted, 0.95) < 1


def test_probability_below_range_and_evidence():
    fitted = cal.fit([(0.4, True), (0.4, False)])
    assert cal.probability(fitted, 0.1) is None
    bin_ = cal.evidence(fitted, 0.45)
    assert bin_["lo"] == 0.4 and bin_["n"] == 2
    assert cal.evidence(fitted, 0.99)["hi"] == 1.0


def test_brier_and_reliability():
    fitted = cal.fit([(0.3, True)] * 5 + [(0.3, False)] * 5)
    assert cal.brier([(0.5, True), (0.5, False)]) == 0.25
    rows = cal.reliability(fitted, [(0.35, True), (0.35, False), (0.8, True)])
    by_lo = {r["lo"]: r for r in rows}
    assert by_lo[0.3]["n"] == 2 and by_lo[0.3]["observed"] == 0.5
    assert by_lo[0.15]["observed"] is None


def test_scenarios_use_calibrated_probability(tree, monkeypatch):
    """Прогноз пожара: вероятность из калибровки, индекс — отдельно, пояснение с числом случаев."""
    from apps.forecasting import scenarios
    from apps.forecasting.domain.scenarios import Assessment
    from apps.forecasting.models import IndicatorCalibration, Prediction

    now = timezone.now().replace(microsecond=0)
    found = Assessment(
        0.9, [{"feature": "rule", "title": "Сработали дымовые извещатели: 2", "contribution": 0.5}]
    )
    # окно данных считается SQL оперативного контура (PostgreSQL) — здесь подставляем готовую оценку
    monkeypatch.setattr(scenarios, "assess", lambda as_of: [("fire", tree["house"].pk, found)])
    calibration = cal.fit([(0.9, True)] * 30 + [(0.9, False)] * 70 + [(0.2, False)] * 100)
    IndicatorCalibration.objects.create(task="fire", period="2019–2025", calibration=calibration)

    scenarios.run_scenarios(now, backtest=True)
    prediction = Prediction.objects.get(task="fire")
    assert prediction.index == 0.9
    assert prediction.probability == cal.probability(calibration, 0.9) < 0.9
    assert "по истории 2019–2025" in prediction.summary


def test_scenarios_without_calibration_keep_index(tree, monkeypatch):
    from apps.forecasting import scenarios
    from apps.forecasting.domain.scenarios import Assessment
    from apps.forecasting.models import Prediction

    monkeypatch.setattr(scenarios, "assess", lambda as_of: [("intrusion", tree["house"].pk, Assessment(0.6))])
    scenarios.run_scenarios(timezone.now(), backtest=True)
    prediction = Prediction.objects.get(task="intrusion")
    assert prediction.probability == prediction.index == 0.6
