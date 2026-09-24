"""Генерирует infra/grafana/dashboards/business.json — бизнес-дашборд по витринам TimescaleDB."""

import json
import pathlib
import sys

DS = {"type": "grafana-postgresql-datasource", "uid": "timescaledb"}
EMU = "AND (i.is_emulated = false OR ${emulated:raw})"
panels = []


def case(column, labels):
    return "CASE " + " ".join(f"WHEN {column} = '{k}' THEN '{v}'" for k, v in labels.items()) + f" ELSE {column} END"


TASK = case("task", {"sensor_failure": "Отказ датчика", "gas": "Газ", "flood": "Подтопление", "fire": "Пожар", "intrusion": "НСД"})
TYPE = case(
    "i.type",
    {"sensor_failure": "Отказ датчика", "fire": "Пожар", "gas": "Газ", "flood": "Подтопление", "intrusion": "НСД",
     "power": "Питание", "equipment": "Оборудование", "communication": "Связь"},
)
CAUSE = case(
    "d.cause",
    {"sensor_fault": "Неисправность датчика", "communication": "Потеря связи", "power": "Обесточивание",
     "false_alarm": "Ложное срабатывание", "external": "Внешнее воздействие", "works": "Работы на объекте",
     "real_event": "Реальное событие", "insufficient_data": "Недостаточно данных", "": "Не указано"},
)
_id = [0]


def panel(kind, title, sql, x, y, w, h, fmt="time_series", **extra):
    _id[0] += 1
    p = {
        "id": _id[0],
        "type": kind,
        "title": title,
        "datasource": DS,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": [{"refId": "A", "datasource": DS, "rawQuery": True, "editorMode": "code", "format": fmt, "rawSql": sql}],
    }
    p.update(extra)
    panels.append(p)


def stat(title, sql, x, unit="none", decimals=0, color="blue", w=4):
    panel(
        "stat",
        title,
        sql,
        x,
        0,
        w,
        4,
        fmt="table",
        fieldConfig={"defaults": {"unit": unit, "decimals": decimals, "color": {"mode": "fixed", "fixedColor": color}}},
        options={"colorMode": "value", "graphMode": "none", "reduceOptions": {"calcs": ["lastNotNull"]}},
    )


stat(
    "Карточек за период",
    f"SELECT count(*) FROM incidents_incident i WHERE $__timeFilter(i.opened_at) {EMU}",
    0,
)
stat(
    "Сигналов потока",
    f"SELECT sum(i.signals_count) FROM incidents_incident i WHERE NOT i.is_forecast AND $__timeFilter(i.opened_at) {EMU}",
    4,
)
stat(
    "До решения, медиана",
    "SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM d.decided_at - i.opened_at) / 60) "
    f"FROM incidents_decision d JOIN incidents_incident i ON i.id = d.incident_id WHERE $__timeFilter(i.opened_at) {EMU}",
    8,
    unit="m",
    decimals=1,
    color="green",
)
stat(
    "Эскалаций по таймауту",
    "SELECT count(DISTINCT e.incident_id)::float / nullif((SELECT count(*) FROM incidents_incident i "
    f"WHERE $__timeFilter(i.opened_at) {EMU}), 0) FROM incidents_incident_event_view e",
    12,
    unit="percentunit",
    decimals=1,
    color="purple",
)
stat(
    "Точность журнала прогнозов",
    "SELECT sum((outcome = 'confirmed')::int)::float / nullif(sum((outcome IN ('confirmed', 'not_confirmed'))::int), 0) "
    "FROM forecasting_prediction WHERE $__timeFilter(issued_at) AND is_backtest = ${backtest:raw}",
    16,
    unit="percentunit",
    decimals=1,
    color="orange",
)
stat(
    "Прогноз помог (по решениям)",
    "SELECT sum((d.forecast_useful)::int)::float / nullif(count(d.forecast_useful), 0) FROM incidents_decision d "
    f"JOIN incidents_incident i ON i.id = d.incident_id WHERE i.is_forecast AND $__timeFilter(i.opened_at) {EMU}",
    20,
    unit="percentunit",
    decimals=0,
    color="teal",
)
# эскалации — события с текстом «нет реакции»; простой подзапрос вместо представления
panels[3]["targets"][0]["rawSql"] = (
    "SELECT count(DISTINCT e.incident_id)::float / nullif(count(DISTINCT i.id), 0) "
    "FROM incidents_incident i LEFT JOIN incidents_incidentevent e ON e.incident_id = i.id "
    "AND e.kind = 'escalated' AND e.text LIKE '%нет реакции%' "
    f"WHERE $__timeFilter(i.opened_at) {EMU}"
)

panel(
    "timeseries",
    "Карточки по типу угрозы, в сутки",
    f"SELECT $__timeGroupAlias(i.opened_at, '1d'), {TYPE} AS metric, count(*) AS value FROM incidents_incident i "
    f"WHERE $__timeFilter(i.opened_at) {EMU} GROUP BY 1, 2 ORDER BY 1",
    0,
    4,
    12,
    9,
    fieldConfig={"defaults": {"custom": {"drawStyle": "bars", "stacking": {"mode": "normal"}, "fillOpacity": 80}}},
)
panel(
    "timeseries",
    "Сигналы потока → карточки, в сутки",
    "SELECT $__timeGroupAlias(i.opened_at, '1d'), sum(i.signals_count) AS \"сигналов\", count(*) AS \"карточек\" "
    f"FROM incidents_incident i WHERE NOT i.is_forecast AND $__timeFilter(i.opened_at) {EMU} GROUP BY 1 ORDER BY 1",
    12,
    4,
    12,
    9,
    fieldConfig={"defaults": {"custom": {"drawStyle": "line", "fillOpacity": 10}}},
)
panel(
    "timeseries",
    "Время реакции, медиана по суткам (мин)",
    "SELECT $__timeGroupAlias(i.opened_at, '1d'), "
    "percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM d.decided_at - i.opened_at) / 60) AS \"до решения\", "
    "percentile_cont(0.9) WITHIN GROUP (ORDER BY extract(epoch FROM d.decided_at - i.opened_at) / 60) AS \"до решения, 90 %\" "
    "FROM incidents_incident i JOIN incidents_decision d ON d.incident_id = i.id "
    f"WHERE $__timeFilter(i.opened_at) {EMU} GROUP BY 1 ORDER BY 1",
    0,
    13,
    12,
    8,
    fieldConfig={"defaults": {"unit": "m"}},
)
panel(
    "piechart",
    "Что происходило на самом деле (по решениям)",
    f"SELECT {CAUSE} AS metric, count(*) AS value FROM incidents_decision d "
    f"JOIN incidents_incident i ON i.id = d.incident_id WHERE $__timeFilter(i.opened_at) {EMU} GROUP BY 1",
    12,
    13,
    6,
    8,
    fmt="table",
    options={"legend": {"displayMode": "table", "placement": "right", "values": ["value"]}, "reduceOptions": {"calcs": ["sum"], "values": True}},
)
panel(
    "table",
    "Сотрудники",
    "SELECT concat(u.last_name, ' ', u.first_name) AS \"сотрудник\", count(*) AS \"решений\", "
    "round((percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM d.decided_at - i.opened_at) / 60))::numeric, 1) AS \"до решения, мин\", "
    "round(avg((d.cause <> '')::int)::numeric * 100) AS \"с причиной, %\" "
    "FROM incidents_decision d JOIN incidents_incident i ON i.id = d.incident_id JOIN accounts_user u ON u.id = d.decided_by_id "
    f"WHERE $__timeFilter(i.opened_at) {EMU} GROUP BY 1 ORDER BY 2 DESC",
    18,
    13,
    6,
    8,
    fmt="table",
)
panel(
    "timeseries",
    "Журнал прогнозов: записей в сутки по задаче",
    f"SELECT $__timeGroupAlias(issued_at, '1d'), {TASK} AS metric, count(*) AS value FROM forecasting_prediction "
    "WHERE $__timeFilter(issued_at) AND is_backtest = ${backtest:raw} GROUP BY 1, 2 ORDER BY 1",
    0,
    21,
    12,
    8,
    fieldConfig={"defaults": {"custom": {"drawStyle": "bars", "stacking": {"mode": "normal"}, "fillOpacity": 80}}},
)
panel(
    "table",
    "Качество прогнозов по задачам",
    f"SELECT {TASK} AS \"задача\", count(*) AS \"записей\", sum((outcome = 'confirmed')::int) AS \"подтвердилось\", "
    "sum((outcome = 'not_confirmed')::int) AS \"не подтвердилось\", sum((outcome = 'prevented')::int) AS \"предотвращено\", "
    "round(100.0 * sum((outcome = 'confirmed')::int) / nullif(sum((outcome IN ('confirmed', 'not_confirmed'))::int), 0), 1) AS \"точность, %\" "
    "FROM forecasting_prediction WHERE $__timeFilter(issued_at) AND is_backtest = ${backtest:raw} GROUP BY 1 ORDER BY 2 DESC",
    12,
    21,
    12,
    8,
    fmt="table",
)

dashboard = {
    "uid": "collector-business",
    "title": "Бизнес-показатели: инциденты, диспетчеры, прогнозы",
    "tags": ["collector", "business"],
    "timezone": "browser",
    "schemaVersion": 39,
    "version": 1,
    "refresh": "1m",
    "time": {"from": "now-120d", "to": "now"},
    "templating": {
        "list": [
            {
                "name": "emulated",
                "label": "Эмуляция смен",
                "type": "custom",
                "query": "нет : false, да : true",
                "current": {"text": "да", "value": "true"},
                "options": [],
            },
            {
                "name": "backtest",
                "label": "Журнал прогнозов",
                "type": "custom",
                "query": "оперативный : false, бэктест : true",
                "current": {"text": "бэктест", "value": "true"},
                "options": [],
            },
        ]
    },
    "panels": panels,
}
out = pathlib.Path(sys.argv[1])
out.write_text(json.dumps(dashboard, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
print("panels", len(panels))
