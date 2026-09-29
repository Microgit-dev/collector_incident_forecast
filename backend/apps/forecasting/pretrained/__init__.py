"""
Поставляемые модели: чемпионы, обученные на журналах СМВУ 2019–2026 (обучение до 2025, подбор порогов
на 2025, тест на 2026). Ставятся при инициализации (manage.py bootstrap) для задачи, у которой ещё нет
активной модели, — прогноз работает сразу после развёртывания, без загрузки истории и переобучения.

Рядом лежат артефакт LightGBM (<задача>_<версия>.txt), его описание признаков и порогов (.json) и карточка
модели (<задача>.model.json: метрики, период, параметры — как в реестре моделей). Новая поставляемая
модель: скопировать эти три файла из artifacts/models и карточку из реестра.
"""

from __future__ import annotations

import json
from pathlib import Path

FOLDER = Path(__file__).resolve().parent
TRIGGER = "pretrained"


def cards() -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(FOLDER.glob("*.model.json"))]


def install() -> list[str]:
    """Поставить модели задач без активной версии; вернуть установленные «задача версия»."""
    from ..models import MLModel
    from ..services import activate

    installed = []
    for card in cards():
        if MLModel.objects.filter(task=card["task"], status=MLModel.Status.ACTIVE).exists():
            continue
        artifact = FOLDER / card["file"]
        if not artifact.exists():
            continue
        model, _ = MLModel.objects.update_or_create(
            task=card["task"],
            version=card["version"],
            defaults={
                "algorithm": card["algorithm"],
                "horizon_hours": card["horizon_hours"],
                "status": MLModel.Status.READY,
                "artifact_path": str(artifact),
                "features": card["features"],
                "params": card["params"] | {"trigger": TRIGGER},
                "metrics": card["metrics"],
                "train_period": card["train_period"],
                "notes": "Поставляемая модель (обучена на журналах СМВУ заказчика). " + card["notes"],
            },
        )
        activate(model)
        installed.append(f"{model.task} {model.version}")
    return installed
