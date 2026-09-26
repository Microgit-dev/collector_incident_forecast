"""
Начальное наполнение вики из apps/wiki/content/*.md. Файл — статья: сверху служебные строки
(`section:`, `title:`, `summary:`, `roles:`, `order:`), после строки `---` — текст в Markdown.
Уже существующие статьи не перезаписываются: их могли поправить в админке (кроме --force).
"""

from __future__ import annotations

from pathlib import Path

from .models import WikiPage, WikiSection

CONTENT = Path(__file__).parent / "content"
SECTIONS = [
    ("start", "Начало работы"),
    ("rules", "Регламенты смены"),
    ("risks", "Риски и карточки"),
    ("roles", "Инструкции по ролям"),
    ("training", "Обучение и учения"),
    ("help", "Справка"),
]


def parse(path: Path) -> dict:
    head, _, body = path.read_text(encoding="utf-8").partition("\n---\n")
    meta = {}
    for line in head.splitlines():
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    return {
        "slug": path.stem.split("-", 1)[1] if path.stem[:2].isdigit() else path.stem,
        "section": meta["section"],
        "title": meta["title"],
        "summary": meta.get("summary", ""),
        "roles": [r.strip() for r in meta.get("roles", "").split(",") if r.strip()],
        "order": int(meta.get("order") or (path.stem[:2] if path.stem[:2].isdigit() else 0)),
        "body": body.strip() + "\n",
    }


def seed(force: bool = False) -> dict:
    sections = {}
    for order, (slug, title) in enumerate(SECTIONS):
        sections[slug], _ = WikiSection.objects.get_or_create(
            slug=slug, defaults={"title": title, "order": order}
        )
    created = updated = 0
    for path in sorted(CONTENT.glob("*.md")):
        data = parse(path)
        section = sections[data.pop("section")]
        page = WikiPage.objects.filter(slug=data["slug"]).first()
        if page is None:
            WikiPage.objects.create(section=section, **data)
            created += 1
        elif force:
            for key, value in data.items():
                setattr(page, key, value)
            page.section = section
            page.save()
            updated += 1
    return {"created": created, "updated": updated}
