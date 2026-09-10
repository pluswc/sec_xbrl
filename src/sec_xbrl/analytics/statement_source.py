"""Prepare original HTML rows and separate PRE/CAL/DEF evidence from attested Raw.

XML is inspected only to bind existing Raw IDs, not to reinterpret XBRL values.
All numeric values, periods and dimensions come from the verified snapshot.
"""
from __future__ import annotations

import hashlib
import json
import re
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any

from lxml import etree, html

from sec_xbrl.analytics.statement_structure import (
    NETWORK_FIELDS,
    finite_decimal,
    materialize_signed_calculation_checks,
    stable_id,
)
from sec_xbrl.discovery.statement import _qualifying_statement_role
from sec_xbrl.facts.layer1 import _stable_id
from sec_xbrl.periods.logic import PeriodClassifier


def read_primary_document(*, entry: dict, filing: dict, package_root: Path) -> bytes:
    """Verify declared filing, package manifest and ZIP before reading its member."""
    ref = entry["filing"]
    directory = package_root / ref["cik"] / ref["accession"].replace("-", "")
    manifest = json.loads((directory / "manifest.json").read_text())
    if any(manifest[k] != ref[k] or filing[k] != ref[k] for k in ("cik", "accession", "form")):
        raise ValueError("source package identity mismatch")
    artifact = next(a for a in manifest["artifacts"] if a["filename"] == ref["accession"] + "-xbrl.zip")
    path = directory / artifact["filename"]
    data = path.read_bytes()
    if len(data) != artifact["byte_size"] or hashlib.sha256(data).hexdigest() != artifact["sha256"] or artifact["sha256"] != filing["package_hash"]:
        raise ValueError("source package bytes do not match attested Raw")
    if ref["primary_document"] != filing["primary_document"]:
        raise ValueError("primary document differs from upstream discovery")
    with zipfile.ZipFile(path) as archive:
        matches = [n for n in archive.namelist() if n == ref["primary_document"]]
        if len(matches) != 1:
            raise ValueError("declared primary member must occur exactly once")
        return archive.read(matches[0])


def prepare_filing(*, snapshot: Any, document: bytes, as_of: str, supplemental_relationships: list[dict] | None = None) -> dict[str, list[dict]]:
    filing = dict(next(iter(snapshot.records("filing"))))
    concepts = {r["raw_concept_id"]: dict(r) for r in snapshot.records("concept")}
    contexts = {r["context_id"]: dict(r) for r in snapshot.records("context")}
    units = {r["unit_id"]: dict(r) for r in snapshot.records("unit")}
    roles = {r["role_id"]: dict(r) for r in snapshot.records("role")}
    relationships = [{**r, "role_uri": roles[r["role_id"]]["role_uri"],
                      "role_definition": roles[r["role_id"]]["role_definition"]}
                     for r in snapshot.records("relationship")]
    for relationship in relationships:
        relationship["evidence_origin"] = "IMMUTABLE_RAW_SNAPSHOT"
    relationships.extend(supplemental_relationships or [])
    dims = defaultdict(list)
    for d in snapshot.records("dimension_fact"):
        dims[d["fact_id"]].append({"axis": d["axis_raw_concept_id"], "member": d["member_raw_concept_id"],
                                  "typed_value": d["typed_member"], "is_default": d["is_default_member"],
                                  "axis_qname": concepts[d["axis_raw_concept_id"]]["qname"],
                                  "member_qname": concepts.get(d["member_raw_concept_id"], {}).get("qname")})
    classified = PeriodClassifier().classify(filing=filing, concepts=concepts.values(),
                                            contexts=contexts.values(), facts=snapshot.records("fact"))
    facts, arithmetic = {}, []
    for raw in classified:
        context = contexts.get(raw["context_id"], {})
        unit = units.get(raw["unit_id"], {})
        period = {"type": str(context.get("period_kind", "")).lower(), "class": raw["period_class"],
                  "start": context.get("start_date"), "end": context.get("end_date"), "instant": context.get("instant_date")}
        scope = {"cik": filing["cik"], "filing_id": filing["filing_id"], "view": "RAW_AS_FILED",
                 "basis": "RAW:" + filing["filing_id"], "as_of": as_of, "period": period,
                 "unit": {"numerator": json.loads(unit.get("numerator_measures") or "[]"),
                          "denominator": json.loads(unit.get("denominator_measures") or "[]")},
                 "dimensions": sorted(dims[raw["fact_id"]], key=lambda d: d["axis"])}
        f = {**raw, "scope": scope, "concept": concepts[raw["raw_concept_id"]],
             "filing": filing, "context": context, "raw_unit": unit,
             "canonical_identity": "RAW:" + raw["raw_concept_id"], "canonical_status": "RAW_IDENTITY_ONLY",
             "source_locations": []}
        facts[f["fact_id"]] = f
        if period["type"] in {"instant", "duration"} and scope["unit"]["numerator"]:
            arithmetic.append(f)
    checks = materialize_signed_calculation_checks(facts=arithmetic, relationships=relationships)
    by_parent = defaultdict(list)
    for check in checks:
        by_parent[check["parent_fact_id"]].append(check["calculation_check_id"])
    for f in facts.values():
        f["calculation_check_ids"] = by_parent[f["fact_id"]]
        f["calculation_status"] = "PREPARED_CHECKS" if by_parent[f["fact_id"]] else "NO_CAL_RELATION"
    pre = presentation_paths(relationships, concepts, roles)
    rows, tables, coverage = enumerate_source(document=document, filing=filing, facts=facts, pre=pre)
    source_checks = []
    arithmetic_ids = {f["fact_id"] for f in arithmetic}
    for table in tables:
        if not table["role_id"]:
            continue
        bound_facts = [f for f in facts.values() if f["fact_id"] in arithmetic_ids and any(loc["table_id"] == table["table_id"] for loc in f["source_locations"])]
        arcs = [a for a in relationships if a["network_type"] == "CAL" and a["role_id"] == table["role_id"]]
        for check in materialize_signed_calculation_checks(facts=bound_facts, relationships=arcs):
            check["calculation_check_id"] = stable_id(table["table_id"], check["calculation_check_id"])
            check["source_table_id"] = table["table_id"]
            check["source_document_sha256"] = table["source_document_sha256"]
            check["check_basis"] = "EXACT_SOURCE_TABLE_FACT_OCCURRENCES"
            source_checks.append(check)
    filing_coverage = []
    for section in ("IS", "BS", "CF"):
        selected = [t for t in tables if t["section"] == section]
        filing_coverage.append({"filing_id": filing["filing_id"], "accession": filing["accession"], "form": filing["form"],
                                "section": section, "status": "INCLUDED" if selected else "NOT_PREPARED",
                                "reason": "PRIMARY_SOURCE_TABLE_BOUND" if selected else "NO_PRIMARY_SOURCE_TABLE_CLASSIFIED; RAW_AMENDMENT_OR_DISCLOSURE_PRESERVED",
                                "table_ids": [t["table_id"] for t in selected], "enumerated_html_tables": len(tables)})
    return {"filings": [filing], "filing_coverage": filing_coverage, "statement_facts": list(facts.values()), "source_statement_rows": rows,
            "source_tables": tables, "row_coverage": coverage, "statement_rows": pre,
            "statement_relationships": relationships, "calculation_checks": checks, "source_calculation_checks": source_checks,
            "member_paths": member_paths(relationships, concepts, facts)}


def presentation_paths(relationships: list[dict], concepts: dict, roles: dict) -> list[dict]:
    groups = defaultdict(list)
    for arc in relationships:
        if arc["network_type"] != "PRE":
            continue
        sections = [s for s in ("IS", "BS", "CF") if _qualifying_statement_role(roles[arc["role_id"]], s)]
        for section in sections:
            groups[(*[arc[k] for k in NETWORK_FIELDS], section)].append(arc)
    rows = []
    for key, arcs in sorted(groups.items()):
        outgoing = defaultdict(list)
        for arc in arcs:
            outgoing[arc["from_raw_concept_id"]].append(arc)
        targets = {a["to_raw_concept_id"] for a in arcs}
        roots = sorted(set(outgoing) - targets)
        # Cyclic rootless components remain explicit rather than disappearing.
        reachable = set()
        pending = list(roots)
        while pending:
            node = pending.pop()
            if node in reachable:
                continue
            reachable.add(node)
            pending.extend(a["to_raw_concept_id"] for a in outgoing[node])
        roots += sorted(set(outgoing) - reachable)
        stack = [(root, (), (), None, None) for root in reversed(roots)]
        order = 0
        while stack:
            concept_id, path, edge_path, parent_id, arc = stack.pop()
            order += 1
            cycle = concept_id in path
            rid = stable_id(key, path, edge_path, concept_id)
            rows.append({"row_id": rid, "parent_row_id": parent_id, "network_identity": dict(zip(NETWORK_FIELDS, key)),
                         "section": key[-1], "raw_concept_id": concept_id, "concept": concepts[concept_id],
                         "source_order": order, "depth": len(path), "path": [*path, concept_id],
                         "relationship_ids": list(edge_path), "relationship_type": "PRE_DISPLAY",
                         "incoming_relationship": arc, "cycle": cycle,
                         "coverage_kind": "PRE_PATH", "coverage_status": "STRUCTURAL" if concepts[concept_id]["abstract"] else "CONCEPT"})
            if cycle:
                continue
            for child in sorted(outgoing[concept_id], key=lambda a: (finite_decimal(a["order"]) or 0, a["relationship_id"]), reverse=True):
                stack.append((child["to_raw_concept_id"], (*path, concept_id), (*edge_path, child["relationship_id"]), rid, child))
    return rows


def _nearest(element, name: str):
    return next((e for e in element.iterancestors() if e.tag == name), None)


def enumerate_source(*, document: bytes, filing: dict, facts: dict, pre: list[dict]) -> tuple[list, list, list]:
    """Independently enumerate actual direct HTML rows, including untagged rows.

    All tables are catalogued. Statement selection is an auditable PRE-overlap
    display locator, never a replacement coverage denominator or value policy.
    """
    xml = etree.fromstring(document, etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
    inline = [e for e in xml.iter() if isinstance(e.tag, str) and etree.QName(e).localname in {"nonFraction", "nonNumeric", "fraction"}]
    doc = html.fromstring(document)
    dom_inline = [e for e in doc.iter() if isinstance(e.tag, str) and e.tag.lower() in {"ix:nonfraction", "ix:nonnumeric", "ix:fraction"}]
    if len(inline) != len(dom_inline):
        raise ValueError("HTML/XML inline enumeration differs; no ordinal inference allowed")
    bindings = {}
    for ordinal, (x, h) in enumerate(zip(inline, dom_inline, strict=True)):
        if x.get("id") != h.get("id") or x.get("name") != h.get("name"):
            raise ValueError("HTML/XML inline order differs")
        fid = _stable_id("fact", filing["filing_id"], x.get("id") or "", f"line:{x.sourceline}", ordinal)
        # Arelle may omit an invalid fact or have a different fact corpus/order.
        # Such an Inline item is explicit UNPREPARED; never fuzzy-joined.
        bound = facts.get(fid)
        if bound and bound["concept"]["qname"] != x.get("name"):
            raise ValueError("Raw fact QName differs from bound Inline source")
        bindings[h] = {"inline_id": x.get("id"), "inline_name": x.get("name"), "context_ref": x.get("contextRef"),
                       "unit_ref": x.get("unitRef"), "scale": x.get("scale"), "sign": x.get("sign"),
                       "decimals": x.get("decimals"), "fact_id": fid if bound else None,
                       "binding_status": "EXACT_RAW_ID" if bound else "UNPREPARED_INLINE_ID"}
    digest = hashlib.sha256(document).hexdigest()
    tree = doc.getroottree()
    rows, tables, coverage = [], [], []
    role_sets = defaultdict(set)
    for row in pre:
        if not row["concept"]["abstract"]:
            role_sets[(row["section"], row["network_identity"]["role_id"])].add(row["raw_concept_id"])
    for table_order, table in enumerate(doc.xpath("//table")):
        locator = tree.getpath(table)
        tid = stable_id(filing["filing_id"], digest, locator)
        direct_rows = [r for r in table.xpath(".//tr") if _nearest(r, "table") is table]
        table_facts, table_rows = [], []
        for row_order, tr in enumerate(direct_rows):
            rid = stable_id(tid, row_order)
            row_loc = tree.getpath(tr)
            cells = []
            for col, td in enumerate(tr.xpath("./th|./td")):
                refs = [dict(bindings[e]) for e in td.iter() if e in bindings and _nearest(e, "table") is table]
                cells.append({"column_order": col, "text": " ".join(td.text_content().split()),
                              "colspan": td.get("colspan", "1"), "rowspan": td.get("rowspan", "1"),
                              "source_cell_locator": tree.getpath(td), "inline_facts": refs})
                for ref in refs:
                    if ref["fact_id"]:
                        f = facts[ref["fact_id"]]
                        table_facts.append(f)
                        f["source_locations"].append({"source_document_sha256": digest, "table_id": tid,
                                                      "table_locator": locator, "row_id": rid, "row_locator": row_loc,
                                                      "cell_locator": tree.getpath(td), **ref})
            refs = [r for c in cells for r in c["inline_facts"]]
            status = "UNPREPARED" if any(r["fact_id"] is None for r in refs) else "INCLUDED" if refs else "STRUCTURAL"
            label = next((c["text"] for c in cells if c["text"] and not c["inline_facts"]), "")
            if not label:
                label = next((c["text"] for c in cells if c["text"]), "(blank row)")
            table_rows.append({"row_id": rid, "table_id": tid, "filing_id": filing["filing_id"],
                               "source_order": row_order, "label": label, "cells": cells,
                               "source_document_sha256": digest, "table_locator": locator, "row_locator": row_loc,
                               "coverage_status": status, "coverage_reason": "EXACT_INLINE_BINDING" if status == "INCLUDED" else "NO_INLINE_FACT" if status == "STRUCTURAL" else "RAW_ID_NOT_FOUND",
                               "relationship_type": "SOURCE_HTML_ORDER", "parent_row_id": None, "depth": 0,
                               "pre_path_ids": [], "protected": True, "warnings": []})
        table_concepts = {f["raw_concept_id"] for f in table_facts if not f["scope"]["dimensions"] and f["value_numeric"] is not None}
        scores = [{"section": section, "role_id": role_id, "overlap": len(ids & table_concepts),
                   "role_count": len(ids)} for (section, role_id), ids in role_sets.items() if len(ids & table_concepts) >= 3]
        table_info = {"table_id": tid, "filing_id": filing["filing_id"], "table_order": table_order,
                      "table_locator": locator, "source_document": filing["primary_document"],
                      "source_document_sha256": digest, "table_sha256": hashlib.sha256(html.tostring(table, with_tail=False)).hexdigest(),
                      "row_count": len(direct_rows), "section": "DISCLOSURE", "pre_candidates": scores,
                      "role_id": None, "has_dimensions": any(f["scope"]["dimensions"] for f in table_facts),
                      "selection_reason": "NONPRIMARY_TABLE_CATALOGUED", "filing": filing}
        tables.append(table_info)
        rows.extend(table_rows)
    # Pick maximum actual primary-role concept coverage. Ties retain earliest
    # source order; complete scores make this locator policy reviewable.
    for section in ("IS", "BS", "CF"):
        candidates = [(s["overlap"], -t["table_order"], t, s) for t in tables for s in t["pre_candidates"] if s["section"] == section]
        if candidates:
            _, _, chosen, score = max(candidates, key=lambda x: (x[0], x[1]))
            chosen.update(section=section, role_id=score["role_id"], selection_reason="MAX_PRIMARY_PRE_CONCEPT_OVERLAP_SOURCE_ORDER_TIEBREAK_V1")
    by_table = {t["table_id"]: t for t in tables}
    pre_by_role_concept = defaultdict(list)
    for p in pre:
        pre_by_role_concept[(p["network_identity"]["role_id"], p["raw_concept_id"])].append(p)
    abstract_labels = defaultdict(list)
    for p in pre:
        if p["concept"]["abstract"]:
            for label in (p["concept"]["label"], p["concept"]["qname"]):
                abstract_labels[(p["network_identity"]["role_id"], _display_words(label))].append(p)
    prior_rows = defaultdict(dict)
    cal_parents = {f["raw_concept_id"] for f in facts.values() if f["calculation_check_ids"]}
    for row in rows:
        table = by_table[row["table_id"]]
        row["section"] = table["section"]
        ids = {facts[r["fact_id"]]["raw_concept_id"] for c in row["cells"] for r in c["inline_facts"] if r["fact_id"]}
        paths = [p for cid in ids for p in pre_by_role_concept[(table["role_id"], cid)]]
        if not ids and row["label"] != "(blank row)":
            abstracts = abstract_labels[(table["role_id"], _display_words(row["label"]))]
            unique = {p["row_id"]: p for p in abstracts}
            if len(unique) == 1:
                paths = list(unique.values())
                ids = {paths[0]["raw_concept_id"]}
                row["heading_binding"] = "UNIQUE_EXACT_NORMALIZED_PRE_ABSTRACT_DISPLAY_LABEL"
        row["pre_path_ids"] = [p["row_id"] for p in paths]
        if len({tuple(p["path"]) for p in paths}) == 1 and paths:
            p = paths[0]
            # Link only a source row actually encountered earlier. Never reorder
            # the table to make a CAL parent precede its source children.
            ancestors = p["path"][:-1]
            parent = next((prior_rows[row["table_id"]][cid] for cid in reversed(ancestors) if cid in prior_rows[row["table_id"]]), None)
            if parent:
                row.update(parent_row_id=parent["row_id"], depth=parent["depth"] + 1)
            row["unbound_pre_ancestor_ids"] = [cid for cid in ancestors if cid not in prior_rows[row["table_id"]]]
        if not paths and ids and table["section"] != "DISCLOSURE":
            row["warnings"].append("HTML_FACT_NOT_IN_SELECTED_PRE")
        row["protected"] = bool(ids & cal_parents) or row["coverage_status"] == "UNPREPARED" or bool(row["warnings"]) or not ids
        for cid in ids:
            prior_rows[row["table_id"]][cid] = row
        coverage.append({"row_id": row["row_id"], "table_id": row["table_id"], "kind": "ORIGINAL_HTML_ROW",
                         "status": row["coverage_status"], "reason": row["coverage_reason"], "section": row["section"],
                         "row_locator": row["row_locator"], "source_document_sha256": digest})
    return rows, tables, coverage


def _display_words(label: str) -> str:
    local = label.split(":")[-1]
    local = re.sub(r"(?:Abstract|LineItems)$", "", local)
    local = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", local)
    return " ".join(re.findall(r"[a-z0-9]+", local.lower()))


def member_paths(relationships: list[dict], concepts: dict, facts: dict) -> list[dict]:
    """Independent Axis lenses; explicit targetRole with full remaining base set.

    Direct member references always retain the full fact scope. DEF structure
    does not license aggregation or inject values into unreported coordinates.
    """
    outgoing = defaultdict(list)
    for a in relationships:
        if a["network_type"] == "DEF" and a["arcrole"].rsplit("/", 1)[-1] in {"dimension-domain", "domain-member"}:
            outgoing[(a["filing_id"], a["role_uri"], a["link_qname"], a["arc_qname"], a["from_raw_concept_id"])].append(a)
    axes = {d["axis"] for f in facts.values() for d in f["scope"]["dimensions"]}
    rows = []
    for axis in sorted(axes):
        roots = sorted(k for k in outgoing if k[-1] == axis)
        for root in roots:
            stack = [(root, (), (), None, True)]
            while stack:
                key, path, rels, parent_id, usable = stack.pop()
                rid = stable_id(axis, root, path, rels, key)
                cycle = key in path
                rows.append({"member_path_id": rid, "axis_id": axis, "axis": concepts[axis],
                             "member_id": key[-1], "member": concepts[key[-1]], "parent_path_id": parent_id,
                             "network_key": list(key), "depth": len(path), "relationship_ids": list(rels),
                             "cycle": cycle, "usable": usable, "relationship_type": "DEF_MEMBER",
                             "fact_ids": sorted(f["fact_id"] for f in facts.values() if any(d["axis"] == axis and d["member"] == key[-1] for d in f["scope"]["dimensions"])) if usable else [],
                             "aggregation_status": "NOT_AUTHORIZED", "validation_scope": "PER_PATH_USABILITY_EVIDENCE_NOT_FULL_DRS_VALIDATION"})
                if cycle:
                    continue
                for a in sorted(outgoing[key], key=lambda x: (finite_decimal(x["order"]) or 0, x["relationship_id"]), reverse=True):
                    if key[-1] == axis and not a["arcrole"].endswith("/dimension-domain"):
                        continue
                    if key[-1] != axis and not a["arcrole"].endswith("/domain-member"):
                        continue
                    next_key = (a["filing_id"], a["target_role_uri"] or a["role_uri"], a["link_qname"], a["arc_qname"], a["to_raw_concept_id"])
                    stack.append((next_key, (*path, key), (*rels, a["relationship_id"]), rid, a["usable"] is not False))
    return rows


def apply_display_reviews(*, rows: list[dict], tables: list[dict], pre: list[dict], reviews: list[dict], decision_cutoff: str) -> list[str]:
    """Reviewed display grouping does not grant arithmetic/share eligibility."""
    from datetime import datetime
    applied = []
    for review in reviews:
        matching = [t for t in tables if (t["source_document_sha256"], t["table_locator"]) == (review["source_document_sha256"], review["table_locator"])]
        if not matching:
            continue
        if len(matching) != 1 or matching[0]["table_sha256"] != review["table_sha256"]:
            raise ValueError("display review table mismatch")
        if not review.get("reviewer") or datetime.fromisoformat(review["reviewed_at"]) > datetime.fromisoformat(decision_cutoff):
            raise ValueError("display review timestamp/reviewer invalid")
        table = matching[0]
        selected = {r["row_locator"]: r for r in rows if r["table_id"] == table["table_id"]}
        parent = selected[review["parent_row_locator"]]
        if parent["label"] != review["parent_label"]:
            raise ValueError("display heading label mismatch")
        required_pre = review["pre_relationship_ids"]
        available = {a for p in pre if p["network_identity"]["role_id"] == table["role_id"] for a in p["relationship_ids"]}
        if not required_pre or not set(required_pre) <= available:
            raise ValueError("display review PRE evidence mismatch")
        for locator in review["child_row_locators"]:
            child = selected[locator]
            if child["source_order"] <= parent["source_order"]:
                raise ValueError("display group must retain earlier heading and source order")
            child.update(parent_row_id=parent["row_id"], depth=parent["depth"] + 1,
                         display_review=review, relationship_type="REVIEWED_SOURCE_DISPLAY")
        for locator in review["protected_row_locators"]:
            selected[locator]["protected"] = True
        parent["display_review"] = review
        applied.append(review["review_id"])
    return applied
