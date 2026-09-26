from django.db.models import QuerySet

from apps.analytics.workspace import roles_of

from .models import WikiPage


def visible_pages(user) -> QuerySet[WikiPage]:
    """Опубликованные статьи для ролей пользователя; администратор видит все, включая черновики."""
    qs = WikiPage.objects.select_related("section", "updated_by")
    if user.is_superuser or user.has_perm("wiki.change_wikipage"):
        return qs
    pages = qs.filter(is_published=True)
    allowed = [p.pk for p in pages if not p.roles or set(p.roles) & set(roles_of(user))]
    return pages.filter(pk__in=allowed)


def search(qs: QuerySet[WikiPage], text: str) -> QuerySet[WikiPage]:
    """Все слова запроса без учёта регистра; статей десятки, поэтому ищем в Python — одинаково на любой БД."""
    words = [w.lower() for w in text.split()[:5]]
    found = [p.pk for p in qs if all(w in " ".join((p.title, p.summary, p.body)).lower() for w in words)]
    return qs.filter(pk__in=found)
