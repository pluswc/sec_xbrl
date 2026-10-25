"""Prepare one clearly synthetic Korean company intro for isolated UI checks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sec_xbrl.screening.common import sha256_file, write_json
from sec_xbrl.screening.company_descriptions import publish_company_descriptions
from sec_xbrl.screening.dataset import MANIFEST as DATASET_MANIFEST
from sec_xbrl.screening.dataset_v2 import open_screening_dataset


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--cik", default="0000320193")
    args = parser.parse_args()

    workspace = args.workspace
    workspace.mkdir(parents=True, exist_ok=False)
    inputs = workspace / "inputs"
    inputs.mkdir()
    dataset = open_screening_dataset(args.dataset)
    companies = {row["cik"]: row for row in dataset.companies}
    if args.cik not in companies:
        raise ValueError("requested synthetic-description CIK is absent from the dataset")

    text_name = f"{args.cik}.txt"
    (inputs / text_name).write_text(
        "이 문장은 화면 동작을 확인하기 위한 합성 회사 소개입니다.\n"
        "실제 제공자 콘텐츠나 투자 판단 자료가 아닙니다.",
        encoding="utf-8",
    )
    entries = []
    for company in sorted(dataset.companies, key=lambda row: row["cik"]):
        if company["cik"] == args.cik:
            entries.append(
                {
                    "cik": company["cik"],
                    "ticker": company["ticker"],
                    "status": "AVAILABLE",
                    "provider_id": "synthetic-ui-fixture",
                    "provider_name": "합성 화면 점검 자료",
                    "profile_url": f"https://example.invalid/company/{company['cik']}",
                    "locale": "ko",
                    "checked_at": "2026-10-10T12:00:00+09:00",
                    "observed_at": "2026-10-10T12:00:00+09:00",
                    "rights_status": "APPROVED",
                    "rights_reference": "SYNTHETIC_FIXTURE_CREATED_IN_REPOSITORY",
                    "rights_scope": "DISPLAY_PLAINTEXT",
                    "rights_valid_from": "2026-10-10",
                    "rights_expires_at": "2099-12-31",
                    "text_path": text_name,
                }
            )
        else:
            entries.append(
                {
                    "cik": company["cik"],
                    "ticker": company["ticker"],
                    "status": "UNAVAILABLE",
                    "provider_id": None,
                    "provider_name": None,
                    "profile_url": None,
                    "locale": None,
                    "checked_at": None,
                    "observed_at": None,
                    "unavailable_reason": "합성 화면 점검 대상으로 선택하지 않은 회사입니다.",
                }
            )
    plan = {
        "schema_version": "company-description-plan-v1",
        "dataset_id": dataset.manifest["dataset_id"],
        "dataset_publication_id": dataset.publication_id,
        "dataset_manifest_sha256": sha256_file(args.dataset / DATASET_MANIFEST),
        "fixture_kind": "SYNTHETIC_DESCRIPTION_FIXTURE",
        "acquisition_mode": "PROVIDED_TEXT",
        "input_root": str(inputs),
        "allowed_hosts": ["example.invalid"],
        "entries": entries,
    }
    plan_path = workspace / "synthetic-plan.json"
    write_json(plan_path, plan)
    result = publish_company_descriptions(
        plan_path,
        args.dataset,
        workspace / "publication",
    )
    print(
        json.dumps(
            {
                "fixture_kind": "SYNTHETIC_DESCRIPTION_FIXTURE",
                "publication": str(result.root),
                "publication_id": result.publication_id,
                "manifest_sha256": result.manifest_sha256,
                "cik": args.cik,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
