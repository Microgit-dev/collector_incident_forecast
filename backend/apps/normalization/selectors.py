from dataclasses import dataclass

from .domain.engine import Profile, Rule, State, ValueKind
from .models import SensorProfile, StateRule


@dataclass(frozen=True)
class CompiledRegistry:
    profiles: dict[str, Profile]
    global_rules: tuple[Rule, ...]


def _rule(r: StateRule) -> Rule:
    return Rule(r.pattern, State(r.state), r.facet, r.is_regex, r.guarded)


def compiled_registry() -> CompiledRegistry:
    """Снимок профилей и правил из БД для движка. Консьюмер перечитывает его периодически."""
    profiles: dict[str, Profile] = {}
    for p in SensorProfile.objects.prefetch_related("rules"):
        profiles[p.code] = Profile(
            code=p.code,
            value_kind=ValueKind(p.value_kind),
            valid_min=p.valid_min,
            valid_max=p.valid_max,
            drift_tolerance=p.drift_tolerance,
            warn_threshold=p.warn_threshold,
            alarm_threshold=p.alarm_threshold,
            direction=p.direction,
            sentinels=frozenset(str(s) for s in p.sentinels),
            rules=tuple(_rule(r) for r in sorted(p.rules.all(), key=lambda r: r.priority)),
        )
    global_rules = tuple(_rule(r) for r in StateRule.objects.filter(profile=None))
    return CompiledRegistry(profiles, global_rules)
