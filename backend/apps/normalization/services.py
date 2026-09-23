from django.db import transaction

from .domain.defaults import DEFAULT_PROFILES, DEFAULT_SENTINELS, GLOBAL_RULES
from .models import SensorProfile, StateRule


@transaction.atomic
def seed_default_taxonomy() -> dict[str, int]:
    """Идемпотентно засевает стартовые профили и глобальные правила (правки в админке не затираются)."""
    created_profiles = 0
    for code, spec in DEFAULT_PROFILES.items():
        defaults = {k: v for k, v in spec.items() if k != "sensor_types"}
        defaults["sentinels"] = list(DEFAULT_SENTINELS)
        _, created = SensorProfile.objects.get_or_create(code=code, defaults=defaults)
        created_profiles += created

    created_rules = 0
    for priority, rule in enumerate(GLOBAL_RULES):
        _, created = StateRule.objects.get_or_create(
            profile=None,
            pattern=rule.pattern,
            defaults={
                "state": rule.state,
                "facet": rule.facet,
                "is_regex": rule.is_regex,
                "priority": priority,
            },
        )
        created_rules += created
    return {"profiles": created_profiles, "rules": created_rules}
