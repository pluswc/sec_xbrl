"""Pinned screening read model with independently loaded observation evidence."""

from __future__ import annotations

import copy
import gzip
import hashlib
import json
import os
import re
from collections import defaultdict
from functools import lru_cache
from itertools import pairwise
from pathlib import Path
from tempfile import NamedTemporaryFile
from types import SimpleNamespace
from typing import Any

from sec_xbrl.screening.common import (
    canonical_json,
    contained_file,
    real_directory,
    regular_file,
    require_cik,
    safe_write_directory,
)
from sec_xbrl.screening.dataset_v3 import MANIFEST as DATASET_MANIFEST
from sec_xbrl.screening.dataset_v3 import VERSION as DATASET_VERSION
from sec_xbrl.screening.dataset_v3 import ScreeningDatasetV3Reader

VERSION = "screening-runtime-projection-v1"
MANIFEST = "screening_runtime_projection_manifest.json"
_METADATA = (
    "companies", "metadata", "metric_definitions", "metric_support",
    "quarter_definitions", "quarter_support", "quarter_period_inventory",
)
_EVIDENCE = ("trace", "source_lineage")
_SHA256 = re.compile(r"[0-9a-f]{64}")


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _encode(value: Any) -> bytes:
    return canonical_json(value).encode("utf-8")


def _dataset_identity(manifest: dict, data: bytes) -> dict:
    if manifest.get("schema_version") != DATASET_VERSION:
        raise ValueError("runtime projection requires an original screening v3 manifest")
    return {
        "dataset_id": manifest["dataset_id"], "publication_id": manifest["publication_id"],
        "manifest_sha256": _digest(data),
    }


def _blob_path(store: Path, digest: str) -> Path:
    return store / digest[:2] / f"{digest}.json.gz"


def _publish_file(path: Path, data: bytes) -> bool:
    """Install complete bytes once, allowing concurrent identical publishers."""
    with NamedTemporaryFile(dir=path.parent, prefix=".partial-") as temporary:
        temporary.write(data)
        temporary.flush()
        try:
            os.link(temporary.name, path)
        except FileExistsError:
            return False
    return True


def _blob(store: Path, value: Any, receipts: dict[str, str]) -> dict:
    raw = _encode(value)
    digest = _digest(raw)
    target = _blob_path(store, digest)
    if not target.exists():
        safe_write_directory(target.parent, "runtime projection blob partition")
        compressed = gzip.compress(raw, compresslevel=6, mtime=0)
        if _publish_file(target, compressed):
            receipts[digest] = _digest(compressed)
            return {"content_sha256": digest, "sha256": receipts[digest]}
    compressed = contained_file(store, str(target.relative_to(store)), "runtime projection blob").read_bytes()
    compressed_digest = _digest(compressed)
    known = receipts.get(digest)
    if (compressed_digest != known if known is not None else gzip.decompress(compressed) != raw):
        raise ValueError("existing runtime projection blob differs from its address or verified bytes")
    receipts[digest] = compressed_digest
    return {"content_sha256": digest, "sha256": compressed_digest}


def compact_observation(row: dict) -> dict:
    """Remove only the nested evidence fields from a public observation."""
    return {key: value for key, value in row.items() if key not in _EVIDENCE}


def _split(row: dict) -> tuple[dict, dict]:
    evidence = {key: row[key] for key in _EVIDENCE if key in row}
    core = compact_observation(row)
    trace = evidence.get("trace")
    if isinstance(trace, dict) and isinstance(lineage := trace.get("value_lineage"), dict) and lineage.get("filed_date"):
        # The annual period resolver displays these dates without opening detail.
        core["trace"] = {"value_lineage": {"filed_date": lineage["filed_date"]}}
    return core, evidence


def _coordinate(row: dict, quarterly: bool) -> tuple[str, int, int | None]:
    if quarterly:
        return row["cik"], row["calendar_year"], row["calendar_quarter"]
    return row["cik"], row["fiscal_year"], None


def _observation_key(row: dict, quarterly: bool) -> tuple:
    return (row["metric_id"],) if quarterly else (row["metric_id"], row["period_class"], row["view"])


def publish_runtime_projection(
    dataset: Path | str, destination: Path | str, blob_store: Path | str,
    *, reader: ScreeningDatasetV3Reader | None = None,
) -> Path:
    """Publish a read model from a normal verified V3 reader, returning its manifest."""
    return RuntimeProjectionBuilder(blob_store).publish(dataset, destination, reader=reader)


class RuntimeProjectionBuilder:
    """Publish multiple verified V3 sources into the same immutable blob store."""

    def __init__(self, blob_store: Path | str) -> None:
        self._blob_store = Path(os.path.abspath(blob_store))
        self._receipts: dict[str, str] = {}

    def publish(
        self, dataset: Path | str, destination: Path | str, *, reader: ScreeningDatasetV3Reader | None = None,
    ) -> Path:
        return _publish_runtime_projection(dataset, destination, self._blob_store, self._receipts, reader)


def _publish_runtime_projection(
    dataset: Path | str, destination: Path | str, blobs: Path, receipts: dict[str, str],
    reader: ScreeningDatasetV3Reader | None,
) -> Path:
    root = real_directory(Path(dataset), "runtime projection source")
    source = regular_file(root / DATASET_MANIFEST, "runtime projection source manifest").read_bytes()
    source_manifest = json.loads(source)
    identity = _dataset_identity(source_manifest, source)
    if reader is None:
        reader = ScreeningDatasetV3Reader(root)
    if (not isinstance(reader, ScreeningDatasetV3Reader) or reader.root != root
        or reader.manifest != source_manifest or reader._manifest_sha256 != identity["manifest_sha256"]):
        raise ValueError("runtime projection verified reader differs from source manifest")
    original_status = reader.verify_all()

    output = Path(os.path.abspath(destination))
    if (
        output == blobs or output in blobs.parents or blobs in output.parents
        or root in (output, *output.parents, blobs, *blobs.parents)
        or output in root.parents or blobs in root.parents
    ):
        raise ValueError("runtime projection source, destination and blob store must be separate")
    store = safe_write_directory(blobs, "runtime projection blob store")
    metadata = {key: getattr(reader, key) for key in _METADATA}
    metadata["quarter_manifest"] = reader.quarterly.manifest
    metadata["status"] = original_status
    indexes = {}
    for frequency, rows in (("annual", reader.observations), ("quarterly", reader.quarter_observations)):
        partitions = defaultdict(list)
        for position, row in enumerate(rows):
            partitions[_coordinate(row, frequency == "quarterly")].append((position, row))
        declarations = []
        for coordinate, group in sorted(partitions.items()):
            cores, evidence = zip(*(_split(row) for _, row in group), strict=True)
            declarations.append({
                "coordinate": coordinate,
                "positions": [position for position, _ in group],
                "core": _blob(store, cores, receipts), "evidence": _blob(store, evidence, receipts),
            })
        indexes[frequency] = declarations

    metadata_ref = _blob(store, metadata, receipts)
    manifest = {
        "schema_version": VERSION, "source": identity, "blob_store": str(store),
        "metadata": metadata_ref, "observations": indexes,
    }
    path = safe_write_directory(output, "runtime projection destination") / MANIFEST
    data = _encode(manifest) + b"\n"
    if not _publish_file(path, data) and regular_file(path, "runtime projection manifest").read_bytes() != data:
        raise ValueError("runtime projection destination already contains a different publication")
    return path


class ScreeningRuntimeProjection:
    """Exact source identity with lazily opened, verified observation partitions."""

    def __init__(self, dataset: Path | str, pin: dict[str, str]) -> None:
        self.root = real_directory(Path(dataset), "runtime projection source")
        data = regular_file(self.root / DATASET_MANIFEST, "runtime projection source manifest").read_bytes()
        self.manifest = json.loads(data)
        identity = _dataset_identity(self.manifest, data)
        self._manifest_sha256 = identity["manifest_sha256"]
        self.publication_id = identity["publication_id"]
        if set(pin) != {"path", "sha256"} or not Path(pin["path"]).is_absolute():
            raise ValueError("runtime projection requires an absolute manifest path and SHA-256")
        projection = regular_file(Path(pin["path"]), "runtime projection manifest").read_bytes()
        if _digest(projection) != pin["sha256"]:
            raise ValueError("runtime projection manifest differs from pinned digest")
        declaration = json.loads(projection)
        if (
            set(declaration) != {"schema_version", "source", "blob_store", "metadata", "observations"}
            or declaration["schema_version"] != VERSION or declaration["source"] != identity
            or not Path(declaration["blob_store"]).is_absolute()
        ):
            raise ValueError("runtime projection manifest differs from original publication")
        self._store = real_directory(Path(declaration["blob_store"]), "runtime projection blob store")
        metadata = self._read_blob(declaration["metadata"])
        for key in _METADATA:
            setattr(self, key, metadata[key])
        self.quarterly = SimpleNamespace(manifest=metadata["quarter_manifest"])
        self._status = metadata["status"]
        if (self._status["publication_id"], self._status["dataset_id"]) != (self.publication_id, identity["dataset_id"]):
            raise ValueError("runtime projection metadata differs from original publication")
        self._partitions = self._index(declaration["observations"])
        self._core = lru_cache(maxsize=None)(self._read_core)
        self._evidence = lru_cache(maxsize=8)(self._read_evidence)

    def _read_blob(self, reference: dict) -> Any:
        if (
            set(reference) != {"content_sha256", "sha256"}
            or any(not isinstance(value, str) or not _SHA256.fullmatch(value) for value in reference.values())
        ):
            raise ValueError("invalid runtime projection blob reference")
        relative = _blob_path(Path(), reference["content_sha256"])
        compressed = contained_file(self._store, str(relative), "runtime projection blob").read_bytes()
        if _digest(compressed) != reference["sha256"]:
            raise ValueError("runtime projection blob differs from pinned digest")
        raw = gzip.decompress(compressed)
        if _digest(raw) != reference["content_sha256"]:
            raise ValueError("runtime projection blob differs from content address")
        return json.loads(raw)

    def _index(self, declarations: dict) -> dict:
        if set(declarations) != {"annual", "quarterly"}:
            raise ValueError("runtime projection observation frequencies differ")
        ciks = {row["cik"] for row in self.companies}
        partitions = {}
        for frequency, items in declarations.items():
            quarterly = frequency == "quarterly"
            result = {}
            positions = []
            for item in items:
                cik, year, quarter = item["coordinate"]
                coordinate = (cik, year, quarter)
                ranks = item["positions"]
                if (
                    require_cik(cik) not in ciks or type(year) is not int
                    or (quarterly and (type(quarter) is not int or not 1 <= quarter <= 4))
                    or (not quarterly and quarter is not None)
                    or coordinate in result or not ranks
                    or any(type(rank) is not int or rank < 0 for rank in ranks)
                    or any(a >= b for a, b in pairwise(ranks))
                ):
                    raise ValueError("invalid runtime projection observation partition")
                result[coordinate] = item
                positions.extend(ranks)
            if sorted(positions) != list(range(len(positions))) or (
                quarterly and len(positions) != self._status["quarter_observation_count"]
            ):
                raise ValueError("runtime projection observation ordering differs")
            partitions[quarterly] = result
        return partitions

    def _read_core(self, quarterly: bool, coordinate: tuple) -> tuple[list[dict], dict[tuple, int]]:
        partition = self._partitions[quarterly][coordinate]
        rows = self._read_blob(partition["core"])
        indexes = {_observation_key(row, quarterly): index for index, row in enumerate(rows)}
        if (
            len(rows) != len(partition["positions"]) or len(indexes) != len(rows)
            or any(_coordinate(row, quarterly) != coordinate for row in rows)
        ):
            raise ValueError("runtime projection core differs from partition coordinates")
        return rows, indexes

    def _read_evidence(self, quarterly: bool, coordinate: tuple) -> list[dict]:
        partition = self._partitions[quarterly][coordinate]
        rows = self._read_blob(partition["evidence"])
        if len(rows) != len(partition["positions"]) or any(
            not isinstance(row, dict) or not set(row) <= set(_EVIDENCE) for row in rows
        ):
            raise ValueError("runtime projection evidence differs from partition coordinates")
        return rows

    def rows(
        self, *, quarterly: bool = False, cik: str | None = None, metric_id: str | None = None,
        year: int | None = None, quarter: int | None = None,
    ) -> list[dict]:
        """Select core rows in their original publication order."""
        results = []
        for coordinate, partition in self._partitions[quarterly].items():
            row_cik, row_year, row_quarter = coordinate
            if ((cik is not None and cik != row_cik) or (year is not None and year != row_year)
                or (quarter is not None and quarter != row_quarter)):
                continue
            rows, _ = self._core(quarterly, coordinate)
            results.extend(
                (position, row)
                for position, row in zip(partition["positions"], rows, strict=True)
                if metric_id is None or row["metric_id"] == metric_id
            )
        return [row for _, row in sorted(results, key=lambda pair: pair[0])]

    def hydrate(self, row: dict, *, quarterly: bool = False) -> dict:
        """Join only the selected row, retaining scalar overrides by callers."""
        coordinate = _coordinate(row, quarterly)
        _, indexes = self._core(quarterly, coordinate)
        evidence = self._evidence(quarterly, coordinate)[indexes[_observation_key(row, quarterly)]]
        return row | evidence

    def company(self, cik: str) -> dict:
        matches = [row for row in self.companies if row["cik"] == cik]
        if len(matches) != 1:
            raise ValueError("company is not uniquely prepared")
        return copy.deepcopy(matches[0])

    def verify_all(self) -> dict:
        """Match the V3 status contract without opening observation evidence."""
        return copy.deepcopy(self._status)


def observation_rows(
    reader: Any, *, quarterly: bool = False, cik: str | None = None, metric_id: str | None = None,
    year: int | None = None, quarter: int | None = None, latest: bool = False,
) -> list[dict]:
    if latest and callable(getattr(reader, "latest_rows", None)):
        return reader.latest_rows(quarterly=quarterly, cik=cik, metric_id=metric_id, year=year, quarter=quarter)
    if _core_reader(reader):
        return reader.rows(quarterly=quarterly, cik=cik, metric_id=metric_id, year=year, quarter=quarter)
    rows = getattr(reader, "quarter_observations", []) if quarterly else reader.observations
    year_field = "calendar_year" if quarterly else "fiscal_year"
    return [
        row for row in rows
        if (cik is None or row["cik"] == cik)
        and (metric_id is None or row["metric_id"] == metric_id)
        and (year is None or row[year_field] == year)
        and (quarter is None or row["calendar_quarter"] == quarter)
    ]


def hydrate_observation(reader: Any, row: dict, *, quarterly: bool = False) -> dict:
    return reader.hydrate(row, quarterly=quarterly) if _core_reader(reader) else row


def _core_reader(reader: Any) -> bool:
    from sec_xbrl.screening.cohort_union import ScreeningCohortUnionReader
    from sec_xbrl.screening.governed_delta import ScreeningGovernedDeltaReader

    return isinstance(reader, (ScreeningRuntimeProjection, ScreeningCohortUnionReader, ScreeningGovernedDeltaReader))
