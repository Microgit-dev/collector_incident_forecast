from datetime import date

import polars as pl

from apps.forecasting.domain.features import add_weather, weather_features


def _weather():
    return pl.DataFrame(
        {
            "day": [date(2024, 3, 1), date(2024, 3, 2), date(2024, 3, 3), date(2024, 3, 5)],
            "precipitation_mm": [1.0, 2.0, 4.0, 8.0],
            "temperature_max_c": [-2.0, 3.0, 5.0, 1.0],
            "snow_depth_cm": [50.0, 48.0, 40.0, 30.0],
        }
    )


def test_weather_features_rolling_melt_and_next_day():
    w = weather_features(_weather())
    # пропущенные сутки 04.03 достраиваются, а не «склеивают» соседние дни
    assert w["day"].to_list()[3] == date(2024, 3, 4)
    row = w.filter(pl.col("day") == date(2024, 3, 3)).row(0, named=True)
    assert row["wx_precip_3"] == 7.0 and row["wx_thaw_3"] == 8.0 and row["wx_precip_next"] is None
    assert w.filter(pl.col("day") == date(2024, 3, 2))["wx_precip_next"][0] == 4.0
    # таяние — убыль покрова за 3 суток, прирост снега таянием не считается
    assert w.filter(pl.col("day") == date(2024, 3, 5))["wx_melt_3"][0] == 18.0


def test_add_weather_joins_by_day_for_every_channel():
    frame = pl.DataFrame({"channel_id": [1, 2], "day": [date(2024, 3, 3), date(2024, 3, 3)]})
    out = add_weather(frame, _weather())
    assert out["wx_precip_1"].to_list() == [4.0, 4.0]
