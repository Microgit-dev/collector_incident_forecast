"""
Метрики сотрудников и команд за период (ТЗ §8): кто первым заметил и первым откликнулся, как быстро,
насколько решения подтвердились, какая нагрузка на смену, как прошли учебные задания.

Правило смены — «кто первым откликнулся, того и карточка» (apps/incidents/first.py), поэтому главная
метрика диспетчера — отклики первым и доля карточек своей зоны, на которые он откликнулся первым.
Гонка — карточка, которую до отклика открыли двое и больше диспетчеров.

Качество решения проверяется итогом: если карточку физической угрозы (пожар, газ, вода, проникновение)
закрыли как ложную, а в следующие 6 часов на том же объекте открылась карточка той же угрозы — решение
считается поспешным. Технические карточки (датчик, связь, питание) в эту проверку не входят: на
объекте они повторяются сами по себе, и это не ошибка диспетчера. Второй источник — метки обучения
из решений: принял их аналитик или отклонил.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from statistics import median
from zoneinfo import ZoneInfo

from apps.accounts.models import Team, User
from apps.audit.models import ActionLog
from apps.forecasting.models import FeedbackLabel
from apps.incidents.first import DISPATCHER_ROLES
from apps.incidents.models import Decision, DecisionOutcome, Incident, IncidentEvent
from apps.topology.selectors import has_global_scope, user_scope_node

from .efficiency import _share, _stats, incidents_in

MSK = ZoneInfo("Europe/Moscow")
REPEAT_WINDOW = timedelta(hours=6)
CLOSING = (DecisionOutcome.FALSE_ALARM,)
PHYSICAL = ("fire", "gas", "flood", "intrusion")


def _minutes(a: datetime | None, b: datetime | None) -> float | None:
    return round((b - a).total_seconds() / 60, 1) if a and b and b >= a else None


def shift_key(ts: datetime) -> str:
    """Смена: день 08–20 и ночь 20–08 по Москве; ночь относится к дате её начала."""
    local = ts.astimezone(MSK)
    if local.hour >= 20:
        return f"{local.date().isoformat()} ночь"
    if local.hour < 8:
        return f"{(local - timedelta(days=1)).date().isoformat()} ночь"
    return f"{local.date().isoformat()} день"


def _staff_in_scope(user) -> list[User]:
    qs = User.objects.filter(groups__name__in=DISPATCHER_ROLES, is_active=True).select_related(
        "team", "scope_node"
    )
    if not has_global_scope(user):
        node = user_scope_node(user)
        qs = qs.filter(scope_node__path__startswith=node.path) if node else qs.none()
    return list(qs.distinct())


def staff_metrics(user, since: datetime, until: datetime, include_emulated: bool = True) -> dict:
    incidents = list(
        incidents_in(user, since, until, include_emulated)
        .select_related("node")
        .only(
            "id",
            "type",
            "node__path",
            "opened_at",
            "first_seen_by",
            "first_seen_at",
            "responder",
            "responded_at",
            "escalation_level",
            "is_emulated",
        )
    )
    ids = [i.pk for i in incidents]
    by_id = {i.pk: i for i in incidents}

    # кто открывал карточку до отклика — участники гонки
    viewers: dict[int, dict[int, datetime]] = defaultdict(dict)
    for object_id, user_id, ts in (
        ActionLog.objects.filter(
            action="incident.view", object_id__in=[str(i) for i in ids], user__isnull=False
        )
        .order_by("ts")
        .values_list("object_id", "user_id", "ts")
    ):
        viewers[int(object_id)].setdefault(user_id, ts)

    # участники гонки — открыли карточку до отклика (или пока отклика не было)
    racers = {
        i.pk: {u for u, ts in viewers[i.pk].items() if not i.responded_at or ts <= i.responded_at}
        for i in incidents
    }

    decisions: dict[int, list[Decision]] = defaultdict(list)
    for d in Decision.objects.filter(incident_id__in=ids).order_by("decided_at"):
        decisions[d.incident_id].append(d)

    takeovers = Counter()
    releases = Counter()
    for kind, actor, payload in IncidentEvent.objects.filter(
        incident_id__in=ids, kind__in=(IncidentEvent.Kind.ASSIGNED, IncidentEvent.Kind.RELEASED)
    ).values_list("kind", "actor_id", "payload"):
        if kind == IncidentEvent.Kind.RELEASED and actor:
            releases[actor] += 1
        elif (payload or {}).get("takeover_from"):
            takeovers[payload["takeover_from"]] += 1

    # повтор угрозы в течение суток после закрытия — поспешное решение
    later = defaultdict(list)
    for node_id, type_, opened in Incident.objects.filter(
        node_id__in={i.node_id for i in incidents}, opened_at__gte=since, opened_at__lt=until + REPEAT_WINDOW
    ).values_list("node_id", "type", "opened_at"):
        later[(node_id, type_)].append(opened)

    labels = Counter()
    for decided_by, status in (
        FeedbackLabel.objects.filter(incident_id__in=ids)
        .exclude(status=FeedbackLabel.Status.PENDING)
        .values_list("decided_by_id", "status")
    ):
        labels[(decided_by, status)] += 1

    shifts: dict[int, set[str]] = defaultdict(set)
    for user_id, ts in ActionLog.objects.filter(
        ts__gte=since, ts__lt=until, user__isnull=False, action__startswith="incident."
    ).values_list("user_id", "ts"):
        shifts[user_id].add(shift_key(ts))
    for i in incidents:  # эмуляция смен пишет только просмотры — отклик тоже признак смены
        if i.responder_id and i.responded_at:
            shifts[i.responder_id].add(shift_key(i.responded_at))

    from apps.training.models import TrainingSession

    training = defaultdict(list)
    for s in TrainingSession.objects.filter(
        status=TrainingSession.Status.DONE, finished_at__gte=since, finished_at__lt=until
    ):
        training[s.user_id].append(s)

    staff = {u.pk: u for u in _staff_in_scope(user)}
    for i in incidents:
        for uid in (i.responder_id, i.first_seen_by_id):
            if uid and uid not in staff:
                u = User.objects.filter(pk=uid).select_related("team", "scope_node").first()
                if u:
                    staff[uid] = u

    people = []
    for uid, person in staff.items():
        zone = [
            i
            for i in incidents
            if person.scope_node is None or i.node.path.startswith(person.scope_node.path)
        ]
        mine = [i for i in incidents if i.responder_id == uid]
        seen_first = [i for i in incidents if i.first_seen_by_id == uid]
        raced = [i for i in incidents if uid in racers[i.pk] and len(racers[i.pk]) > 1]
        won = [i for i in raced if i.responder_id == uid]
        own_decisions = [d for i in incidents for d in decisions[i.pk] if d.decided_by_id == uid]
        closing = [d for d in own_decisions if d.outcome in CLOSING and by_id[d.incident_id].type in PHYSICAL]
        repeated = [
            d
            for d in closing
            if any(
                d.decided_at < t <= d.decided_at + REPEAT_WINDOW
                for t in later[(by_id[d.incident_id].node_id, by_id[d.incident_id].type)]
            )
        ]
        decision_min = []
        for i in mine:
            first = next((d for d in decisions[i.pk] if d.decided_by_id == uid), None)
            if first:
                decision_min.append(_minutes(i.responded_at, first.decided_at))
        worked = len(shifts.get(uid, ()))
        sessions = training.get(uid, [])
        accepted, rejected = (
            labels[(uid, FeedbackLabel.Status.ACCEPTED)],
            labels[(uid, FeedbackLabel.Status.REJECTED)],
        )
        people.append(
            {
                "user": uid,
                "name": person.get_full_name() or person.get_username(),
                "position": person.position,
                "team": person.team.name if person.team else None,
                "team_id": person.team_id,
                "zone": person.scope_node.name if person.scope_node else "Все объекты",
                "active": bool(mine or seen_first or own_decisions or raced or sessions),
                "zone_cards": len(zone),
                "first_seen": len(seen_first),
                "responded": len(mine),
                "responded_share": _share(len(mine), len(zone)),
                "view_median": _stats([_minutes(i.opened_at, i.first_seen_at) for i in seen_first])["median"],
                "response_median": _stats([_minutes(i.opened_at, i.responded_at) for i in mine])["median"],
                "decision_median": _stats(decision_min)["median"],
                "races": len(raced),
                "races_won": len(won),
                "races_won_share": _share(len(won), len(raced)),
                "decisions": len(own_decisions),
                "closed": len(closing),
                "repeated": len(repeated),
                "quality": _share(len(closing) - len(repeated), len(closing)),
                "labels_accepted": accepted,
                "labels_rejected": rejected,
                "takeovers_lost": takeovers.get(uid, 0),
                "releases": releases.get(uid, 0),
                "shifts": worked,
                "per_shift": round(len(mine) / worked, 1) if worked else None,
                "training_done": len(sessions),
                "training_mistakes": round(sum(s.mistakes for s in sessions) / len(sessions), 1)
                if sessions
                else None,
            }
        )
    people.sort(
        key=lambda p: (-p["responded"], p["response_median"] if p["response_median"] is not None else 1e9)
    )
    rank = 0
    for p in people:
        if p["responded"]:
            rank += 1
            p["rank"] = rank
        else:
            p["rank"] = None

    responded = [i for i in incidents if i.responder_id]
    contested = [i for i in incidents if len(racers[i.pk]) > 1]
    return {
        "period": {"from": since, "to": until},
        "summary": {
            "cards": len(incidents),
            "responded_share": _share(len(responded), len(incidents)),
            "response": _stats([_minutes(i.opened_at, i.responded_at) for i in responded]),
            "contested": len(contested),
            "contested_share": _share(len(contested), len(incidents)),
            "escalated_unanswered": sum(1 for i in incidents if i.escalation_level and not i.responder_id),
            "takeovers": sum(takeovers.values()),
            "emulated": sum(1 for i in incidents if i.is_emulated),
        },
        "people": people,
        "teams": _teams(people, incidents),
    }


def _teams(people: list[dict], incidents: list[Incident]) -> list[dict]:
    by_team: dict[int, list[dict]] = defaultdict(list)
    for p in people:
        if p["team_id"]:
            by_team[p["team_id"]].append(p)
    teams = Team.objects.in_bulk(list(by_team))
    out = []
    for team_id, members in by_team.items():
        team = teams[team_id]
        scope = team.scope_node
        zone = [i for i in incidents if scope is None or i.node.path.startswith(scope.path)]
        member_ids = {m["user"] for m in members}
        answered = [i for i in zone if i.responder_id in member_ids]
        out.append(
            {
                "team": team.name,
                "members": len(members),
                "zone_cards": len(zone),
                "responded": len(answered),
                "responded_share": _share(len(answered), len(zone)),
                "response_median": _stats([_minutes(i.opened_at, i.responded_at) for i in answered])[
                    "median"
                ],
                "escalated_unanswered": sum(1 for i in zone if i.escalation_level and not i.responder_id),
                "quality": _share(
                    sum(m["closed"] - m["repeated"] for m in members), sum(m["closed"] for m in members)
                ),
                "training_done": sum(m["training_done"] for m in members),
            }
        )
    return sorted(out, key=lambda t: -t["responded"])


def my_period(user) -> tuple[datetime, datetime] | None:
    """30 суток до последнего собственного отклика: личные показатели — там, где сотрудник работал."""
    last = (
        Incident.objects.filter(responder=user, responded_at__isnull=False)
        .order_by("-responded_at")
        .values_list("responded_at", flat=True)
        .first()
    )
    if last is None:
        return None
    end = datetime.combine(last.astimezone(MSK).date() + timedelta(days=1), datetime.min.time(), MSK)
    return end - timedelta(days=30), end


def my_metrics(user, since: datetime, until: datetime) -> dict:
    """«Мои показатели»: строка сотрудника, медиана коллег его зоны и место в рейтинге."""
    data = staff_metrics(user, since, until)
    me = next((p for p in data["people"] if p["user"] == user.pk), None)
    colleagues = [p for p in data["people"] if p["user"] != user.pk and p["active"]]

    def med(key):
        values = [p[key] for p in colleagues if p[key] is not None]
        return round(median(values), 1) if values else None

    return {
        "period": data["period"],
        "me": me,
        "rank_of": sum(1 for p in data["people"] if p["rank"]),
        "colleagues": {
            "count": len(colleagues),
            "responded": med("responded"),
            "response_median": med("response_median"),
            "responded_share": med("responded_share"),
            "quality": med("quality"),
        },
    }
