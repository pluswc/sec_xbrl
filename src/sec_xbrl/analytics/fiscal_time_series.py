"""Company-internal fiscal time-series serving model.

This is deliberately downstream of T4-B/T5: it lays out already selected
observations and does not discover filings, choose a recast, calculate a
metric, or normalize a 53-week year.  Fiscal labels are the primary columns;
the real context boundaries remain first-class evidence on every column/cell.
"""

from __future__ import annotations

import hashlib
import marshal
import os
import sqlite3
import tempfile
from collections.abc import Iterable, Iterator, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from itertools import islice
from pathlib import Path
from typing import Any

from sec_xbrl.analytics.company_analysis_panel import CompanyAnalysisPanelResult

FISCAL_TIME_SERIES_VERSION = "analysis-company-fiscal-timeseries-v2"
_PERIOD_CLASSES = frozenset({"QTD_3M", "YTD_6M", "YTD_9M", "FY", "TTM", "INSTANT", "OTHER_DURATION"})


class FiscalTimeSeriesError(ValueError):
    """Raised when a time-series request would hide incompatible history."""


@dataclass(frozen=True, slots=True)
class FiscalPeriod:
    """A requested fiscal column; absent panels become explicit history gaps."""

    fiscal_year: int
    fiscal_quarter: int | None
    period_class: str

    def __post_init__(self) -> None:
        if self.fiscal_year < 1 or self.period_class not in _PERIOD_CLASSES:
            raise FiscalTimeSeriesError("fiscal period requires a valid year and period class")
        if self.fiscal_quarter is not None and self.fiscal_quarter not in {1, 2, 3, 4}:
            raise FiscalTimeSeriesError("fiscal quarter must be 1 through 4 when supplied")


@dataclass(frozen=True, slots=True)
class FiscalTimeSeriesInput:
    """A selected T5 panel plus DEI fiscal metadata from its raw filing.

    ``fiscal_year_end`` is the as-filed DEI value (normally ``--MM-DD``).
    It is intentionally passed in rather than inferred from a revenue fact;
    without it automatic cross-year calendar comparability is fail-closed.
    """

    panel: CompanyAnalysisPanelResult
    fiscal_year_end: str | None


@dataclass(frozen=True, slots=True)
class FiscalTimeSeriesResult:
    """Pivot rows and cells with fiscal-calendar and selection provenance."""

    columns: tuple[dict[str, Any], ...]
    rows: tuple[dict[str, Any], ...]
    cells: tuple[dict[str, Any], ...]
    scope: dict[str, Any]


class FiscalTimeSeriesBuilder:
    """Build a single-company, single-period-class fiscal pivot.

    The caller may request historical columns that have no source panel.  Such
    columns are represented, but no row/value is fabricated: each existing
    analytical row receives a ``MISSING_HISTORY`` cell with provenance-free
    value fields set to ``None``.
    """

    def build(
        self,
        *,
        inputs: Iterable[FiscalTimeSeriesInput],
        expected_periods: Sequence[FiscalPeriod] = (),
    ) -> FiscalTimeSeriesResult:
        prepared = tuple(inputs)
        if not prepared:
            raise FiscalTimeSeriesError("time series requires at least one selected panel")
        scope = _shared_scope(prepared)
        expected = tuple(expected_periods)
        _validate_expected(expected, scope["period_class"])
        columns = _annotate_comparability(
            tuple(sorted(_columns(prepared, expected), key=lambda item: item["column_order_key"]))
        )
        rows: dict[tuple[Any, ...], dict[str, Any]] = {}
        cells: list[dict[str, Any]] = []
        candidates: dict[tuple[str, str], list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]]] = {}
        column_by_period = {
            (item["fiscal_year"], item["fiscal_quarter"], item["period_class"]): item
            for item in columns
        }
        for item in prepared:
            panel = item.panel
            period = (panel.scope["fiscal_year"], panel.scope["fiscal_quarter"], panel.scope["period_class"])
            column = column_by_period[period]
            definitions = {str(row["analysis_line_id"]): row for row in panel.definitions}
            bindings = {str(row["analysis_line_id"]): row for row in panel.bindings}
            for value in panel.values:
                line_id = str(value["analysis_line_id"])
                definition, binding = definitions.get(line_id), bindings.get(line_id)
                if definition is None or binding is None:
                    raise FiscalTimeSeriesError("T5 value has no definition/binding lineage")
                _validate_value_scope(value, panel.scope)
                _validate_derived_q4(value, panel.scope)
                key = _row_key(definition, binding, value)
                row_id = _id("row", key)
                rows.setdefault(row_id, _row(row_id, key, definition, binding, value))
                coordinate = (row_id, str(column["fiscal_time_series_column_id"]))
                candidates.setdefault(coordinate, []).append((definition, binding, value))
        column_by_id = {str(column["fiscal_time_series_column_id"]): column for column in columns}
        for (row_id, column_id), choices in candidates.items():
            cells.append(_resolve_cell(row_id, column_by_id[column_id], choices))
        result = FiscalTimeSeriesResult(
            columns=columns,
            rows=tuple(sorted(rows.values(), key=_row_order)),
            cells=tuple(sorted(cells, key=lambda item: (item["fiscal_time_series_row_id"], item["fiscal_time_series_column_id"]))),
            scope={**scope, "fiscal_time_series_version": FISCAL_TIME_SERIES_VERSION},
        )
        return result

    def build_spilled(
        self,
        *,
        inputs: Iterable[FiscalTimeSeriesInput],
        spill_root: Path,
        expected_periods: Sequence[FiscalPeriod] = (),
    ) -> FiscalTimeSeriesSpilledResult:
        """Build the same ordered records with bounded panel ownership.

        The eager ``build`` API remains the compatibility boundary.  This
        additive path consumes and releases one input panel at a time, keeping
        the row/candidate index in a private disk-backed SQLite temporary
        database.  A typed, checksummed journal remains in ``spill_root`` on
        failure; callers explicitly remove it only after every output table has
        been durably staged.
        """
        expected = tuple(expected_periods)
        spill = _FiscalTimeSeriesSpill(spill_root)
        try:
            iterator = iter(inputs)
            scope: dict[str, Any] | None = None
            by_period: dict[tuple[int, int | None, str], dict[str, Any]] = {}
            consumed = 0
            while True:
                try:
                    item = next(iterator)
                except StopIteration:
                    break
                panel = item.panel
                item_scope = _shared_scope((item,))
                if scope is None:
                    scope = item_scope
                    _validate_expected(expected, scope["period_class"])
                elif any(
                    item_scope[field] != scope[field]
                    for field in ("cik", "period_class", "selection_view", "selection_as_of_date")
                ):
                    raise FiscalTimeSeriesError(
                        "time series cannot mix company, period class, view, or as-of date"
                    )
                period = (
                    panel.scope["fiscal_year"],
                    panel.scope["fiscal_quarter"],
                    panel.scope["period_class"],
                )
                column = _column(period, item.fiscal_year_end, _period_evidence(panel))
                previous = by_period.get(period)
                if previous is not None and previous != column:
                    raise FiscalTimeSeriesError(
                        "one fiscal label has incompatible actual period evidence"
                    )
                by_period[period] = column
                definitions = {
                    str(row["analysis_line_id"]): row for row in panel.definitions
                }
                bindings = {str(row["analysis_line_id"]): row for row in panel.bindings}
                definition = binding = value = key = None
                for value in panel.values:
                    line_id = str(value["analysis_line_id"])
                    definition, binding = definitions.get(line_id), bindings.get(line_id)
                    if definition is None or binding is None:
                        raise FiscalTimeSeriesError(
                            "T5 value has no definition/binding lineage"
                        )
                    _validate_value_scope(value, panel.scope)
                    _validate_derived_q4(value, panel.scope)
                    key = _row_key(definition, binding, value)
                    row_id = _id("row", key)
                    spill.add_row(
                        row_id,
                        _row(row_id, key, definition, binding, value),
                    )
                    spill.add_candidate(
                        row_id,
                        period,
                        definition,
                        binding,
                        value,
                    )
                consumed += 1
                # Do not ask the producer for the next panel while references
                # to this one remain in the consumer frame.
                del definitions, bindings, definition, binding, value, key
                del panel, item, item_scope
            if not consumed or scope is None:
                raise FiscalTimeSeriesError(
                    "time series requires at least one selected panel"
                )
            for period in expected:
                key = (
                    period.fiscal_year,
                    period.fiscal_quarter,
                    period.period_class,
                )
                by_period.setdefault(key, _missing_column(key))
            columns = _annotate_comparability(
                tuple(
                    sorted(
                        by_period.values(),
                        key=lambda item: item["column_order_key"],
                    )
                )
            )
            spill.checkpoint()
            return FiscalTimeSeriesSpilledResult(
                spill=spill,
                columns=columns,
                scope={**scope, "fiscal_time_series_version": FISCAL_TIME_SERIES_VERSION},
            )
        except BaseException:
            spill.close(success=False)
            raise


class FiscalTimeSeriesSpilledResult:
    """Owned record iterators for a disk-spilled fiscal pivot."""

    def __init__(
        self,
        *,
        spill: _FiscalTimeSeriesSpill,
        columns: tuple[dict[str, Any], ...],
        scope: dict[str, Any],
    ) -> None:
        self._spill = spill
        self._columns = columns
        self.scope = scope
        self.counts = {
            "columns": len(columns),
            "rows": spill.row_count(),
            "cells": spill.cell_count(),
        }
        self._closed = False

    @property
    def diagnostic_path(self) -> Path:
        return self._spill.path

    def records(self, name: str) -> Iterator[dict[str, Any]]:
        if self._closed:
            raise FiscalTimeSeriesError("spilled result is closed")
        if name == "columns":
            yield from self._columns
        elif name == "rows":
            yield from self._spill.rows()
        elif name == "cells":
            columns = {
                (
                    row["fiscal_year"],
                    row["fiscal_quarter"],
                    row["period_class"],
                ): row
                for row in self._columns
            }
            yield from self._spill.cells(columns)
        else:
            raise FiscalTimeSeriesError(f"unknown spilled dataset: {name}")

    def dataset(self, name: str) -> Sequence[dict[str, Any]]:
        """Return a re-iterable, bounded sequence view for history staging."""
        if name not in self.counts:
            raise FiscalTimeSeriesError(f"unknown spilled dataset: {name}")
        return _SpilledRecordSequence(self, name)

    def materialize(self) -> FiscalTimeSeriesResult:
        """Materialize for compatibility checks, not bounded production use."""
        return FiscalTimeSeriesResult(
            columns=tuple(self.records("columns")),
            rows=tuple(self.records("rows")),
            cells=tuple(self.records("cells")),
            scope=deepcopy(self.scope),
        )

    def close(self, *, success: bool) -> None:
        if self._closed:
            return
        self._closed = True
        self._spill.close(success=success)


class _SpilledRecordSequence(Sequence[dict[str, Any]]):
    def __init__(self, result: FiscalTimeSeriesSpilledResult, name: str) -> None:
        self._result = result
        self._name = name

    def __len__(self) -> int:
        return self._result.counts[self._name]

    def __iter__(self) -> Iterator[dict[str, Any]]:
        return self._result.records(self._name)

    def __getitem__(self, index: int | slice) -> Any:
        if isinstance(index, slice):
            start, stop, step = index.indices(len(self))
            if step != 1:
                return tuple(self)[index]
            return tuple(islice(iter(self), start, stop))
        normalized = index if index >= 0 else len(self) + index
        if normalized < 0 or normalized >= len(self):
            raise IndexError(index)
        return next(islice(iter(self), normalized, normalized + 1))


def _spill_pack(value: Any) -> bytes:
    """Non-executable typed encoding; never stringify nested provenance."""
    try:
        return b"M" + marshal.dumps(value)
    except ValueError:
        def encode(item: Any) -> Any:
            if isinstance(item, dict):
                return ("dict", [(encode(key), encode(value)) for key, value in item.items()])
            if isinstance(item, (list, tuple)):
                return (type(item).__name__, [encode(value) for value in item])
            if isinstance(item, datetime):
                return ("datetime", (item.isoformat(), item.fold))
            if isinstance(item, (date, time, Decimal)):
                return (type(item).__name__, str(item))
            if isinstance(item, timedelta):
                return ("timedelta", (item.days, item.seconds, item.microseconds))
            return ("scalar", item)

        return b"T" + marshal.dumps(encode(value))


def _spill_unpack(payload: bytes) -> Any:
    if payload[:1] == b"M":
        return marshal.loads(payload[1:])
    if payload[:1] != b"T":
        raise FiscalTimeSeriesError("invalid fiscal time-series spill record")

    def decode(item: Any) -> Any:
        kind, value = item
        if kind == "dict":
            return {decode(key): decode(nested) for key, nested in value}
        if kind in {"list", "tuple"}:
            values = [decode(nested) for nested in value]
            return values if kind == "list" else tuple(values)
        if kind == "datetime":
            return datetime.fromisoformat(value[0]).replace(fold=value[1])
        if kind == "timedelta":
            return timedelta(days=value[0], seconds=value[1], microseconds=value[2])
        if kind in {"date", "time", "Decimal"}:
            return {
                "date": date.fromisoformat,
                "time": time.fromisoformat,
                "Decimal": Decimal,
            }[kind](value)
        if kind == "scalar":
            return value
        raise FiscalTimeSeriesError("invalid fiscal time-series spill scalar")

    return decode(marshal.loads(payload[1:]))


class _FiscalTimeSeriesSpill:
    """Private typed journal plus disposable disk-backed SQLite index."""

    def __init__(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        self.root = root
        self.root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        self.directory = Path(tempfile.mkdtemp(prefix="fiscal-timeseries-", dir=root))
        self.directory_fd = os.open(
            self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        )
        self.path = self.directory / "fiscal-time-series-spill.records"
        self.fd = os.open(
            self.path.name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=self.directory_fd,
        )
        root_stat = os.fstat(self.root_fd)
        directory_stat = os.fstat(self.directory_fd)
        path_stat = os.fstat(self.fd)
        self._bindings = {
            "root": (root_stat.st_dev, root_stat.st_ino),
            "directory": (directory_stat.st_dev, directory_stat.st_ino),
            "path": (path_stat.st_dev, path_stat.st_ino),
        }
        self.db: sqlite3.Connection | None = None
        try:
            self.db = sqlite3.connect("")
            options = {row[0] for row in self.execute("PRAGMA compile_options")}
            if "TEMP_STORE=3" in options:
                raise FiscalTimeSeriesError(
                    "fiscal spill requires SQLite disk-backed temporary storage"
                )
            self.execute("PRAGMA temp_store=FILE")
            if self.execute("PRAGMA temp_store").fetchone() != (1,):
                raise FiscalTimeSeriesError(
                    "fiscal spill temporary storage is not FILE"
                )
            self.execute("PRAGMA cache_size=-2048")
            self.execute("PRAGMA mmap_size=0")
            self.execute("PRAGMA journal_mode=OFF")
            self.execute(
                "CREATE TABLE rows ("
                "row_id TEXT PRIMARY KEY, review INTEGER, label TEXT, record BLOB)"
            )
            self.execute(
                "CREATE TABLE candidates ("
                "ordinal INTEGER PRIMARY KEY, row_id TEXT, column_id TEXT, "
                "period BLOB, record BLOB)"
            )
            self.execute(
                "CREATE INDEX candidate_coordinate "
                "ON candidates(row_id, column_id, ordinal)"
            )
            self._append({"event": "OPEN", "version": "fiscal-timeseries-spill-v1"})
        except BaseException:
            self.close(success=False)
            raise

    def check(self) -> None:
        root_stat = os.fstat(self.root_fd)
        directory_stat = os.fstat(self.directory_fd)
        path_stat = os.fstat(self.fd)
        if (root_stat.st_dev, root_stat.st_ino) != self._bindings["root"]:
            raise FiscalTimeSeriesError("fiscal spill ownership changed")
        if (directory_stat.st_dev, directory_stat.st_ino) != self._bindings["directory"]:
            raise FiscalTimeSeriesError("fiscal spill ownership changed")
        if (path_stat.st_dev, path_stat.st_ino) != self._bindings["path"]:
            raise FiscalTimeSeriesError("fiscal spill ownership changed")
        current_directory = os.stat(
            self.directory.name, dir_fd=self.root_fd, follow_symlinks=False
        )
        current_path = os.stat(
            self.path.name, dir_fd=self.directory_fd, follow_symlinks=False
        )
        if (current_directory.st_dev, current_directory.st_ino) != self._bindings["directory"]:
            raise FiscalTimeSeriesError("fiscal spill ownership changed")
        if (current_path.st_dev, current_path.st_ino) != self._bindings["path"]:
            raise FiscalTimeSeriesError("fiscal spill ownership changed")

    def execute(self, sql: str, parameters: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        self.check()
        if self.db is None:
            raise FiscalTimeSeriesError("fiscal spill is closed")
        return self.db.execute(sql, parameters)

    def _append(self, event: dict[str, Any]) -> None:
        self.check()
        payload = _spill_pack(event)
        frame = len(payload).to_bytes(8, "big") + hashlib.sha256(payload).digest()
        for part in (frame, payload):
            remaining = memoryview(part)
            while remaining:
                written = os.write(self.fd, remaining)
                if written <= 0:
                    raise OSError("fiscal spill journal short write")
                remaining = remaining[written:]

    def add_row(self, row_id: str, record: dict[str, Any]) -> None:
        inserted = self.execute(
            "INSERT OR IGNORE INTO rows(row_id,review,label,record) VALUES(?,?,?,?)",
            (
                row_id,
                int(bool(record.get("mapping_review_required"))),
                str(record.get("label") or ""),
                _spill_pack(record),
            ),
        ).rowcount
        if inserted:
            self._append({"event": "ROW", "row_id": row_id, "record": record})

    def add_candidate(
        self,
        row_id: str,
        period: tuple[int, int | None, str],
        definition: Mapping[str, Any],
        binding: Mapping[str, Any],
        value: Mapping[str, Any],
    ) -> None:
        record = (dict(definition), dict(binding), dict(value))
        self.execute(
            "INSERT INTO candidates(row_id,column_id,period,record) VALUES(?,?,?,?)",
            (
                row_id,
                _id("column", period),
                _spill_pack(period),
                _spill_pack(record),
            ),
        )
        self._append(
            {
                "event": "CANDIDATE",
                "row_id": row_id,
                "period": period,
                "record": record,
            }
        )

    def checkpoint(self) -> None:
        if self.db is None:
            raise FiscalTimeSeriesError("fiscal spill is closed")
        self.db.commit()
        self._append({"event": "CHECKPOINT"})
        os.fsync(self.fd)

    def row_count(self) -> int:
        return int(self.execute("SELECT count(*) FROM rows").fetchone()[0])

    def cell_count(self) -> int:
        return int(
            self.execute(
                "SELECT count(*) FROM ("
                "SELECT 1 FROM candidates GROUP BY row_id,column_id)"
            ).fetchone()[0]
        )

    def rows(self) -> Iterator[dict[str, Any]]:
        for (payload,) in self.execute(
            "SELECT record FROM rows ORDER BY review,label,row_id"
        ):
            yield _spill_unpack(payload)

    def cells(
        self,
        columns: Mapping[tuple[int, int | None, str], Mapping[str, Any]],
    ) -> Iterator[dict[str, Any]]:
        current: tuple[str, str, tuple[int, int | None, str]] | None = None
        choices: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
        for row_id, column_id, period_payload, record_payload in self.execute(
            "SELECT row_id,column_id,period,record FROM candidates "
            "ORDER BY row_id,column_id,ordinal"
        ):
            period = _spill_unpack(period_payload)
            coordinate = (str(row_id), str(column_id), period)
            if current is not None and coordinate != current:
                yield _resolve_cell(current[0], columns[current[2]], choices)
                choices = []
            current = coordinate
            choices.append(_spill_unpack(record_payload))
        if current is not None:
            yield _resolve_cell(current[0], columns[current[2]], choices)

    def close(self, *, success: bool) -> None:
        error: BaseException | None = None
        if self.db is not None:
            try:
                self.db.close()
            except sqlite3.Error as exc:  # pragma: no cover - platform close failure
                error = exc
            self.db = None
        if success and error is None:
            try:
                self.check()
                os.fsync(self.fd)
                os.unlink(self.path.name, dir_fd=self.directory_fd)
                os.rmdir(self.directory.name, dir_fd=self.root_fd)
            except (OSError, FiscalTimeSeriesError) as exc:
                error = exc
        for descriptor in ("fd", "directory_fd", "root_fd"):
            value = getattr(self, descriptor, None)
            if value is not None:
                os.close(value)
                setattr(self, descriptor, None)
        if error is not None:
            raise error


class FiscalTimeSeriesQuery:
    """Defensive matrix reader which makes missing history explicit."""

    def __init__(self, result: FiscalTimeSeriesResult) -> None:
        self._result = deepcopy(result)

    def matrix(self) -> tuple[dict[str, Any], ...]:
        existing = {(str(cell["fiscal_time_series_row_id"]), str(cell["fiscal_time_series_column_id"])): cell for cell in self._result.cells}
        rendered = []
        for row in self._result.rows:
            cells = []
            for column in self._result.columns:
                cell = existing.get((str(row["fiscal_time_series_row_id"]), str(column["fiscal_time_series_column_id"])))
                cells.append(deepcopy(cell) if cell is not None else _missing_cell(row, column))
            rendered.append({"row": deepcopy(row), "cells": tuple(cells)})
        return tuple(rendered)


def _shared_scope(inputs: tuple[FiscalTimeSeriesInput, ...]) -> dict[str, Any]:
    first = inputs[0].panel.scope
    required = ("cik", "period_class", "selection_view", "selection_as_of_date")
    if any(first.get(field) in (None, "") for field in required):
        raise FiscalTimeSeriesError("T5 panel lacks complete company, period, view, or as-of scope")
    if first["period_class"] not in _PERIOD_CLASSES:
        raise FiscalTimeSeriesError("unknown period class")
    for item in inputs[1:]:
        scope = item.panel.scope
        if any(scope.get(field) != first.get(field) for field in required):
            raise FiscalTimeSeriesError("time series cannot mix company, period class, view, or as-of date")
    return {field: first[field] for field in required}


def _validate_expected(periods: tuple[FiscalPeriod, ...], period_class: str) -> None:
    seen = set()
    for period in periods:
        if period.period_class != period_class:
            raise FiscalTimeSeriesError("requested columns cannot mix QTD, YTD, FY, or instant period classes")
        key = (period.fiscal_year, period.fiscal_quarter, period.period_class)
        if key in seen:
            raise FiscalTimeSeriesError("requested fiscal columns cannot repeat")
        seen.add(key)


def _columns(inputs: tuple[FiscalTimeSeriesInput, ...], expected: tuple[FiscalPeriod, ...]) -> tuple[dict[str, Any], ...]:
    by_period: dict[tuple[int, int | None, str], dict[str, Any]] = {}
    for item in inputs:
        scope = item.panel.scope
        period = (scope["fiscal_year"], scope["fiscal_quarter"], scope["period_class"])
        evidence = _period_evidence(item.panel)
        column = _column(period, item.fiscal_year_end, evidence)
        previous = by_period.get(period)
        if previous is not None and previous != column:
            raise FiscalTimeSeriesError("one fiscal label has incompatible actual period evidence")
        by_period[period] = column
    for period in expected:
        key = (period.fiscal_year, period.fiscal_quarter, period.period_class)
        by_period.setdefault(key, _missing_column(key))
    return tuple(by_period.values())


def _period_evidence(panel: CompanyAnalysisPanelResult) -> dict[str, Any]:
    reported = [row for row in panel.values if row.get("value_status") == "REPORTED"]
    if not reported:
        return {"actual_start_date": None, "actual_end_date": None, "actual_instant_date": None, "duration_days": None}
    boundaries = {
        (row.get("context_start_date"), row.get("context_end_date"), row.get("context_instant_date"))
        for row in reported
    }
    # A T5 exploration panel may contain valid disclosure details with a
    # different context boundary from the statement anchor.  Never choose one
    # by label/order and silently apply it to the whole fiscal column.
    if len(boundaries) != 1:
        return {
            "actual_start_date": None, "actual_end_date": None, "actual_instant_date": None,
            "duration_days": None, "actual_period_boundaries": tuple(sorted(boundaries)),
            "period_evidence_status": "MULTIPLE_ACTUAL_PERIOD_BOUNDARIES",
        }
    start, end, instant = next(iter(boundaries))
    return {
        "actual_start_date": start, "actual_end_date": end, "actual_instant_date": instant,
        "duration_days": _duration(start, end), "actual_period_boundaries": tuple(sorted(boundaries)),
        "period_evidence_status": "ONE_ACTUAL_PERIOD_BOUNDARY",
    }


def _column(period: tuple[int, int | None, str], fiscal_year_end: str | None, evidence: Mapping[str, Any]) -> dict[str, Any]:
    fy, fq, period_class = period
    anchor = _fiscal_anchor(fiscal_year_end)
    # The month is stable across a normally rolling 52/53-week calendar.  The
    # actual day remains evidence and its difference is evaluated separately.
    version = f"DEI_FYE_MONTH:{anchor[:2]}" if anchor else "UNKNOWN_DEI_FYE"
    return {
        "fiscal_time_series_column_id": _id("column", period),
        "fiscal_year": fy, "fiscal_quarter": fq, "period_class": period_class,
        "fiscal_label": f"FY{fy}" + (f" Q{fq}" if fq is not None else ""),
        "actual_start_date": evidence["actual_start_date"], "actual_end_date": evidence["actual_end_date"],
        "actual_instant_date": evidence["actual_instant_date"], "duration_days": evidence["duration_days"],
        "actual_period_boundaries": deepcopy(evidence.get("actual_period_boundaries", ())),
        "period_evidence_status": evidence.get("period_evidence_status", "ONE_ACTUAL_PERIOD_BOUNDARY"),
        "fiscal_year_end_as_filed": fiscal_year_end, "fiscal_calendar_version": version,
        "column_status": "AVAILABLE", "column_reason": None,
        "column_order_key": (fy, fq is None, fq or 0, period_class),
    }


def _missing_column(period: tuple[int, int | None, str]) -> dict[str, Any]:
    fy, fq, period_class = period
    return {
        "fiscal_time_series_column_id": _id("column", period), "fiscal_year": fy, "fiscal_quarter": fq,
        "period_class": period_class, "fiscal_label": f"FY{fy}" + (f" Q{fq}" if fq is not None else ""),
        "actual_start_date": None, "actual_end_date": None, "actual_instant_date": None, "duration_days": None,
        "actual_period_boundaries": (), "period_evidence_status": "MISSING_HISTORY",
        "fiscal_year_end_as_filed": None, "fiscal_calendar_version": "UNKNOWN_DEI_FYE",
        "column_status": "MISSING_HISTORY", "column_reason": "NO_SELECTED_PANEL_FOR_REQUESTED_FISCAL_PERIOD",
        "column_order_key": (fy, fq is None, fq or 0, period_class),
    }


def _annotate_comparability(columns: tuple[dict[str, Any], ...]) -> tuple[dict[str, Any], ...]:
    """Attach a visible, non-calculating comparison gate to every column."""
    previous: dict[str, Any] | None = None
    result: list[dict[str, Any]] = []
    for source in columns:
        column = dict(source)
        if column["column_status"] != "AVAILABLE":
            status, reason = "NOT_COMPARABLE", column["column_reason"]
        elif previous is None:
            status, reason = "BASELINE", None
        elif column["period_evidence_status"] != "ONE_ACTUAL_PERIOD_BOUNDARY" or previous["period_evidence_status"] != "ONE_ACTUAL_PERIOD_BOUNDARY":
            status, reason = "REVIEW_REQUIRED", "MULTIPLE_ACTUAL_PERIOD_BOUNDARIES"
        elif "UNKNOWN_DEI_FYE" in {column["fiscal_calendar_version"], previous["fiscal_calendar_version"]}:
            status, reason = "REVIEW_REQUIRED", "MISSING_DEI_FISCAL_YEAR_END"
        elif column["fiscal_calendar_version"] != previous["fiscal_calendar_version"]:
            status, reason = "REVIEW_REQUIRED", "FISCAL_CALENDAR_VERSION_CHANGE"
        elif column["duration_days"] is None or previous["duration_days"] is None:
            status, reason = "REVIEW_REQUIRED", "MISSING_ACTUAL_DURATION"
        else:
            difference = abs(int(column["duration_days"]) - int(previous["duration_days"]))
            if difference == 7:
                status, reason = "DURATION_EXCEPTION_7_DAYS", "ACTUAL_DURATION_DIFFERS_BY_7_DAYS_53_WEEK_NOT_CONFIRMED"
            elif difference > 7:
                status, reason = "REVIEW_REQUIRED", "ACTUAL_DURATION_DIFFERS_BY_MORE_THAN_7_DAYS"
            else:
                status, reason = "COMPARABLE", None
        column["comparability_status"], column["comparability_reason"] = status, reason
        if column["column_status"] == "AVAILABLE": previous = column
        result.append(column)
    return tuple(result)


def _row_key(definition: Mapping[str, Any], binding: Mapping[str, Any], value: Mapping[str, Any]) -> tuple[Any, ...]:
    # T6's strict key is retained: both common GAAP and mapped company custom
    # detail can continue, while reviewed/unmapped facts cannot merge by label.
    review = bool(value.get("mapping_review_required"))
    canonical = value.get("company_canonical_concept_id")
    dimensions = _freeze(value.get("canonical_dimension_signature") or ())
    unit = _freeze((value.get("unit_numerator_measures"), value.get("unit_denominator_measures")))
    # T4's fiscal label is filing metadata.  A filing can also contain prior
    # comparative contexts under that label.  The upstream comparative class
    # is the safe separator; without one the actual boundary remains scoped.
    comparative = value.get("comparative_type")
    boundaries = (value.get("context_start_date"), value.get("context_end_date"), value.get("context_instant_date"))
    family = ("COMPARATIVE", comparative) if comparative else ("UNCLASSIFIED_BOUNDARY", boundaries)
    if canonical and not review and unit != (None, None):
        return ("JOIN", canonical, dimensions, unit, family)
    return ("REVIEW", value.get("source_snapshot_id"), value.get("source_filing_id"), value.get("selected_source_fact_id") or binding.get("analysis_binding_id"))


def _row(row_id: str, key: tuple[Any, ...], definition: Mapping[str, Any], binding: Mapping[str, Any], value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "fiscal_time_series_row_id": row_id, "row_identity": deepcopy(key), "label": definition.get("label"),
        "line_class": definition.get("line_class"), "line_scope": definition.get("line_scope"), "line_kind": definition.get("line_kind"),
        "raw_concept_qname": value.get("raw_concept_qname"), "company_canonical_concept_id": value.get("company_canonical_concept_id"),
        "canonical_dimension_signature": deepcopy(value.get("canonical_dimension_signature")),
        "mapping_review_required": bool(value.get("mapping_review_required")), "first_definition": deepcopy(definition), "first_binding": deepcopy(binding),
    }


def _cell(row_id: str, column: Mapping[str, Any], definition: Mapping[str, Any], binding: Mapping[str, Any], value: Mapping[str, Any]) -> dict[str, Any]:
    status, reason = _comparability(column, value)
    return {
        "fiscal_time_series_cell_id": _id("cell", row_id, column["fiscal_time_series_column_id"], value.get("analysis_line_value_id")),
        "fiscal_time_series_row_id": row_id, "fiscal_time_series_column_id": column["fiscal_time_series_column_id"],
        "value_status": value.get("value_status"), "value_numeric": deepcopy(value.get("value_numeric")), "value_text": deepcopy(value.get("value_text")),
        "comparability_status": status, "comparability_reason": reason,
        "definition": deepcopy(definition), "binding": deepcopy(binding), "value_lineage": deepcopy(value),
    }


def _resolve_cell(row_id: str, column: Mapping[str, Any], candidates: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]]) -> dict[str, Any]:
    """Coalesce navigation duplicates without guessing a conflicting fact.

    Placement is only a preference inside one eligible filing version and
    exact actual period. T4 remains the authority on eligible source versions.
    Every rejected alternative and every graph path stays inspectable.
    """
    ordered = sorted(candidates, key=lambda item: str(item[2].get("analysis_line_value_id")))
    lineage = tuple({"definition": deepcopy(d), "binding": deepcopy(b), "value": deepcopy(v)} for d, b, v in ordered)
    boundaries = {(v.get("context_start_date"), v.get("context_end_date"), v.get("context_instant_date")) for _, _, v in ordered}
    versions = {v.get("source_filing_id") for _, _, v in ordered}
    reason = None
    selected = ordered
    if len(boundaries) > 1:
        reason = "AMBIGUOUS_ACTUAL_PERIOD_BOUNDARIES"
    elif len(versions) > 1:
        reason = "MULTIPLE_SELECTED_FILING_VERSIONS"
    else:
        primary = [item for item in ordered if item[1].get("primary_statement_evidence")]
        selected = primary or ordered
    by_fact: dict[tuple[Any, ...], set[tuple[Any, ...]]] = {}
    for _, _, candidate in ordered:
        fact = (candidate.get("source_snapshot_id"), candidate.get("source_filing_id"), candidate.get("selected_source_fact_id"))
        by_fact.setdefault(fact, set()).add(_value_signature(candidate))
    if any(len(signatures) > 1 for signatures in by_fact.values()):
        reason = "INCONSISTENT_SAME_SOURCE_FACT"
    signatures = {_value_signature(v) for _, _, v in selected}
    if len(signatures) > 1 and reason is None:
        reason = "CONFLICTING_EQUAL_PRIORITY_FACTS"
    definition, binding, value = selected[0]
    cell = _cell(row_id, column, definition, binding, value)
    cell["candidate_lineage"] = lineage
    cell["candidate_count"] = len(ordered)
    cell["source_fact_count"] = len({(v.get("source_snapshot_id"), v.get("source_filing_id"), v.get("selected_source_fact_id")) for _, _, v in ordered})
    cell["resolution_rule"] = "PRIMARY_STATEMENT_THEN_NOTES_WITHIN_SELECTED_VERSION_V1"
    cell["resolution_status"] = "UNAVAILABLE" if reason else "COALESCED" if len(ordered) > 1 else "SINGLE"
    cell["resolution_reason"] = reason
    if reason:
        cell.update(value_status="UNAVAILABLE", value_numeric=None, value_text=None,
                    comparability_status="REVIEW_REQUIRED", comparability_reason=reason,
                    definition=None, binding=None, value_lineage=None)
    return cell


def _value_signature(value: Mapping[str, Any]) -> tuple[Any, ...]:
    numeric = value.get("value_numeric")
    if numeric is not None:
        try:
            numeric = Decimal(str(numeric))
        except InvalidOperation:
            numeric = str(numeric)
    return (value.get("value_status"), numeric, value.get("value_text"), value.get("source_type"), value.get("reported_or_derived"))


def _missing_cell(row: Mapping[str, Any], column: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "fiscal_time_series_row_id": row["fiscal_time_series_row_id"], "fiscal_time_series_column_id": column["fiscal_time_series_column_id"],
        "value_status": column["column_status"] if column["column_status"] in {"MISSING_HISTORY", "UNAVAILABLE"} else "NOT_REPORTED", "value_numeric": None, "value_text": None,
        "comparability_status": "NOT_COMPARABLE", "comparability_reason": column["column_reason"] or "NO_SELECTED_FACT_FOR_ROW_IN_AVAILABLE_PERIOD",
        "definition": None, "binding": None, "value_lineage": None,
    }


def _comparability(column: Mapping[str, Any], value: Mapping[str, Any]) -> tuple[str, str | None]:
    if column["column_status"] != "AVAILABLE":
        return "NOT_COMPARABLE", str(column["column_reason"])
    # Per-cell source facts must agree with the column's actual context.
    actual = (value.get("context_start_date"), value.get("context_end_date"), value.get("context_instant_date"))
    expected = (column["actual_start_date"], column["actual_end_date"], column["actual_instant_date"])
    if column.get("period_evidence_status") == "ONE_ACTUAL_PERIOD_BOUNDARY" and actual != expected:
        return "REVIEW_REQUIRED", "CELL_PERIOD_BOUNDARY_DISAGREES_WITH_FISCAL_COLUMN"
    return str(column.get("comparability_status") or "COMPARABLE"), column.get("comparability_reason")


def _validate_value_scope(value: Mapping[str, Any], scope: Mapping[str, Any]) -> None:
    if value.get("selection_view") != scope["selection_view"] or value.get("selection_as_of_date") != scope["selection_as_of_date"]:
        raise FiscalTimeSeriesError("cell selection provenance disagrees with panel scope")


def _validate_derived_q4(value: Mapping[str, Any], scope: Mapping[str, Any]) -> None:
    derived = value.get("reported_or_derived") == "DERIVED" or value.get("source_type") == "DERIVED_Q4"
    if derived and (scope["fiscal_quarter"] != 4 or scope["period_class"] != "QTD_3M"):
        raise FiscalTimeSeriesError("DERIVED_Q4 is allowed only in a QTD_3M fiscal Q4 column")


def _duration(start: Any, end: Any) -> int | None:
    if not start or not end:
        return None
    try:
        return (date.fromisoformat(str(end)) - date.fromisoformat(str(start))).days
    except ValueError as exc:
        raise FiscalTimeSeriesError("actual context boundary is not ISO date") from exc


def _fiscal_anchor(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if len(text) == 7 and text.startswith("--") and text[2:4].isdigit() and text[5:7].isdigit() and text[4] == "-":
        return text[2:]
    return None


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping): return tuple(sorted((str(key), _freeze(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple)): return tuple(_freeze(item) for item in value)
    return value


def _id(prefix: str, *parts: Any) -> str:
    return f"fiscal-timeseries:{prefix}:{hashlib.sha256(repr(parts).encode()).hexdigest()[:24]}"


def _row_order(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (bool(row.get("mapping_review_required")), str(row.get("label") or ""), str(row["fiscal_time_series_row_id"]))
