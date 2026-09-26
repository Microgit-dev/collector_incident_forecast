from django.shortcuts import get_object_or_404
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from ..selectors import search, visible_pages


def _brief(page) -> dict:
    return {
        "slug": page.slug,
        "title": page.title,
        "summary": page.summary,
        "roles": page.roles,
        "is_published": page.is_published,
    }


class WikiIndexView(APIView):
    """Оглавление по разделам (только статьи для ролей пользователя); ?q= — поиск по тексту."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        pages = visible_pages(request.user)
        q = (request.query_params.get("q") or "").strip()
        if q:
            pages = search(pages, q)
        sections: dict[int, dict] = {}
        for page in pages:
            section = sections.setdefault(
                page.section_id, {"slug": page.section.slug, "title": page.section.title, "pages": []}
            )
            section["pages"].append(_brief(page))
        return Response(
            {
                "sections": list(sections.values()),
                "can_edit": request.user.has_perm("wiki.change_wikipage"),
            }
        )


class WikiPageView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, slug: str):
        page = get_object_or_404(visible_pages(request.user), slug=slug)
        return Response(
            {
                **_brief(page),
                "id": page.pk,
                "section": page.section.title,
                "body": page.body,
                "updated_at": page.updated_at,
                "updated_by": (page.updated_by.get_full_name() or page.updated_by.username)
                if page.updated_by
                else None,
            }
        )
