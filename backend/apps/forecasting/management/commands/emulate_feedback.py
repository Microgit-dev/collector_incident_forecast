"""
Эмуляция разметки диспетчеров на исторических событиях — только для демонстрационного стенда.

На стенде история заканчивается 30.06.2026, а живые решения диспетчеров датируются текущими
днями, поэтому в обучающую выборку они не попадают, и влияние разметки на модель показать
нельзя. Команда создаёт метки так, как их поставил бы диспетчер по правилам разметки:
    «кратковременный сбой питания/связи» — неисправность канала в сутки массового обесточивания
    объекта (≥ 3 потерь питания у других каналов): это не отказ датчика;
    «ложное: неисправность датчика» — неисправность канала, который сбоил 5+ раз за 30 суток:
    подтверждённый отказ.
Метки помечаются источником «эмуляция», их видно и можно отклонить в окне «Обучение».
"""

from django.core.management.base import BaseCommand
from django.db import connection

from apps.forecasting.feedback import seed_rules
from apps.forecasting.models import FeedbackLabel, FeedbackRule

POWER_SQL = """
WITH node_power AS (
    SELECT c.node_id, d.day, sum(d.power_losses) AS power
    FROM telemetry_channeldaily d JOIN assets_channel c ON c.id = d.channel_id
    WHERE d.day BETWEEN %(since)s AND %(until)s
    GROUP BY 1, 2
)
SELECT d.channel_id, d.day
FROM telemetry_channeldaily d
JOIN assets_channel c ON c.id = d.channel_id
JOIN node_power np ON np.node_id = c.node_id AND np.day = d.day
WHERE d.day BETWEEN %(since)s AND %(until)s AND d.faults > 0 AND np.power - d.power_losses >= 3
ORDER BY md5(d.channel_id::text || d.day::text)
LIMIT %(limit)s
"""

FLAKY_SQL = """
SELECT d.channel_id, d.day
FROM telemetry_channeldaily d
WHERE d.day BETWEEN %(since)s AND %(until)s AND d.faults > 0
  AND (SELECT count(*) FROM telemetry_channeldaily p
       WHERE p.channel_id = d.channel_id AND p.faults > 0
         AND p.day BETWEEN d.day - 30 AND d.day - 1) >= 5
ORDER BY md5(d.channel_id::text || d.day::text)
LIMIT %(limit)s
"""


class Command(BaseCommand):
    help = "Демо: эмулированная разметка диспетчеров на исторических событиях (источник «эмуляция»)"

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=400, help="меток каждого вида")
        parser.add_argument("--since", default="2024-01-01")
        parser.add_argument("--until", default="2025-12-31")
        parser.add_argument("--clear", action="store_true", help="удалить прежние эмулированные метки")

    def handle(self, *args, count, since, until, clear, **options):
        seed_rules()
        if clear:
            deleted = FeedbackLabel.objects.filter(source=FeedbackLabel.Source.EMULATED).delete()[0]
            self.stdout.write(f"deleted: {deleted}")
        params = {"since": since, "until": until, "limit": count}
        created = 0
        for sql, code in ((POWER_SQL, "false-power-glitch"), (FLAKY_SQL, "false-sensor-fault")):
            rule = FeedbackRule.objects.get(code=code)
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                rows = cursor.fetchall()
            status = FeedbackLabel.Status.ACCEPTED if rule.auto_accept else FeedbackLabel.Status.PENDING
            FeedbackLabel.objects.bulk_create(
                [
                    FeedbackLabel(
                        source=FeedbackLabel.Source.EMULATED,
                        channel_id=channel_id,
                        label_date=day,
                        effect=rule.effect,
                        weight=rule.weight,
                        status=status,
                        rule=rule,
                    )
                    for channel_id, day in rows
                ]
            )
            created += len(rows)
            self.stdout.write(f"{code}: {len(rows)}")
        self.stdout.write(self.style.SUCCESS(f"emulated labels: {created}"))
