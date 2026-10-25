"""Governed, accession-scoped fiscal-focus corrections for Layer 2.

The registry never changes Layer 1 records.  It returns a corrected filing copy
only after the immutable snapshot and a separately approved evidence record
have matched the declared correction exactly.
"""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sec_xbrl.longitudinal.corpus_release import CorpusSnapshot

_SCHEMA_VERSION_V1 = "layer2-fiscal-focus-corrections-v1"
_SCHEMA_VERSION_V2 = "layer2-fiscal-focus-corrections-v2"
_APPROVAL_SCHEMA_VERSION_V1 = "lead-accession-fiscal-focus-approval-v1"
_APPROVAL_SCHEMA_VERSION_V2 = "lead-hon-exact-two-fiscal-focus-user-approval-v1"
_EVIDENCE_SCHEMA_VERSION_V1 = "lead-accession-fiscal-focus-evidence-supplement-v1"
_EVIDENCE_SCHEMA_VERSION_V2 = "lead-accession-fiscal-focus-evidence-supplement-v2"
_FISCAL_PERIODS = frozenset({"FY", "Q1", "Q2", "Q3", "Q4"})
_ENTRY_KEYS = frozenset({
    "correction_id", "cik", "accession", "form", "primary_document", "report_date",
    "reported", "source", "effective", "approval", "evidence_supplement",
})
_REPORTED_KEYS = frozenset({
    "qname", "fact_id", "context_ref", "fiscal_year", "fiscal_period",
    "context_start_date", "context_end_date",
})
_SOURCE_KEYS = frozenset({
    "package_manifest_sha256", "raw_xbrl_zip_path", "raw_xbrl_zip_sha256",
    "layer1_manifest_sha256",
})
_APPROVAL_KEYS = frozenset({"path", "sha256"})
_EVIDENCE_KEYS = frozenset({"path", "sha256"})
_ATTRIBUTE = re.compile(r"(?:^|\s)([\w:-]+)\s*=\s*(['\"])(.*?)\2", re.DOTALL)
_INLINE_FACT = re.compile(r"<ix:nonNumeric\b([^>]*)>([^<]*)</ix:nonNumeric>", re.DOTALL)
_CONTEXT = re.compile(r"<xbrli:context\b([^>]*)>(.*?)</xbrli:context>", re.DOTALL)


class FiscalFocusCorrectionError(RuntimeError):
    """Raised when governed correction evidence is missing or inconsistent."""


@dataclass(frozen=True, slots=True)
class FiscalFocusCorrectionRegistry:
    """Validated corrections whose use must be exact and complete."""

    artifact_sha256: str
    _entries: Mapping[tuple[str, str], Mapping[str, Any]]
    _consumed: set[tuple[str, str]]

    @classmethod
    def load(cls, path: Path, *, expected_sha256: str) -> FiscalFocusCorrectionRegistry:
        correction_path = Path(path)
        if not correction_path.is_file() or correction_path.is_symlink():
            raise FiscalFocusCorrectionError("correction artifact must be a regular non-symlink file")
        actual_sha256 = _sha256_file(correction_path)
        if not _is_sha256(expected_sha256) or actual_sha256 != expected_sha256:
            raise FiscalFocusCorrectionError("correction artifact SHA-256 mismatch")
        payload = _read_object(correction_path, "correction artifact")
        schema_version = payload.get("schema_version")
        if (
            set(payload) != {"schema_version", "corrections"}
            or schema_version not in {_SCHEMA_VERSION_V1, _SCHEMA_VERSION_V2}
        ):
            raise FiscalFocusCorrectionError("unsupported correction artifact schema")
        raw_entries = payload["corrections"]
        if not isinstance(raw_entries, list) or not raw_entries:
            raise FiscalFocusCorrectionError("correction artifact requires a non-empty corrections list")
        entries: dict[tuple[str, str], Mapping[str, Any]] = {}
        for raw_entry in raw_entries:
            entry = _validate_entry(raw_entry, schema_version=schema_version)
            key = (entry["cik"], entry["accession"])
            if key in entries:
                raise FiscalFocusCorrectionError("duplicate correction accession identity")
            _validate_approval(entry)
            _validate_source_evidence(entry)
            entries[key] = entry
        if schema_version == _SCHEMA_VERSION_V2:
            _validate_v2_group(entries)
        return cls(actual_sha256, entries, set())

    def apply(self, snapshot: CorpusSnapshot, filing: Mapping[str, Any]) -> dict[str, Any]:
        """Return an analytical filing copy, corrected only on an exact match."""
        key = (str(filing.get("cik") or ""), str(filing.get("accession") or ""))
        entry = self._entries.get(key)
        if entry is None:
            return dict(filing)
        if key in self._consumed:
            raise FiscalFocusCorrectionError("correction was consumed more than once")
        reported = entry["reported"]
        source = entry["source"]
        expected_filing = {
            "cik": entry["cik"],
            "accession": entry["accession"],
            "form": entry["form"],
            "primary_document": entry["primary_document"],
            "report_date": entry["report_date"],
            "document_fiscal_year_focus": str(reported["fiscal_year"]),
            "document_fiscal_period_focus": reported["fiscal_period"],
        }
        mismatched = [name for name, expected in expected_filing.items() if filing.get(name) != expected]
        if mismatched:
            raise FiscalFocusCorrectionError(f"correction filing evidence mismatch: {mismatched}")
        if (
            snapshot.input.cik != entry["cik"]
            or snapshot.input.accession != entry["accession"]
            or snapshot.input.manifest_sha256 != source["layer1_manifest_sha256"]
            or snapshot.manifest.package_sha256 != source["raw_xbrl_zip_sha256"]
        ):
            raise FiscalFocusCorrectionError("correction snapshot evidence mismatch")
        corrected = dict(filing)
        corrected["document_fiscal_year_focus"] = str(entry["effective"]["fiscal_year"])
        corrected["reported_document_fiscal_year_focus"] = str(reported["fiscal_year"])
        corrected["effective_document_fiscal_year_focus"] = str(entry["effective"]["fiscal_year"])
        if "fiscal_period" in entry["effective"]:
            corrected["document_fiscal_period_focus"] = entry["effective"]["fiscal_period"]
            corrected["reported_document_fiscal_period_focus"] = reported["fiscal_period"]
            corrected["effective_document_fiscal_period_focus"] = entry["effective"][
                "fiscal_period"
            ]
        corrected["fiscal_focus_correction_id"] = entry["correction_id"]
        corrected["fiscal_focus_correction_artifact_sha256"] = self.artifact_sha256
        corrected["fiscal_focus_correction_provenance"] = {
            "qname": reported["qname"],
            "fact_id": reported["fact_id"],
            "context_ref": reported["context_ref"],
            "context_start_date": reported["context_start_date"],
            "context_end_date": reported["context_end_date"],
            "package_manifest_sha256": source["package_manifest_sha256"],
            "raw_xbrl_zip_sha256": source["raw_xbrl_zip_sha256"],
            "layer1_manifest_sha256": source["layer1_manifest_sha256"],
            "approval_sha256": entry["approval"]["sha256"],
            "evidence_supplement_sha256": entry["evidence_supplement"]["sha256"],
        }
        if "fiscal_period" in entry["effective"]:
            corrected["fiscal_focus_correction_provenance"].update(
                {
                    "reported_lexical_value": _reported_lexical(entry),
                    "effective_lexical_value": _effective_lexical(entry),
                }
            )
        self._consumed.add(key)
        return corrected

    def require_all_consumed(self) -> None:
        missing = sorted(set(self._entries) - self._consumed)
        if missing:
            raise FiscalFocusCorrectionError(f"declared corrections were not consumed: {missing}")


def _validate_entry(raw: object, *, schema_version: object) -> Mapping[str, Any]:
    if not isinstance(raw, dict) or set(raw) != _ENTRY_KEYS:
        raise FiscalFocusCorrectionError("correction entry has invalid fields")
    reported, source, effective, approval, evidence = (
        raw.get("reported"), raw.get("source"), raw.get("effective"), raw.get("approval"),
        raw.get("evidence_supplement"),
    )
    if not isinstance(reported, dict) or set(reported) != _REPORTED_KEYS:
        raise FiscalFocusCorrectionError("reported correction evidence has invalid fields")
    if not isinstance(source, dict) or set(source) != _SOURCE_KEYS:
        raise FiscalFocusCorrectionError("source correction evidence has invalid fields")
    expected_effective_keys = (
        {"fiscal_year"}
        if schema_version == _SCHEMA_VERSION_V1
        else {"fiscal_year", "fiscal_period"}
    )
    if not isinstance(effective, dict) or set(effective) != expected_effective_keys:
        raise FiscalFocusCorrectionError("effective correction has invalid fields")
    if not isinstance(approval, dict) or set(approval) != _APPROVAL_KEYS:
        raise FiscalFocusCorrectionError("approval binding has invalid fields")
    if not isinstance(evidence, dict) or set(evidence) != _EVIDENCE_KEYS:
        raise FiscalFocusCorrectionError("evidence supplement binding has invalid fields")
    required_text = (
        raw["correction_id"], raw["cik"], raw["accession"], raw["form"],
        raw["primary_document"], raw["report_date"], reported["qname"],
        reported["fact_id"], reported["context_ref"], reported["fiscal_period"],
        reported["context_start_date"], reported["context_end_date"], approval["path"],
        evidence["path"], source["raw_xbrl_zip_path"],
    )
    if any(type(value) is not str or not value for value in required_text):
        raise FiscalFocusCorrectionError("correction text fields must be non-empty strings")
    if type(reported["fiscal_year"]) is not int or type(effective["fiscal_year"]) is not int:
        raise FiscalFocusCorrectionError("fiscal years must be integers")
    if reported["fiscal_period"] not in _FISCAL_PERIODS:
        raise FiscalFocusCorrectionError("reported fiscal period is unsupported")
    if schema_version == _SCHEMA_VERSION_V1:
        if reported["fiscal_year"] == effective["fiscal_year"]:
            raise FiscalFocusCorrectionError(
                "effective fiscal year must differ from reported fiscal year"
            )
    else:
        if (
            type(effective["fiscal_period"]) is not str
            or effective["fiscal_period"] not in _FISCAL_PERIODS
        ):
            raise FiscalFocusCorrectionError("effective fiscal period is unsupported")
        year_changed = reported["fiscal_year"] != effective["fiscal_year"]
        period_changed = reported["fiscal_period"] != effective["fiscal_period"]
        if year_changed == period_changed:
            raise FiscalFocusCorrectionError("v2 correction must change exactly one focus field")
        expected_qname = (
            "dei:DocumentFiscalYearFocus"
            if year_changed
            else "dei:DocumentFiscalPeriodFocus"
        )
        if reported["qname"] != expected_qname:
            raise FiscalFocusCorrectionError("correction QName does not identify changed focus")
    hashes = (
        source["package_manifest_sha256"], source["raw_xbrl_zip_sha256"],
        source["layer1_manifest_sha256"], approval["sha256"], evidence["sha256"],
    )
    if any(not _is_sha256(value) for value in hashes):
        raise FiscalFocusCorrectionError("correction hashes must be lowercase SHA-256 values")
    return raw


def _validate_approval(entry: Mapping[str, Any]) -> None:
    approval_path = Path(entry["approval"]["path"])
    if not approval_path.is_file() or approval_path.is_symlink():
        raise FiscalFocusCorrectionError("approval evidence must be a regular non-symlink file")
    if _sha256_file(approval_path) != entry["approval"]["sha256"]:
        raise FiscalFocusCorrectionError("approval evidence SHA-256 mismatch")
    approval = _read_object(approval_path, "approval evidence")
    if "fiscal_period" in entry["effective"]:
        _validate_v2_approval(entry, approval)
        return
    scope = approval.get("scope")
    if (
        approval.get("schema_version") != _APPROVAL_SCHEMA_VERSION_V1
        or approval.get("status") != "USER_APPROVED_BOUNDED_IMPLEMENTATION"
        or approval.get("authorized_by") != "HUMAN_USER"
        or not isinstance(scope, dict)
    ):
        raise FiscalFocusCorrectionError("approval evidence is not an approved bounded correction")
    reported, source = entry["reported"], entry["source"]
    expected_scope = {
        "cik": entry["cik"], "accession": entry["accession"],
        "qname": reported["qname"], "fact_id": reported["fact_id"],
        "context_ref": reported["context_ref"], "reported_year": reported["fiscal_year"],
        "effective_year": entry["effective"]["fiscal_year"],
        "package_manifest_sha256": source["package_manifest_sha256"],
        "raw_xbrl_zip_sha256": source["raw_xbrl_zip_sha256"],
    }
    if any(scope.get(name) != value for name, value in expected_scope.items()):
        raise FiscalFocusCorrectionError("approval scope disagrees with correction entry")


def _validate_source_evidence(entry: Mapping[str, Any]) -> None:
    evidence_path = Path(entry["evidence_supplement"]["path"])
    if not evidence_path.is_file() or evidence_path.is_symlink():
        raise FiscalFocusCorrectionError("evidence supplement must be a regular non-symlink file")
    if _sha256_file(evidence_path) != entry["evidence_supplement"]["sha256"]:
        raise FiscalFocusCorrectionError("evidence supplement SHA-256 mismatch")
    evidence = _read_object(evidence_path, "evidence supplement")
    if "fiscal_period" in entry["effective"]:
        _validate_v2_source_evidence(entry, evidence)
        return
    reported, source = entry["reported"], entry["source"]
    expected_scope = {
        "cik": entry["cik"], "accession": entry["accession"],
        "primary_document": entry["primary_document"], "qname": reported["qname"],
        "fact_id": reported["fact_id"], "context_ref": reported["context_ref"],
        "context_start_date": reported["context_start_date"],
        "context_end_date": reported["context_end_date"],
        "reported_year": reported["fiscal_year"],
        "effective_year": entry["effective"]["fiscal_year"],
        "raw_xbrl_zip_sha256": source["raw_xbrl_zip_sha256"],
        "package_manifest_sha256": source["package_manifest_sha256"],
        "layer1_manifest_sha256": source["layer1_manifest_sha256"],
    }
    source_evidence = evidence.get("source_evidence")
    if (
        evidence.get("schema_version") != _EVIDENCE_SCHEMA_VERSION_V1
        or evidence.get("status")
        != "ROOT_APPROVED_EVIDENCE_DETAIL_WITHIN_HUMAN_APPROVED_SCOPE"
        or evidence.get("authorized_by") != "ROOT_LEAD"
        or evidence.get("human_approval") != entry["approval"]
        or not isinstance(evidence.get("scope"), dict)
        or any(evidence["scope"].get(name) != value for name, value in expected_scope.items())
        or not isinstance(source_evidence, dict)
    ):
        raise FiscalFocusCorrectionError("evidence supplement disagrees with correction entry")
    maximum = source_evidence.get("maximum_prefix_bytes")
    if (
        source_evidence.get("member_name") != entry["primary_document"]
        or type(source_evidence.get("member_size")) is not int
        or not isinstance(source_evidence.get("member_crc32"), str)
        or type(maximum) is not int
        or maximum <= 0
        or maximum > 131_072
        or source_evidence.get("reported_lexical_value") != str(reported["fiscal_year"])
        or source_evidence.get("narrative_fiscal_year") != entry["effective"]["fiscal_year"]
    ):
        raise FiscalFocusCorrectionError("evidence supplement source declaration differs")
    _validate_cached_inline_source(entry, source_evidence, maximum)


def _validate_v2_approval(entry: Mapping[str, Any], approval: Mapping[str, Any]) -> None:
    diagnosis = approval.get("diagnosis")
    corrections = approval.get("corrections")
    if (
        approval.get("schema_version") != _APPROVAL_SCHEMA_VERSION_V2
        or approval.get("status") != "USER_APPROVED_BOUNDED_IMPLEMENTATION"
        or approval.get("authorized_by") != "HUMAN_USER"
        or approval.get("cik") != entry["cik"]
        or not isinstance(diagnosis, dict)
        or set(diagnosis) != {"path", "sha256"}
        or not isinstance(corrections, list)
    ):
        raise FiscalFocusCorrectionError("approval evidence is not an approved v2 correction")
    _validate_bound_file(diagnosis, "diagnosis evidence")
    expected = _focus_identity(entry)
    if sum(item == expected for item in corrections) != 1:
        raise FiscalFocusCorrectionError("approval corrections disagree with correction entry")


def _validate_v2_source_evidence(
    entry: Mapping[str, Any], evidence: Mapping[str, Any]
) -> None:
    corrections = evidence.get("corrections")
    diagnosis = evidence.get("diagnosis")
    if (
        evidence.get("schema_version") != _EVIDENCE_SCHEMA_VERSION_V2
        or evidence.get("status")
        != "ROOT_APPROVED_EVIDENCE_DETAIL_WITHIN_HUMAN_APPROVED_SCOPE"
        or evidence.get("authorized_by") != "ROOT_LEAD"
        or evidence.get("human_approval") != entry["approval"]
        or not isinstance(diagnosis, dict)
        or set(diagnosis) != {"path", "sha256"}
        or not isinstance(corrections, list)
    ):
        raise FiscalFocusCorrectionError("v2 evidence supplement disagrees with correction entry")
    approval = _read_object(Path(entry["approval"]["path"]), "approval evidence")
    if diagnosis != approval.get("diagnosis"):
        raise FiscalFocusCorrectionError("v2 evidence diagnosis differs from approval")
    _validate_bound_file(diagnosis, "diagnosis evidence")
    matches = [
        item
        for item in corrections
        if isinstance(item, dict)
        and item.get("cik") == entry["cik"]
        and item.get("accession") == entry["accession"]
    ]
    if len(matches) != 1:
        raise FiscalFocusCorrectionError("v2 evidence requires one correction record per accession")
    record = matches[0]
    expected_keys = {
        "cik", "accession", "primary_document", "qname", "fact_id", "context_ref",
        "context_start_date", "context_end_date", "reported_lexical_value",
        "effective_lexical_value", "package_manifest_sha256", "raw_xbrl_zip_sha256",
        "layer1_manifest_sha256", "source_evidence",
    }
    source = entry["source"]
    reported = entry["reported"]
    expected = {
        "cik": entry["cik"],
        "accession": entry["accession"],
        "primary_document": entry["primary_document"],
        "qname": reported["qname"],
        "fact_id": reported["fact_id"],
        "context_ref": reported["context_ref"],
        "context_start_date": reported["context_start_date"],
        "context_end_date": reported["context_end_date"],
        "reported_lexical_value": _reported_lexical(entry),
        "effective_lexical_value": _effective_lexical(entry),
        "package_manifest_sha256": source["package_manifest_sha256"],
        "raw_xbrl_zip_sha256": source["raw_xbrl_zip_sha256"],
        "layer1_manifest_sha256": source["layer1_manifest_sha256"],
    }
    if set(record) != expected_keys or any(record.get(name) != value for name, value in expected.items()):
        raise FiscalFocusCorrectionError("v2 evidence correction record differs")
    source_evidence = record.get("source_evidence")
    if not isinstance(source_evidence, dict) or set(source_evidence) != {
        "member_name", "member_size", "member_crc32", "maximum_prefix_bytes"
    }:
        raise FiscalFocusCorrectionError("v2 source evidence has invalid fields")
    maximum = source_evidence.get("maximum_prefix_bytes")
    if (
        source_evidence.get("member_name") != entry["primary_document"]
        or type(source_evidence.get("member_size")) is not int
        or not isinstance(source_evidence.get("member_crc32"), str)
        or type(maximum) is not int
        or maximum <= 0
        or maximum > 131_072
    ):
        raise FiscalFocusCorrectionError("v2 source declaration differs")
    _validate_v2_diagnosis(entry, approval.get("diagnosis"), source_evidence)
    _validate_cached_inline_source(entry, source_evidence, maximum)


def _validate_v2_diagnosis(
    entry: Mapping[str, Any],
    diagnosis_reference: object,
    source_evidence: Mapping[str, Any],
) -> None:
    if not isinstance(diagnosis_reference, dict):
        raise FiscalFocusCorrectionError("v2 diagnosis binding is malformed")
    diagnosis = _read_object(Path(diagnosis_reference["path"]), "diagnosis evidence")
    conflicts = diagnosis.get("source_conflicts")
    proposals = diagnosis.get("proposed_effective_corrections")
    if (
        diagnosis.get("schema_version")
        != "root-hon-original-fiscal-metadata-conflict-diagnosis-v1"
        or diagnosis.get("status") != "SOURCE_CONFLICT_CONFIRMED_NO_CORRECTION_AUTHORIZED"
        or diagnosis.get("verified_by") != "ROOT_LEAD"
        or not isinstance(conflicts, list)
        or not isinstance(proposals, list)
    ):
        raise FiscalFocusCorrectionError("v2 diagnosis evidence has invalid authority fields")
    matching_conflicts = [
        item
        for item in conflicts
        if isinstance(item, dict) and item.get("accession") == entry["accession"]
    ]
    if len(matching_conflicts) != 1:
        raise FiscalFocusCorrectionError("v2 diagnosis requires one source conflict per accession")
    conflict = matching_conflicts[0]
    raw_zip = conflict.get("raw_zip")
    member = conflict.get("member")
    layer1_manifest = conflict.get("layer1_manifest")
    reported = entry["reported"]
    source = entry["source"]
    if (
        not isinstance(raw_zip, dict)
        or set(raw_zip) != {"path", "sha256"}
        or raw_zip.get("path") != source["raw_xbrl_zip_path"]
        or raw_zip.get("sha256") != source["raw_xbrl_zip_sha256"]
        or not isinstance(member, dict)
        or member.get("name") != entry["primary_document"]
        or member.get("size") != source_evidence["member_size"]
        or member.get("crc32") != source_evidence["member_crc32"]
        or conflict.get("bounded_prefix_bytes")
        != source_evidence["maximum_prefix_bytes"]
        or not isinstance(layer1_manifest, dict)
        or layer1_manifest.get("sha256") != source["layer1_manifest_sha256"]
        or conflict.get("package_manifest_sha256") != source["package_manifest_sha256"]
    ):
        raise FiscalFocusCorrectionError("v2 diagnosis source identity differs")
    facts = conflict.get("facts")
    if not isinstance(facts, list):
        raise FiscalFocusCorrectionError("v2 diagnosis facts are malformed")
    matching_facts = [
        item
        for item in facts
        if isinstance(item, dict) and item.get("qname") == reported["qname"]
    ]
    if len(matching_facts) != 1 or matching_facts[0] != {
        "qname": reported["qname"],
        "value": _reported_lexical(entry),
        "fact_id": reported["fact_id"],
        "context_ref": reported["context_ref"],
    }:
        raise FiscalFocusCorrectionError("v2 diagnosis fiscal-focus fact differs")
    contexts = conflict.get("contexts")
    if not isinstance(contexts, dict) or set(contexts) != {reported["context_ref"]}:
        raise FiscalFocusCorrectionError("v2 diagnosis context identity differs")
    context_xml = contexts[reported["context_ref"]]
    if (
        type(context_xml) is not str
        or f"<xbrli:startDate>{reported['context_start_date']}</xbrli:startDate>"
        not in context_xml
        or f"<xbrli:endDate>{reported['context_end_date']}</xbrli:endDate>"
        not in context_xml
    ):
        raise FiscalFocusCorrectionError("v2 diagnosis context period differs")
    expected_proposal = _focus_identity(entry)
    matching_proposals = [
        item
        for item in proposals
        if isinstance(item, dict) and item.get("accession") == entry["accession"]
    ]
    if len(matching_proposals) != 1 or matching_proposals[0] != expected_proposal:
        raise FiscalFocusCorrectionError("v2 diagnosis proposed correction differs")


def _validate_v2_group(entries: Mapping[tuple[str, str], Mapping[str, Any]]) -> None:
    approval_refs = {tuple(sorted(entry["approval"].items())) for entry in entries.values()}
    evidence_refs = {
        tuple(sorted(entry["evidence_supplement"].items())) for entry in entries.values()
    }
    if len(approval_refs) != 1 or len(evidence_refs) != 1:
        raise FiscalFocusCorrectionError("v2 corrections require one approval and evidence supplement")
    first = next(iter(entries.values()))
    approval = _read_object(Path(first["approval"]["path"]), "approval evidence")
    evidence = _read_object(
        Path(first["evidence_supplement"]["path"]), "evidence supplement"
    )
    artifact_identities = {_identity_tuple(_focus_identity(entry)) for entry in entries.values()}
    approval_items = approval.get("corrections")
    evidence_items = evidence.get("corrections")
    if not isinstance(approval_items, list) or any(
        not isinstance(item, dict)
        or set(item) != {"accession", "qname", "reported", "effective"}
        or any(type(item.get(name)) is not str or not item.get(name) for name in item)
        for item in approval_items
    ):
        raise FiscalFocusCorrectionError("approval corrections are malformed")
    approval_identities = {_identity_tuple(item) for item in approval_items}
    if len(approval_identities) != len(approval_items) or approval_identities != artifact_identities:
        raise FiscalFocusCorrectionError("artifact and approval correction identities differ")
    if not isinstance(evidence_items, list) or any(
        not isinstance(item, dict)
        or any(
            type(item.get(name)) is not str or not item.get(name)
            for name in (
                "accession", "qname", "reported_lexical_value",
                "effective_lexical_value",
            )
        )
        for item in evidence_items
    ):
        raise FiscalFocusCorrectionError("evidence corrections are malformed")
    evidence_identities = {
        _identity_tuple(
            {
                "accession": item.get("accession"),
                "qname": item.get("qname"),
                "reported": item.get("reported_lexical_value"),
                "effective": item.get("effective_lexical_value"),
            }
        )
        for item in evidence_items
    }
    if len(evidence_identities) != len(evidence_items) or evidence_identities != artifact_identities:
        raise FiscalFocusCorrectionError("artifact and evidence correction identities differ")


def _focus_identity(entry: Mapping[str, Any]) -> dict[str, str]:
    return {
        "accession": entry["accession"],
        "qname": entry["reported"]["qname"],
        "reported": _reported_lexical(entry),
        "effective": _effective_lexical(entry),
    }


def _identity_tuple(value: Mapping[str, Any]) -> tuple[Any, ...]:
    return tuple(value.get(name) for name in ("accession", "qname", "reported", "effective"))


def _reported_lexical(entry: Mapping[str, Any]) -> str:
    reported = entry["reported"]
    if reported["qname"] == "dei:DocumentFiscalPeriodFocus":
        return reported["fiscal_period"]
    return str(reported["fiscal_year"])


def _effective_lexical(entry: Mapping[str, Any]) -> str:
    effective = entry["effective"]
    if entry["reported"]["qname"] == "dei:DocumentFiscalPeriodFocus":
        return effective["fiscal_period"]
    return str(effective["fiscal_year"])


def _validate_bound_file(reference: Mapping[str, Any], label: str) -> None:
    raw_path = reference.get("path")
    expected_sha256 = reference.get("sha256")
    if (
        type(raw_path) is not str
        or not raw_path
        or not _is_sha256(expected_sha256)
    ):
        raise FiscalFocusCorrectionError(f"{label} binding mismatch")
    path = Path(raw_path)
    if (
        not path.is_file()
        or path.is_symlink()
        or _sha256_file(path) != expected_sha256
    ):
        raise FiscalFocusCorrectionError(f"{label} binding mismatch")


def _validate_cached_inline_source(
    entry: Mapping[str, Any], source_evidence: Mapping[str, Any], maximum: int
) -> None:
    source_path = Path(entry["source"]["raw_xbrl_zip_path"])
    if not source_path.is_file() or source_path.is_symlink():
        raise FiscalFocusCorrectionError("cached source must be a regular non-symlink file")
    if _sha256_file(source_path) != entry["source"]["raw_xbrl_zip_sha256"]:
        raise FiscalFocusCorrectionError("cached source SHA-256 mismatch")
    try:
        with zipfile.ZipFile(source_path) as archive:
            members = [item for item in archive.infolist() if item.filename == entry["primary_document"]]
            if len(members) != 1:
                raise FiscalFocusCorrectionError("cached source member identity differs")
            member = members[0]
            if (
                member.file_size != source_evidence["member_size"]
                or f"{member.CRC:08x}" != source_evidence["member_crc32"]
            ):
                raise FiscalFocusCorrectionError("cached source member metadata differs")
            with archive.open(member) as stream:
                prefix = stream.read(maximum)
    except (OSError, zipfile.BadZipFile, KeyError, RuntimeError) as exc:
        raise FiscalFocusCorrectionError("cached source ZIP is invalid") from exc
    try:
        text = prefix.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FiscalFocusCorrectionError("cached source prefix is not UTF-8") from exc
    reported = entry["reported"]
    facts = []
    for match in _INLINE_FACT.finditer(text):
        attrs = _attributes(match.group(1))
        if attrs.get("id") == reported["fact_id"]:
            facts.append((attrs, match.group(2).strip()))
    if len(facts) != 1 or any(
        facts[0][0].get(name) != expected
        for name, expected in {
            "contextRef": reported["context_ref"], "name": reported["qname"],
            "id": reported["fact_id"],
        }.items()
    ) or facts[0][1] != _reported_lexical(entry):
        raise FiscalFocusCorrectionError("cached inline fiscal-focus fact differs")
    contexts = []
    for match in _CONTEXT.finditer(text):
        attrs = _attributes(match.group(1))
        if attrs.get("id") == reported["context_ref"]:
            contexts.append(match.group(2))
    if len(contexts) != 1:
        raise FiscalFocusCorrectionError("cached inline fiscal-focus context differs")
    body = contexts[0]
    if (
        f"<xbrli:startDate>{reported['context_start_date']}</xbrli:startDate>" not in body
        or f"<xbrli:endDate>{reported['context_end_date']}</xbrli:endDate>" not in body
    ):
        raise FiscalFocusCorrectionError("cached inline fiscal-focus context period differs")


def _attributes(value: str) -> dict[str, str]:
    return {match.group(1): match.group(3) for match in _ATTRIBUTE.finditer(value)}


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FiscalFocusCorrectionError(f"invalid {label}") from exc
    if not isinstance(payload, dict):
        raise FiscalFocusCorrectionError(f"{label} must be a JSON object")
    return payload


def _is_sha256(value: object) -> bool:
    return type(value) is str and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
