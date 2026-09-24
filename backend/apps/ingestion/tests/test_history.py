from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.ingestion import history
from apps.ingestion.models import ImportJob


@pytest.fixture
def data_dir(tmp_path, settings):
    journals = tmp_path / "dataset" / "journals"
    journals.mkdir(parents=True)
    for year in (2020, 2021, 2022):
        (journals / f"ext-journal-{year}.csv").write_text("ид_события\n", encoding="utf-8")
    settings.DATA_DIR = tmp_path
    return tmp_path


def test_available_journals_marks_2021_excluded(db, data_dir):
    journals = {j["year"]: j for j in history.available_journals()}
    assert set(journals) == {2020, 2021, 2022}
    assert journals[2021]["excluded"] and not journals[2020]["excluded"]


def test_plan_creates_year_jobs_and_window_and_blocks_second_run(db, data_dir):
    batch = history.plan([2022, 2020], raw_days=14)
    jobs = ImportJob.objects.filter(batch=batch)
    assert sorted(j.params.get("year", 0) for j in jobs if j.kind == "history") == [2020, 2022]
    assert jobs.get(kind="window").params["raw_days"] == 14
    with pytest.raises(history.ImportBusy):
        history.plan([2020])


def test_stale_running_job_does_not_block(db, data_dir):
    batch = history.plan([2020])
    ImportJob.objects.filter(batch=batch).update(
        status="running", updated_at=timezone.now() - timedelta(hours=1)
    )
    history.plan([2022])
    assert set(ImportJob.objects.filter(batch=batch).values_list("status", flat=True)) == {"failed"}


def test_history_api_requires_permission_and_starts_batch(
    data_dir, tree, make_user, django_capture_on_commit_callbacks
):
    client = APIClient()
    client.force_authenticate(make_user("disp", "ods_dispatcher", tree["district"]))
    assert client.get("/api/v1/ingestion/history/").status_code == 403

    client.force_authenticate(make_user("an", "analyst", tree["district"]))
    assert len(client.get("/api/v1/ingestion/history/").json()["journals"]) == 3
    with (
        patch("apps.ingestion.tasks.run_history_batch.delay") as delay,
        django_capture_on_commit_callbacks(execute=True),
    ):
        response = client.post("/api/v1/ingestion/history/", {"years": [2020], "raw_days": 7}, format="json")
    assert response.status_code == 202 and delay.called
    busy = client.post("/api/v1/ingestion/history/", {"years": [2022]}, format="json")
    assert busy.status_code == 409
