"""
Пакетная обработка исторических журналов СМВУ (десятки миллионов строк на год).

Идея: в журнале лишь несколько тысяч различных значений `значение_датчика`, поэтому
тот же движок нормализации, что и в потоке (domain/engine.py), применяется к уникальным
парам (профиль, значение), а результат присоединяется обратно векторно в Polars.
Логика интерпретации одна на поток и архив, скорость — как у колоночной обработки.

Результат:
- Parquet-архив по годам (ТЗ §13, архивный контур) — источник для обучения моделей;
- отчёт о качестве загрузки (ImportJob.quality);
- суточная витрина ChannelDaily за всю историю;
- сырые показания только за оперативное окно — в hypertable.
"""

from __future__ import annotations

import io
import logging
import shutil
import tempfile
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

import polars as pl
from django.db import connection
from django.utils import timezone

from apps.assets.models import Channel
from apps.assets.services import ensure_channels
from apps.normalization.domain.engine import Profile, Quality, State, normalize
from apps.normalization.selectors import CompiledRegistry, compiled_registry

logger = logging.getLogger(__name__)

# Колбэк прогресса: (доля 0..1, название этапа). Задание импорта пишет его в БД для интерфейса.
Progress = Callable[[float, str], None]


def _noop(_: float, __: str) -> None:
    pass


MSK = "Europe/Moscow"
FALLBACK = "fallback"
COLUMNS = {
    "ид_события": "event_id",
    "ид_канала_данных": "channel_ext",
    "дата": "date",
    "время": "time",
    "тревожное": "raw_alarm",
    "значение_датчика": "raw_value",
}
VALID_STATES = [State.NORMAL, State.WARNING, State.ALARM, State.EVENT]
TECHNICAL_STATES = [State.FAULT, State.POWER_LOSS, State.UNKNOWN]
READING_COLUMNS = [
    "ts",
    "event_id",
    "channel_id",
    "raw_value",
    "raw_alarm",
    "numeric",
    "state",
    "facet",
    "quality",
]


def _channel_frame() -> pl.DataFrame:
    rows = Channel.objects.values_list(
        "external_id", "pk", "profile_override__code", "sensor_type__profile__code"
    )
    return pl.DataFrame(
        [(ext, pk, override or by_type or FALLBACK) for ext, pk, override, by_type in rows],
        schema={"channel_ext": pl.Int64, "channel_id": pl.Int64, "profile": pl.Utf8},
        orient="row",
    )


def _value_map(pairs: pl.DataFrame, registry: CompiledRegistry) -> pl.DataFrame:
    """Нормализация уникальных пар (профиль, значение) движком из domain/engine.py."""
    fallback = Profile(code=FALLBACK)
    rows = []
    for profile_code, raw, raw_alarm in pairs.iter_rows():
        result = normalize(
            raw, registry.profiles.get(profile_code, fallback), registry.global_rules, raw_alarm
        )
        rows.append(
            (
                profile_code,
                raw,
                raw_alarm,
                result.state.value,
                result.numeric,
                result.facet,
                result.quality.value,
            )
        )
    return pl.DataFrame(
        rows,
        schema={
            "profile": pl.Utf8,
            "raw_value": pl.Utf8,
            "raw_alarm": pl.Boolean,
            "state": pl.Utf8,
            "numeric": pl.Float64,
            "facet": pl.Utf8,
            "quality": pl.Utf8,
        },
        orient="row",
    )


def _scan(src: Path) -> pl.LazyFrame:
    true_values = ["t", "true", "1"]
    false_values = ["f", "false", "0"]
    return (
        pl.scan_csv(src, infer_schema=False)
        .rename(COLUMNS)
        .with_columns(
            pl.col("event_id").cast(pl.Int64, strict=False),
            pl.col("channel_ext").cast(pl.Int64, strict=False),
            pl.col("raw_value").fill_null("").str.strip_chars(),
            pl.when(pl.col("raw_alarm").str.to_lowercase().is_in(true_values))
            .then(True)
            .when(pl.col("raw_alarm").str.to_lowercase().is_in(false_values))
            .then(False)
            .otherwise(None)
            .alias("raw_alarm"),
            (pl.col("date") + " " + pl.col("time"))
            .str.strptime(pl.Datetime("us"), "%Y-%m-%d %H:%M:%S", strict=False)
            .dt.replace_time_zone(MSK, ambiguous="earliest", non_existent="null")
            .dt.convert_time_zone("UTC")
            .alias("ts"),
        )
    )


def normalize_journal(
    src: Path,
    dst: Path,
    *,
    year: int | None = None,
    create_missing_channels: bool = True,
    progress: Progress = _noop,
) -> dict:
    """
    CSV журнала → нормализованный Parquet + отчёт о качестве.

    CSV читается ровно один раз — во временный Parquet на локальном диске; все проходы
    (статистика, дубли, каналы, уникальные значения, запись) идут уже по нему. На томах,
    примонтированных в контейнер, повторное чтение многогигабайтного CSV — основная потеря времени.
    """
    with tempfile.TemporaryDirectory(prefix="journal-") as tmp:
        staging = Path(tmp) / "staging.parquet"
        progress(0.02, "Чтение файла")
        _scan(src).sink_parquet(staging, compression="lz4")
        result = Path(tmp) / "result.parquet"
        report = _normalize_staged(pl.scan_parquet(staging), result, year, create_missing_channels, progress)
        progress(0.95, "Сохранение архива")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(result, dst)
    report["source"] = src.name
    return report


def _normalize_staged(
    base: pl.LazyFrame, dst: Path, year: int | None, create_missing_channels: bool, progress: Progress = _noop
) -> dict:
    now = timezone.now()
    in_period = pl.col("ts") <= pl.lit(now)
    if year is not None:
        # ts хранится в UTC, а год файла — по московскому времени
        in_period &= pl.col("ts").dt.convert_time_zone(MSK).dt.year() == year
    ids_ok = pl.col("event_id").is_not_null() & pl.col("channel_ext").is_not_null()

    progress(0.25, "Проверка идентификаторов и времени")
    pre = (
        base.select(
            pl.len().alias("rows_total"),
            (~ids_ok).sum().alias("bad_ids"),
            (ids_ok & pl.col("ts").is_null()).sum().alias("bad_time"),
            (ids_ok & pl.col("ts").is_not_null() & ~in_period).sum().alias("out_of_period"),
        )
        .collect(engine="streaming")
        .row(0, named=True)
    )

    clean = base.filter(ids_ok & pl.col("ts").is_not_null() & in_period).with_columns(
        pl.col("ts").dt.convert_time_zone(MSK).dt.strftime("%Y-%m").alias("month")
    )
    # Год обрабатывается помесячно (≈5 млн строк за раз): дедупликация и поиск каналов
    # по всему году сразу держали в памяти десятки миллионов строк и упирали Docker в лимит.
    # Дубль — это повтор всей записи (id, канал, время, значение): такие всегда в одном месяце.
    # Сам ид_события не уникален: в 2023 году ~227 тыс. id переиспользованы для других каналов
    # и дат — это разные события, их нельзя схлопывать по одному идентификатору.
    months = sorted(clean.select("month").unique().collect(engine="streaming")["month"].to_list())
    parts_dir = dst.parent / "parts"
    parts_dir.mkdir(exist_ok=True)
    duplicates = 0
    journal_channels: set[int] = set()
    for index, month in enumerate(months):
        progress(
            0.3 + 0.35 * index / max(len(months), 1), f"Дедупликация: {month} ({index + 1} из {len(months)})"
        )
        part = clean.filter(pl.col("month") == month).drop("month").collect(engine="streaming")
        unique = part.unique(subset=["event_id", "channel_ext", "ts", "raw_value"], keep="any")
        duplicates += part.height - unique.height
        journal_channels.update(unique["channel_ext"].unique().to_list())
        unique.write_parquet(parts_dir / f"{month}.parquet", compression="lz4")
        del part, unique
    clean = pl.scan_parquet(parts_dir / "*.parquet")

    progress(0.65, "Сверка каналов со справочником")
    known = set(Channel.objects.filter(in_catalog=True).values_list("external_id", flat=True))
    unknown_channels = journal_channels - known
    if create_missing_channels:
        ensure_channels(unknown_channels)
    channels = _channel_frame()

    joined = clean.join(channels.lazy(), on="channel_ext", how="inner")
    # Ключ нормализации включает флаг источника: от него зависит трактовка охранных сработок
    pairs = joined.select("profile", "raw_value", "raw_alarm").unique().collect(engine="streaming")
    values = _value_map(pairs, compiled_registry())
    progress(0.72, f"Нормализация значений ({pairs.height} уникальных)")

    (
        joined.join(values.lazy(), on=["profile", "raw_value", "raw_alarm"], how="left", nulls_equal=True)
        .select(
            "ts",
            "event_id",
            "channel_ext",
            "channel_id",
            "raw_value",
            "raw_alarm",
            "numeric",
            "state",
            "facet",
            "quality",
        )
        .sink_parquet(dst, compression="zstd", row_group_size=1_000_000)
    )

    progress(0.88, "Отчёт о качестве")
    report = _quality_report(dst, values, unknown_channels)
    report.update(
        year=year,
        rows_total=pre["rows_total"],
        bad_ids=pre["bad_ids"],
        bad_time=pre["bad_time"],
        out_of_period=pre["out_of_period"],
        duplicates=duplicates,
        unique_values=pairs.height,
    )
    report["summary"] = _summary(report)
    return report


def _quality_report(parquet: Path, values: pl.DataFrame, unknown_channels: set[int]) -> dict:
    lf = pl.scan_parquet(parquet)
    totals = (
        lf.select(
            pl.len().alias("rows_loaded"),
            pl.col("ts").min().alias("from"),
            pl.col("ts").max().alias("to"),
            pl.col("channel_ext").n_unique().alias("channels"),
            (pl.col("raw_alarm") == True).sum().alias("source_alarm_rows"),  # noqa: E712
            pl.col("channel_ext").is_in(list(unknown_channels)).sum().alias("unknown_channel_rows"),
        )
        .collect(engine="streaming")
        .row(0, named=True)
    )
    by_quality = dict(lf.group_by("quality").len().collect(engine="streaming").iter_rows())
    by_state = dict(lf.group_by("state").len().collect(engine="streaming").iter_rows())
    by_state_ok = dict(
        lf.filter(pl.col("quality") == Quality.OK)
        .group_by("state")
        .len()
        .collect(engine="streaming")
        .iter_rows()
    )
    unmapped = (
        lf.filter(pl.col("quality") == Quality.UNMAPPED_TEXT)
        .group_by("raw_value")
        .len()
        .sort("len", descending=True)
        .head(20)
        .collect(engine="streaming")
    )
    return {
        "rows_loaded": totals["rows_loaded"],
        "period": {
            "from": totals["from"].isoformat() if totals["from"] else None,
            "to": totals["to"].isoformat() if totals["to"] else None,
        },
        "channels": totals["channels"],
        "unknown_channels": len(unknown_channels),
        "unknown_channel_rows": totals["unknown_channel_rows"],
        "source_alarm_rows": totals["source_alarm_rows"],
        "by_quality": by_quality,
        "by_state": by_state,
        "valid_rows": sum(by_state_ok.get(s, 0) for s in VALID_STATES),
        "technical_rows": sum(by_state_ok.get(s, 0) for s in TECHNICAL_STATES),
        "unmapped_top": [{"value": v, "rows": n} for v, n in unmapped.iter_rows()],
    }


def _summary(report: dict) -> list[dict]:
    """Сводка для интерфейса: те же пять категорий, что показываются в отчёте."""
    invalid = sum(n for q, n in report["by_quality"].items() if q not in (Quality.OK, Quality.DRIFT))
    return [
        {"key": "rows_total", "label": "Всего строк", "value": report["rows_total"]},
        {"key": "valid", "label": "Корректные измерения и события", "value": report["valid_rows"]},
        {
            "key": "technical",
            "label": "Технические состояния (неисправен, обесточен, неопределён)",
            "value": report["technical_rows"],
        },
        {
            "key": "drift",
            "label": "Дрейф нуля газоанализаторов (нужна калибровка)",
            "value": report["by_quality"].get(Quality.DRIFT, 0),
        },
        {
            "key": "invalid",
            "label": "Невалидные значения (служебные коды, 1970, вне диапазона)",
            "value": invalid,
        },
        {
            "key": "time",
            "label": "Ошибки времени и вне периода",
            "value": report["bad_time"] + report["out_of_period"],
        },
        {"key": "duplicates", "label": "Дубли ид_события", "value": report["duplicates"]},
        {"key": "bad_ids", "label": "Нет идентификатора события или канала", "value": report["bad_ids"]},
        {
            "key": "unknown",
            "label": "Строки каналов вне справочника",
            "value": report["unknown_channel_rows"],
        },
    ]


# ---------- загрузка в БД ----------


def _copy(table: str, columns: list[str], frame: pl.DataFrame) -> None:
    buffer = io.BytesIO()
    frame.write_csv(
        buffer, include_header=False, null_value="\\N", datetime_format="%Y-%m-%d %H:%M:%S%.6f+00"
    )
    raw = connection.connection  # psycopg3: COPY быстрее bulk_create на порядки
    with (
        raw.cursor() as cursor,
        cursor.copy(f"COPY {table} ({', '.join(columns)}) FROM STDIN (FORMAT csv, NULL '\\N')") as copy,
    ):
        copy.write(buffer.getvalue())


def load_readings(
    parquets: list[Path], since: datetime, batch: int = 500_000, progress: Progress = _noop
) -> int:
    """Сырые показания за оперативное окно → hypertable. Повторный запуск не создаёт дублей."""
    connection.ensure_connection()
    frame = (
        pl.scan_parquet(parquets)
        .filter(pl.col("ts") >= pl.lit(since).dt.convert_time_zone("UTC"))
        .with_columns(pl.col("ts").dt.replace_time_zone(None))
        .select(READING_COLUMNS)
        .collect(engine="streaming")
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "CREATE TEMP TABLE IF NOT EXISTS stage_reading (LIKE telemetry_reading INCLUDING DEFAULTS)"
        )
    inserted = 0
    for offset in range(0, frame.height, batch):
        progress(
            0.1 + 0.8 * offset / max(frame.height, 1), f"Загрузка показаний: {offset:,} из {frame.height:,}"
        )
        with connection.cursor() as cursor:
            cursor.execute("TRUNCATE stage_reading")
        _copy("stage_reading", READING_COLUMNS, frame.slice(offset, batch))
        with connection.cursor() as cursor:
            cursor.execute(
                f"INSERT INTO telemetry_reading ({', '.join(READING_COLUMNS)}) "
                f"SELECT {', '.join(READING_COLUMNS)} FROM stage_reading ON CONFLICT DO NOTHING"
            )
            inserted += cursor.rowcount
    progress(0.92, "Текущие состояния каналов")
    _load_channel_states(frame)
    return inserted


def _load_channel_states(frame: pl.DataFrame) -> None:
    """Текущее состояние каналов = последнее значение окна; «состояние с» = начало последней серии."""
    if frame.is_empty():
        return
    runs = frame.sort("channel_id", "facet", "ts").with_columns(
        (pl.col("state") != pl.col("state").shift(1).over("channel_id", "facet"))
        .fill_null(True)
        .cum_sum()
        .over("channel_id", "facet")
        .alias("run")
    )
    last = runs.group_by("channel_id", "facet").agg(
        pl.col("state").last(),
        pl.col("numeric").last(),
        pl.col("raw_value").last(),
        pl.col("ts").last().alias("last_seen_at"),
        pl.col("run").last(),
    )
    started = runs.group_by("channel_id", "facet", "run").agg(pl.col("ts").min().alias("changed_at"))
    states = last.join(started, on=["channel_id", "facet", "run"]).select(
        "channel_id", "facet", "state", "numeric", "raw_value", "changed_at", "last_seen_at"
    )
    columns = states.columns
    with connection.cursor() as cursor:
        # Без суррогатного id: LIKE не переносит автоинкремент, а для upsert он не нужен
        cursor.execute(
            f"CREATE TEMP TABLE IF NOT EXISTS stage_state AS "
            f"SELECT {', '.join(columns)} FROM telemetry_channelstate WITH NO DATA"
        )
        cursor.execute("TRUNCATE stage_state")
    _copy("stage_state", columns, states.with_columns(pl.col("raw_value").fill_null("")))
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            INSERT INTO telemetry_channelstate ({", ".join(columns)})
            SELECT {", ".join(columns)} FROM stage_state
            ON CONFLICT (channel_id, facet) DO UPDATE SET
                state = EXCLUDED.state, numeric = EXCLUDED.numeric, raw_value = EXCLUDED.raw_value,
                changed_at = EXCLUDED.changed_at, last_seen_at = EXCLUDED.last_seen_at
            WHERE telemetry_channelstate.last_seen_at <= EXCLUDED.last_seen_at
            """
        )


DAILY_COLUMNS = [
    "day",
    "channel_id",
    "readings",
    "normal",
    "warnings",
    "alarms",
    "faults",
    "power_losses",
    "unknowns",
    "events",
    "invalid",
    "numeric_avg",
    "numeric_min",
    "numeric_max",
    "first_ts",
    "last_ts",
    "last_state",
    "first_fault_ts",
]


def daily_frame(lf: pl.LazyFrame, progress: Progress = _noop) -> pl.DataFrame:
    """Суточная сводка; считается помесячно, чтобы группировка не держала год в памяти."""
    local_day = pl.col("ts").dt.convert_time_zone(MSK).dt.date()
    bounds = lf.select(local_day.min().alias("lo"), local_day.max().alias("hi")).collect(engine="streaming")
    lo, hi = bounds["lo"][0], bounds["hi"][0]
    if lo is None:
        return _daily_month(lf.head(0))
    frames = []
    year, month = lo.year, lo.month
    total = (hi.year - lo.year) * 12 + hi.month - lo.month + 1
    while (year, month) <= (hi.year, hi.month):
        progress(len(frames) / total, f"Суточная витрина: {year}-{month:02d} ({len(frames) + 1} из {total})")
        frames.append(
            _daily_month(lf.filter((local_day.dt.year() == year) & (local_day.dt.month() == month)))
        )
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return pl.concat(frames)


def _daily_month(lf: pl.LazyFrame) -> pl.DataFrame:
    def count(state: State) -> pl.Expr:
        return (pl.col("state") == state.value).sum().alias(state_column[state])

    state_column = {
        State.NORMAL: "normal",
        State.WARNING: "warnings",
        State.ALARM: "alarms",
        State.FAULT: "faults",
        State.POWER_LOSS: "power_losses",
        State.UNKNOWN: "unknowns",
        State.EVENT: "events",
    }
    # Числовая статистика — только по корректным значениям: служебные коды не концентрация
    valid_numeric = pl.when(pl.col("quality").is_in([Quality.OK, Quality.DRIFT])).then(pl.col("numeric"))
    primary = pl.col("facet") == "primary"
    return (
        lf.with_columns(pl.col("ts").dt.convert_time_zone(MSK).dt.date().alias("day"))
        .group_by("day", "channel_id")
        .agg(
            pl.len().alias("readings"),
            *[count(s) for s in state_column],
            (~pl.col("quality").is_in([Quality.OK, Quality.DRIFT])).sum().alias("invalid"),
            valid_numeric.mean().alias("numeric_avg"),
            valid_numeric.min().alias("numeric_min"),
            valid_numeric.max().alias("numeric_max"),
            pl.col("ts").min().dt.replace_time_zone(None).alias("first_ts"),
            pl.col("ts").max().dt.replace_time_zone(None).alias("last_ts"),
            pl.col("state")
            .filter(primary)
            .sort_by(pl.col("ts").filter(primary))
            .last()
            .fill_null("")
            .alias("last_state"),
            pl.col("ts")
            .filter(pl.col("state") == State.FAULT.value)
            .min()
            .dt.replace_time_zone(None)
            .alias("first_fault_ts"),
        )
        .select(DAILY_COLUMNS)
        .collect(engine="streaming")
    )


def load_daily(frame: pl.DataFrame) -> int:
    connection.ensure_connection()
    with connection.cursor() as cursor:
        cursor.execute(
            "CREATE TEMP TABLE IF NOT EXISTS stage_daily (LIKE telemetry_channeldaily INCLUDING DEFAULTS)"
        )
        cursor.execute("TRUNCATE stage_daily")
    _copy("stage_daily", DAILY_COLUMNS, frame)
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in DAILY_COLUMNS[2:])
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO telemetry_channeldaily ({', '.join(DAILY_COLUMNS)}) "
            f"SELECT {', '.join(DAILY_COLUMNS)} FROM stage_daily "
            f"ON CONFLICT (day, channel_id) DO UPDATE SET {updates}"
        )
        return cursor.rowcount


def refresh_hourly() -> None:
    """Continuous aggregate не пересчитывает загруженную «задним числом» историю сам."""
    with connection.cursor() as cursor:
        cursor.execute("CALL refresh_continuous_aggregate('telemetry_reading_hourly', NULL, NULL)")


def window_start(parquets: list[Path], days: int) -> datetime:
    last = pl.scan_parquet(parquets).select(pl.col("ts").max()).collect().item()
    return last - timedelta(days=days)
