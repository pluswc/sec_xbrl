"""Append-only screening dataset v3 over annual v2 and quarterly metrics."""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from sec_xbrl.screening.common import (
 digest_value,
 read_json,
 real_directory,
 regular_file,
 require_string,
 sha256_file,
 write_json,
)
from sec_xbrl.screening.dataset_v2 import MANIFEST, ScreeningDatasetV2Reader
from sec_xbrl.screening.quarterly import MANIFEST as QUARTER_MANIFEST
from sec_xbrl.screening.quarterly import QuarterlyScreeningMetricReader

VERSION="screening-dataset-v3"; CONFIG_VERSION="screening-prepare-config-v3"

def publish_screening_dataset_v3(config_path:Path|str,destination:Path|str)->Path:
 p=regular_file(Path(config_path),"v3 config"); c=read_json(p,"v3 config")
 if not isinstance(c,dict) or c.get("schema_version")!=CONFIG_VERSION: raise ValueError("unsupported screening v3 config")
 dest=Path(destination).absolute()
 if dest.exists(): raise ValueError("screening v3 destination must be new")
 annual_root=real_directory(Path(require_string(c.get("annual_dataset_root"),"annual root")),"annual v2")
 quarter_root=real_directory(Path(require_string(c.get("quarterly_metric_root"),"quarter root")),"quarter metrics")
 annual_hash=sha256_file(annual_root/MANIFEST); quarter_hash=sha256_file(quarter_root/QUARTER_MANIFEST)
 if annual_hash!=c.get("annual_manifest_sha256") or quarter_hash!=c.get("quarterly_manifest_sha256"): raise ValueError("screening v3 parent differs from pinned manifest")
 annual=ScreeningDatasetV2Reader(annual_root); quarter=QuarterlyScreeningMetricReader(quarter_root,manifest_sha256=quarter_hash)
 if [x["cik"] for x in annual.companies]!=quarter.manifest["universe"]["ciks"]: raise ValueError("annual and quarterly company membership differ")
 identity={"config_path":str(p),"config_sha256":sha256_file(p),"config":c,"annual_publication_id":annual.publication_id,"quarterly_publication_id":quarter.publication_id}
 manifest={"schema_version":VERSION,"publication_id":"screening-dataset-"+digest_value(identity)[:24],"dataset_id":require_string(c.get("dataset_id"),"dataset_id"),"fixture_kind":c.get("fixture_kind","ACTUAL_PREPARED"),"financial_as_of":quarter.manifest["financial_as_of"],"config_path":str(p),"config_sha256":sha256_file(p),"config":c,"parents":{"annual":{"root":str(annual_root),"publication_id":annual.publication_id,"manifest_sha256":annual_hash},"quarterly":{"root":str(quarter_root),"publication_id":quarter.publication_id,"manifest_sha256":quarter_hash}}}
 dest.mkdir(parents=True);write_json(dest/MANIFEST,manifest);ScreeningDatasetV3Reader(dest);return dest

class ScreeningDatasetV3Reader:
 def __init__(self,root:Path|str):
  self.root=real_directory(Path(root),"screening v3");self.manifest=read_json(regular_file(self.root/MANIFEST,"v3 manifest"),"v3 manifest")
  if self.manifest.get("schema_version")!=VERSION: raise ValueError("unsupported screening v3 publication")
  a=self.manifest["parents"]["annual"];q=self.manifest["parents"]["quarterly"]
  ar=real_directory(Path(a["root"]),"annual parent");qr=real_directory(Path(q["root"]),"quarter parent")
  if sha256_file(ar/MANIFEST)!=a["manifest_sha256"] or sha256_file(qr/QUARTER_MANIFEST)!=q["manifest_sha256"]: raise ValueError("screening v3 parent changed")
  self.annual=ScreeningDatasetV2Reader(ar);self.quarterly=QuarterlyScreeningMetricReader(qr,manifest_sha256=q["manifest_sha256"])
  self.publication_id=self.manifest["publication_id"];self.companies=copy.deepcopy(self.annual.companies);self.metadata=copy.deepcopy(self.annual.metadata);self.metric_definitions=copy.deepcopy(self.annual.metric_definitions);self.metric_support=copy.deepcopy(self.annual.metric_support);self.observations=copy.deepcopy(self.annual.observations)
  self.quarter_definitions=copy.deepcopy(self.quarterly.definitions);self.quarter_support=copy.deepcopy(self.quarterly.support);self.quarter_observations=copy.deepcopy(self.quarterly.observations);self.quarter_period_inventory=copy.deepcopy(self.quarterly.period_inventory);self.verify_all()
 def company(self,cik:str)->dict[str,Any]: return self.annual.company(cik)
 def verify_all(self)->dict[str,Any]:
  if [x["cik"] for x in self.companies]!=self.quarterly.manifest["universe"]["ciks"]: raise ValueError("screening v3 membership changed")
  return {"publication_id":self.publication_id,"dataset_id":self.manifest["dataset_id"],"fixture_kind":self.manifest["fixture_kind"],"financial_as_of":self.manifest["financial_as_of"],"company_count":len(self.companies),"quarter_definition_count":len(self.quarter_definitions),"quarter_observation_count":len(self.quarter_observations)}
