import pytest
from rest_framework.test import APIClient

from apps.wiki.content import CONTENT, parse, seed
from apps.wiki.models import WikiPage, WikiSection


def _client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def pages(db):
    section = WikiSection.objects.create(title="Регламенты", slug="rules")
    WikiPage.objects.create(section=section, slug="first", title="Кто первый", body="# Правило\nтекст")
    WikiPage.objects.create(
        section=section, slug="brigade", title="Бригаде", body="заявки", roles=["technician"]
    )
    WikiPage.objects.create(section=section, slug="draft", title="Черновик", body="x", is_published=False)


def slugs(user):
    return [p["slug"] for s in _client(user).get("/api/v1/wiki/").json()["sections"] for p in s["pages"]]


def test_pages_are_filtered_by_role(pages, tree, make_user):
    disp = make_user("disp", "unit_dispatcher", tree["complex"])
    tech = make_user("tech", "technician", tree["complex"])
    assert slugs(disp) == ["first"]
    assert slugs(tech) == ["brigade", "first"]
    assert _client(disp).get("/api/v1/wiki/brigade/").status_code == 404
    assert _client(tech).get("/api/v1/wiki/brigade/").json()["body"] == "заявки"


def test_admin_sees_drafts_and_can_edit(pages, tree, make_user):
    admin = make_user("adm", "admin")
    body = _client(admin).get("/api/v1/wiki/").json()
    assert body["can_edit"] is True
    assert "draft" in [p["slug"] for s in body["sections"] for p in s["pages"]]


def test_search(pages, tree, make_user):
    disp = make_user("disp", "unit_dispatcher", tree["complex"])
    found = _client(disp).get("/api/v1/wiki/", {"q": "правило"}).json()["sections"]
    assert [p["slug"] for s in found for p in s["pages"]] == ["first"]


def test_seed_does_not_overwrite_edits(db):
    assert seed()["created"] == len(list(CONTENT.glob("*.md")))
    page = WikiPage.objects.order_by("pk").first()
    page.body = "исправлено в админке"
    page.save()
    assert seed() == {"created": 0, "updated": 0}
    page.refresh_from_db()
    assert page.body == "исправлено в админке"


def test_content_files_are_valid():
    sections = {"start", "rules", "risks", "roles", "training", "help"}
    for path in CONTENT.glob("*.md"):
        data = parse(path)
        assert data["section"] in sections and data["title"] and len(data["body"]) > 200, path.name
