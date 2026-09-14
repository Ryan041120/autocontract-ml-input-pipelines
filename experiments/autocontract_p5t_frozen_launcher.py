#!/usr/bin/env python3
"""Frozen P5T M0 launcher. Generated once; do not edit."""
from __future__ import annotations
import argparse, hashlib, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
EXPECTED_FREEZE_SHA = "33ac3887574839513099d5dcafe407f422fffae10d3f35349266167688d341d9"
EXPECTED_RUNNER_SHA = "1c6077558074fb0049a3c14ebc981bc282915850de6e9547043c02b225a685b3"
EXPECTED_PROTOCOL_SHA = "1bf43196befa9487561e4849b2ac87a22fbe54d04ff96a551e2327714d45ff93"
EXPECTED_SPLIT_SHA = "47deaf7746e89a121c0cc1571989da9dd469ab9a3f6ec29a12c3a77afc4026ba"
EXPECTED_SCHEMA_SHA = "c9506832baab0d917fdc881dd75d33d323c0f643cf6b120f1afd69fdd41e670f"
EXPECTED_GENERATOR_SHA = "c1eb0ef34b0c1be3872847bcab6508c2465082e8e5b9771cd2158535429e290c"
RUNNER=ROOT/"experiments"/"autocontract_p5t_benefit_surface.py"
PROTOCOL=ROOT/"benchmark"/"final_v1"/"p5t_benefit_surface_protocol.json"
SPLIT=ROOT/"benchmark"/"final_v1"/"p5t_div2k_split_manifest.json"
SCHEMA=ROOT/"benchmark"/"final_v1"/"p5t_benefit_surface_result.schema.json"
FREEZE=ROOT/"benchmark"/"final_v1"/"p5t_m0_execution_freeze.json"
GENERATOR=ROOT/"experiments"/"autocontract_p5t_frozen_launcher_generator.py"
def sha(path):
 d=hashlib.sha256()
 with path.open("rb") as h:
  for b in iter(lambda:h.read(1024*1024),b""): d.update(b)
 return d.hexdigest()
def main():
 p=argparse.ArgumentParser(); p.add_argument("--cedar-root",required=True); p.add_argument("--dataset-root",required=True); p.add_argument("--output",required=True); a=p.parse_args(); output=Path(a.output)
 if output.exists() or not (FREEZE.is_file() and sha(FREEZE)==EXPECTED_FREEZE_SHA and sha(RUNNER)==EXPECTED_RUNNER_SHA and sha(PROTOCOL)==EXPECTED_PROTOCOL_SHA and sha(SPLIT)==EXPECTED_SPLIT_SHA and sha(SCHEMA)==EXPECTED_SCHEMA_SHA and sha(GENERATOR)==EXPECTED_GENERATOR_SHA): return 1
 sys.path.insert(0,str(ROOT/"experiments")); from autocontract_p5t_frozen_launcher_generator import dispatch
 launcher_sha=sha(Path(__file__))
 def valid(path):
  v=json.loads(path.read_text(encoding="utf-8")); assert v.get("phase")=="m0-aggregate" and v.get("status")=="pass" and v.get("scientific_evidence") is False and v.get("protocol_sha256")==EXPECTED_PROTOCOL_SHA and v.get("runner_sha256")==EXPECTED_RUNNER_SHA and v.get("split_manifest_sha256")==EXPECTED_SPLIT_SHA and v.get("freeze_sha256")==EXPECTED_FREEZE_SHA and v.get("launcher_sha256")==launcher_sha
 return dispatch([sys.executable,str(RUNNER),"--mode","m0","--cedar-root",a.cedar_root,"--dataset-root",a.dataset_root,"--output",str(output),"--expected-freeze-sha",EXPECTED_FREEZE_SHA,"--launcher-path",str(Path(__file__).resolve()),"--launcher-sha",launcher_sha],output,valid)
if __name__=="__main__": raise SystemExit(main())
