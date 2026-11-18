"""Accession-local Inline document inventory; Arelle owns IXDS interpretation."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from lxml import etree

IX = frozenset({"http://www.xbrl.org/2013/inlineXBRL", "http://www.xbrl.org/2008/inlineXBRL"})
XBRLI = "http://www.xbrl.org/2003/instance"
FACTS = frozenset({"nonNumeric", "nonFraction", "fraction"})


class InlineDocumentSetError(ValueError):
    """An accession's Inline set cannot be established unambiguously."""


@dataclass(frozen=True)
class InlineDocumentSet:
    paths: tuple[Path, ...]
    target: str | None
    documents: tuple[dict[str, Any], ...]

    def verify_loaded(self, model: Any) -> tuple[dict[str, Any], ...]:
        """Bind expected package facts to the actual model's document provenance."""
        expected = {doc["name"]: doc for doc in self.documents}
        owners = {}
        for document in model.urlDocs.values():
            if not getattr(document, "filepath", None):
                continue
            path = Path(document.filepath).resolve()
            for name, item in expected.items():
                if path.as_posix().endswith("/" + name):
                    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"] or name in owners:
                        raise InlineDocumentSetError("Inline loaded document identity/hash is ambiguous or changed")
                    owners[name] = path
                    document.sec_source_document = name
        if set(owners) != set(expected):
            raise InlineDocumentSetError("Inline expected/loaded document coverage differs")
        counts = dict.fromkeys(owners.values(), 0)
        for fact in model.facts:
            if bool(getattr(fact, "isTuple", False)):
                continue
            location = Path(fact.modelDocument.filepath).resolve()
            if location not in counts:
                raise InlineDocumentSetError("Inline fact belongs to an undeclared document")
            counts[location] += 1
        result = []
        for name, doc in expected.items():
            if counts[owners[name]] != doc["expected_fact_count"]:
                raise InlineDocumentSetError("Inline expected/loaded document fact coverage differs")
            result.append({**doc, "loaded": True, "loaded_fact_count": counts[owners[name]]})
        return tuple(result)


def verify_package_model(zip_path: Path, entrypoint: str, model: Any) -> tuple[dict[str, Any], ...]:
    """Recompute package expectations even for public direct-ingest callers."""
    from tempfile import TemporaryDirectory

    from sec_xbrl.filing.filing_index import _extract_zip

    with TemporaryDirectory(prefix="sec-ixds-verify-") as temporary:
        root = Path(temporary)
        _extract_zip(zip_path, root)
        selected = discover_inline_set(root, root / entrypoint)
        return selected.verify_loaded(model) if selected else ()



def discover_inline_set(root: Path, entrypoint: Path) -> InlineDocumentSet | None:
    """Select a connected, single-target set from actual Inline resources/references.

    Same suffix/target alone does not authorize merging independent instances.
    Missing or duplicate resources and continuation chains fail before Arelle load.
    """
    documents: dict[Path, tuple[Any, list[Any]]] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".htm", ".html", ".xhtml", ".xml"}:
            continue
        content = path.read_bytes()
        if any(namespace.encode() in content for namespace in IX):
            try:
                etree.fromstring(content, etree.XMLParser(resolve_entities=False, no_network=True))
            except etree.XMLSyntaxError as exc:
                raise InlineDocumentSetError("Inline document is not well-formed XML") from exc
            if b"<!DOCTYPE" in content.upper() or b"<!ENTITY" in content.upper():
                raise InlineDocumentSetError("Inline DTD/entity declarations are not supported")
        tree = etree.fromstring(content, etree.XMLParser(resolve_entities=False, no_network=True, recover=True))
        if tree is None:
            continue
        inline = [node for node in tree.iter() if isinstance(node.tag, str) and etree.QName(node).namespace in IX]
        if inline:
            if any(etree.QName(node).localname == "tuple" for node in inline):
                raise InlineDocumentSetError("Inline tuple corpus requires an explicit supported extraction contract")
            for element in tree.iter():
                if not isinstance(element.tag, str):
                    continue
                if element.get("{http://www.w3.org/XML/1998/namespace}base"):
                    raise InlineDocumentSetError("Inline xml:base requires explicit package resolution support")
                if element.tag not in {"{http://www.xbrl.org/2003/linkbase}schemaRef", "{http://www.xbrl.org/2003/linkbase}linkbaseRef"}:
                    continue
                reference = urlsplit(element.get("{http://www.w3.org/1999/xlink}href", ""))
                if reference.scheme in {"http", "https"}:
                    continue  # Existing offline taxonomy-cache and Arelle resolution gates still apply.
                local = (path.parent / unquote(reference.path)).resolve()
                if reference.scheme or reference.netloc or not reference.path or not local.is_relative_to(root.resolve()) or not local.is_file():
                    raise InlineDocumentSetError("missing or external arbitrary Inline resource document")
            documents[path] = (tree, inline)
    if entrypoint not in documents:
        if documents:
            raise InlineDocumentSetError("primary entry is not part of the accession Inline document set")
        return None
    targets = {node.get("target") for _, nodes in documents.values() for node in nodes
               if etree.QName(node).localname in FACTS | {"references"}}
    if len(targets) != 1:
        raise InlineDocumentSetError("ambiguous or conflicting Inline targets")
    target = targets.pop()
    definitions: dict[str, tuple[Path, Any]] = {}
    for path, (tree, _) in documents.items():
        for node in tree.iter():
            if not isinstance(node.tag, str):
                continue
            qname = etree.QName(node)
            if node.get("id") and (qname.namespace in IX or qname.namespace == XBRLI and qname.localname in {"context", "unit"}):
                identifier = node.get("id")
                if identifier in definitions:
                    raise InlineDocumentSetError("duplicate Inline resource/element ID")
                definitions[identifier] = (path, node)
    edges: dict[Path, set[Path]] = {path: set() for path in documents}
    continuations: dict[str, str] = {}
    for path, (_, nodes) in documents.items():
        for node in nodes:
            for attr in ("fromRefs", "toRefs", "footnoteRefs"):
                for reference in node.get(attr, "").split():
                    if reference not in definitions:
                        raise InlineDocumentSetError("missing Inline relationship/footnote reference")
                    owner, _ = definitions[reference]
                    edges[path].add(owner)
                    edges[owner].add(path)
            for attr, required in (("contextRef", "context"), ("unitRef", "unit"), ("continuedAt", "continuation")):
                reference = node.get(attr)
                if not reference:
                    continue
                if reference not in definitions or etree.QName(definitions[reference][1]).localname != required:
                    raise InlineDocumentSetError("missing or wrong-kind Inline resource reference")
                owner, _ = definitions[reference]
                edges[path].add(owner)
                edges[owner].add(path)
                if attr == "continuedAt" and node.get("id"):
                    continuations[node.get("id")] = reference
            if etree.QName(node).localname in FACTS and not node.get("contextRef"):
                raise InlineDocumentSetError("Inline fact lacks context reference")
    for origin in continuations:
        seen: set[str] = set()
        current = origin
        while current in continuations:
            if current in seen:
                raise InlineDocumentSetError("cyclic Inline continuation")
            seen.add(current)
            current = continuations[current]
    connected, pending = set(), [entrypoint]
    while pending:
        path = pending.pop()
        if path not in connected:
            connected.add(path)
            pending.extend(edges[path] - connected)
    if connected != set(documents):
        raise InlineDocumentSetError("unrelated Inline instances require explicit separate selection")
    paths = (entrypoint, *sorted(connected - {entrypoint}))
    return InlineDocumentSet(paths, target, tuple({"name": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "target": target,
        "expected_fact_count": sum(etree.QName(node).localname in FACTS for node in documents[path][1]),
        "continuation_count": sum(etree.QName(node).localname == "continuation" for node in documents[path][1]),
        "footnote_count": sum(etree.QName(node).localname == "footnote" for node in documents[path][1]),
        "tuple_policy": "UNSUPPORTED_FAIL_CLOSED"} for path in paths))
