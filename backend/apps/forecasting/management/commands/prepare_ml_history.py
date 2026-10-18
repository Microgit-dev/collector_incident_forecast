"""Build an offline ML snapshot using the application's actual normalization and daily aggregates."""

import hashlib
import json
import platform
from pathlib import Path

import polars as pl
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from apps.assets.models import Channel
from apps.assets.services import import_channels
from apps.ingestion import archive
from apps.ingestion.history import EXCLUDED_YEARS
from apps.normalization.services import seed_default_taxonomy
from apps.topology.services import import_objects


def sha256(path: Path) -> str:
    with path.open("rb") as fh:
        return hashlib.file_digest(fh, "sha256").hexdigest()


class Command(BaseCommand):
    help = "Prepare normalized Parquet/daily files for offline ML; use a dedicated migrated SQLite database"

    def add_arguments(self, parser):
        parser.add_argument("--output", type=Path, required=True)
        parser.add_argument(
            "--years", nargs="+", type=int, default=[2019, 2020, 2022, 2023, 2024, 2025, 2026]
        )

    def handle(self, *args, output, years, **options):
        if connection.vendor != "sqlite":
            raise CommandError(
                "Use a dedicated SQLite DATABASE_URL for offline metadata, not the working database"
            )
        db_path = Path(connection.settings_dict["NAME"]).resolve()
        output = output.resolve()
        if not db_path.is_relative_to(output):
            raise CommandError("The dedicated metadata database must be inside --output")
        if EXCLUDED_YEARS.intersection(years):
            raise CommandError("2021 is excluded by the current data methodology")
        base = settings.DATA_DIR / "dataset"
        paths = [base / "journals" / f"ext-journal-{y}.csv" for y in sorted(set(years))]
        refs = [
            base / name for name in ("справочник_объектов_диспетчер.csv", "справочник_каналов_датчиков.csv")
        ]
        missing = [str(p) for p in [*paths, *refs] if not p.is_file()]
        if missing:
            raise CommandError(f"Missing files: {missing}")
        output.mkdir(parents=True, exist_ok=True)
        # Cache provenance includes all code that defines the interpretation of the input data.
        app = Path(__file__).resolve().parents[3]
        sources = [
            app / "ingestion/archive.py",
            app / "normalization/domain/engine.py",
            app / "normalization/domain/defaults.py",
            app / "normalization/services.py",
            app / "assets/services.py",
        ]
        code_hash = hashlib.sha256("".join(sha256(p) for p in sources).encode()).hexdigest()
        manifest_path = output / "manifest.json"
        old = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
        ref_hashes = {p.name: sha256(p) for p in refs}
        if old and (old["normalization_code"] != code_hash or old["references"] != ref_hashes):
            raise CommandError("Normalization/references changed: choose a new snapshot output directory")
        seed_default_taxonomy()
        self.stdout.write(f"objects: {import_objects(refs[0])}")
        self.stdout.write(f"channels: {import_channels(refs[1])}")
        manifest = {
            "normalization_code": code_hash,
            "references": ref_hashes,
            "python": platform.python_version(),
            "polars": pl.__version__,
            "excluded_years": sorted(EXCLUDED_YEARS),
            "years": {},
        }
        for src in paths:
            year = int(src.stem.rsplit("-", 1)[-1])
            self.stdout.write(f"[{year}] fingerprinting input", ending="\n")
            fingerprint = sha256(src)
            normalized = output / "archive" / f"journal_{year}.parquet"
            daily = output / "daily" / f"daily_{year}.parquet"
            previous = old.get("years", {}).get(str(year))
            if (
                previous
                and previous["source_sha256"] == fingerprint
                and normalized.exists()
                and daily.exists()
            ):
                manifest["years"][str(year)] = previous
                self.stdout.write(f"[{year}] reuse complete snapshot")
                continue

            def progress(fraction, stage, year=year):
                self.stdout.write(f"[{year}] {fraction:5.0%} {stage}")
                self.stdout.flush()

            report = archive.normalize_journal(src, normalized, year=year, progress=progress)
            frame = archive.daily_frame(pl.scan_parquet(normalized), progress=progress)
            daily.parent.mkdir(parents=True, exist_ok=True)
            frame.write_parquet(daily, compression="zstd")
            manifest["years"][str(year)] = {
                "source_sha256": fingerprint,
                "source_bytes": src.stat().st_size,
                "quality": report,
                "daily_rows": frame.height,
                "first_day": str(frame["day"].min()),
                "last_day": str(frame["day"].max()),
            }
            # A restart can reuse only fully completed years.
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str))
            self.stdout.write(f"[{year}] complete: {frame.height:,} channel-days")
        rows = list(
            Channel.objects.filter(in_catalog=True, is_active=True).values_list(
                "pk", "node_id", "sensor_type__name"
            )
        )
        pl.DataFrame(
            rows, schema={"channel_id": pl.Int64, "node_id": pl.Int64, "sensor_type": pl.String}, orient="row"
        ).write_parquet(output / "channels.parquet")
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str))
        self.stdout.write(self.style.SUCCESS(f"Snapshot ready: {output}"))
