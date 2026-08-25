"""Atomic, complete Layer 1 ingestion for one resolved SEC filing package.

This is the production boundary between a resolved FilingRef package and the
immutable Layer 1 snapshot.  It intentionally joins Fact and relationship
materialization from the *same* validated Arelle model so analytical consumers
cannot mistake a partial Fact subset for an as-filed filing.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sec_xbrl.facts.layer1 import Layer1ExtractionError, Layer1Extractor, select_fact_corpus
from sec_xbrl.filing.company_discovery import canonicalize_cik
from sec_xbrl.filing.filing_index import ArelleFilingLoader, ResolvedFiling
from sec_xbrl.relationships.layer1 import RelationshipExtractor


class Layer1IngestionError(RuntimeError):
    """Raised when a filing cannot become a complete immutable Layer 1 snapshot."""


@dataclass(frozen=True, slots=True)
class Layer1SnapshotManifest:
    """Success metadata proving the scope and provenance of one snapshot."""

    schema_version: int
    cik: str
    accession: str
    form: str
    source_url: str
    package_sha256: str
    fact_corpus_source: str
    source_fact_count: int
    materialized_fact_count: int
    concept_count: int
    context_count: int
    unit_count: int
    dimension_fact_count: int
    role_count: int
    relationship_count: int
    layer1_parser_version: str
    relationship_parser_version: str

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True) + "\n"

    @classmethod
    def from_path(cls, path: Path) -> Layer1SnapshotManifest:
        try:
            return cls(**json.loads(path.read_text(encoding="utf-8")))
        except (OSError, TypeError, json.JSONDecodeError) as exc:
            raise Layer1IngestionError(f"invalid Layer 1 snapshot manifest: {path}") from exc


class Layer1Ingestor:
    """Create one complete, immutable Layer 1 snapshot per resolved filing."""

    manifest_name = "layer1_manifest.json"

    def __init__(
        self,
        destination_root: Path,
        *,
        fact_extractor: Layer1Extractor | None = None,
        relationship_extractor: RelationshipExtractor | None = None,
    ) -> None:
        self.destination_root = destination_root
        self.fact_extractor = fact_extractor or Layer1Extractor()
        self.relationship_extractor = relationship_extractor or RelationshipExtractor()

    def snapshot_dir(self, resolved: ResolvedFiling) -> Path:
        filing = resolved.filing
        return self.destination_root / canonicalize_cik(filing.cik) / filing.accession.replace("-", "")

    def ingest(self, resolved: ResolvedFiling, model: Any) -> Layer1SnapshotManifest:
        """Validate and atomically materialize Fact plus relationship tables.

        ``model`` is injected so callers can manage Arelle controller lifetime.
        Use :meth:`load_and_ingest` for the normal resolved-package path.
        """
        self._validate_model(model)
        destination = self.snapshot_dir(resolved)
        if destination.exists():
            raise Layer1IngestionError(f"Layer 1 snapshot already exists: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=f".{resolved.filing.accession.replace('-', '')}.partial-", dir=destination.parent))
        try:
            package_sha256 = _sha256_file(resolved.zip_path)
            facts = self.fact_extractor.extract(
                model,
                resolved.filing,
                source_url=resolved.index.source_url,
                package_hash=package_sha256,
            )
            relationships = self.relationship_extractor.extract(model, resolved.filing)
            facts.write_parquet(temporary)
            relationships.write_parquet(temporary)
            corpus = select_fact_corpus(model)
            manifest = Layer1SnapshotManifest(
                schema_version=1,
                cik=canonicalize_cik(resolved.filing.cik),
                accession=resolved.filing.accession,
                form=resolved.filing.form,
                source_url=resolved.index.source_url,
                package_sha256=package_sha256,
                fact_corpus_source=corpus.source,
                source_fact_count=corpus.source_count,
                materialized_fact_count=len(facts.facts),
                concept_count=len(facts.concepts),
                context_count=len(facts.contexts),
                unit_count=len(facts.units),
                dimension_fact_count=len(facts.dimension_facts),
                role_count=len(relationships.roles),
                relationship_count=len(relationships.relationships),
                layer1_parser_version=self.fact_extractor.parser_version,
                relationship_parser_version=self.relationship_extractor.parser_version,
            )
            (temporary / self.manifest_name).write_text(manifest.to_json(), encoding="utf-8")
            os.replace(temporary, destination)
            return manifest
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise

    def load_and_ingest(
        self, resolved: ResolvedFiling, loader: ArelleFilingLoader, extraction_dir: Path
    ) -> Layer1SnapshotManifest:
        """Load a resolved package then materialize a snapshot from that same model."""
        model = loader.load(resolved, extraction_dir)
        return self.ingest(resolved, model)

    def _validate_model(self, model: Any) -> None:
        """Reject unresolved taxonomies/Inline transforms before any data is written."""
        errors = tuple(str(error) for error in (getattr(model, "errors", None) or ()))
        fatal = tuple(error for error in errors if _is_resolution_or_transform_error(error))
        if fatal:
            raise Layer1IngestionError(
                "Arelle model has unresolved taxonomy or Inline transform errors: " + "; ".join(fatal)
            )
        try:
            corpus = select_fact_corpus(model)
        except Layer1ExtractionError as exc:
            raise Layer1IngestionError(str(exc)) from exc
        unresolved = [
            index
            for index, fact in enumerate(corpus.facts)
            if getattr(fact, "concept", None) is None or getattr(fact, "qname", None) is None
        ]
        if unresolved:
            raise Layer1IngestionError(
                "Fact corpus contains unresolved concepts; taxonomy cache/bootstrap is required "
                f"(first ordinals: {unresolved[:5]})"
            )


def _is_resolution_or_transform_error(error: str) -> bool:
    normalized = error.lower()
    markers = (
        "ioerror",
        "missingreference",
        "unresolved",
        "invalidtransformation",
        "transformation",
        "taxonomy",
        "schemaref",
    )
    return any(marker in normalized for marker in markers)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
