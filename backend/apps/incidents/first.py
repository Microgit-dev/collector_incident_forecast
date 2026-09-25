"""
Правило смены: карточку забирает тот, кто первым откликнулся. «Откликнулся» — принял, взял в работу,
отметил шаг чек-листа, принял решение или составил заявку. Второй диспетчер получает отказ с именем
того, кто успел раньше; перехватить карточку может только тот, у кого есть право takeover
(руководитель). Кто первым заметил (открыл карточку) и кто первым откликнулся, фиксируется
один раз и не меняется при освобождении или перехвате: на этом строятся метрики сотрудников.
"""

from __future__ import annotations

from django.utils import timezone

DISPATCHER_ROLES = ("unit_dispatcher", "ods_dispatcher")


def is_dispatcher(user) -> bool:
    return user.groups.filter(name__in=DISPATCHER_ROLES).exists()


def mark_seen(incident, user) -> bool:
    """Первый просмотр карточки диспетчером; гонка двух просмотров решается условным UPDATE."""
    from .models import Incident

    if incident.first_seen_at or not is_dispatcher(user):
        return False
    now = timezone.now()
    won = Incident.objects.filter(pk=incident.pk, first_seen_at__isnull=True).update(
        first_seen_by=user, first_seen_at=now
    )
    if won:
        incident.first_seen_by, incident.first_seen_at = user, now
    return bool(won)


def backfill(Incident, ActionLog, IncidentEvent, Decision, ids=None) -> int:
    """
    Отметки для карточек, созданных до правила (и эмуляции смен): первый просмотр — из журнала
    действий, первый отклик — самое раннее из «принял / взял в работу / решение».
    Принимает классы моделей, чтобы работать и в миграции.
    """
    qs = Incident.objects.filter(responder__isnull=True) | Incident.objects.filter(first_seen_at__isnull=True)
    if ids is not None:
        qs = qs.filter(pk__in=ids)
    targets = {i.pk: i for i in qs.distinct()}
    if not targets:
        return 0
    keys = [str(pk) for pk in targets]
    seen: dict[int, tuple] = {}
    for object_id, ts, user_id in (
        ActionLog.objects.filter(action="incident.view", object_id__in=keys, user__isnull=False)
        .order_by("ts")
        .values_list("object_id", "ts", "user_id")
    ):
        seen.setdefault(int(object_id), (ts, user_id))
    responded: dict[int, tuple] = {}
    for incident_id, ts, user_id in (
        IncidentEvent.objects.filter(
            incident_id__in=targets, kind__in=("acknowledged", "assigned"), actor__isnull=False
        )
        .order_by("ts")
        .values_list("incident_id", "ts", "actor_id")
    ):
        responded.setdefault(incident_id, (ts, user_id))
    for incident_id, ts, user_id in (
        Decision.objects.filter(incident_id__in=targets, decided_by__isnull=False)
        .order_by("decided_at")
        .values_list("incident_id", "decided_at", "decided_by_id")
    ):
        if incident_id not in responded or ts < responded[incident_id][0]:
            responded[incident_id] = (ts, user_id)
    changed = []
    for pk, incident in targets.items():
        dirty = False
        if incident.first_seen_at is None and pk in seen:
            incident.first_seen_at, incident.first_seen_by_id = seen[pk]
            dirty = True
        if incident.responder_id is None and pk in responded:
            incident.responded_at, incident.responder_id = responded[pk]
            dirty = True
        if dirty:
            changed.append(incident)
    Incident.objects.bulk_update(
        changed, ["first_seen_at", "first_seen_by", "responded_at", "responder"], batch_size=1000
    )
    return len(changed)
