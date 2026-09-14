#!/usr/bin/env python3
"""Frozen P5T M0 launcher. Generated once; do not edit."""
from __future__ import annotations
import argparse, hashlib, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
EXPECTED_FREEZE_SHA = "0674c159aefe5fbee73ff6818ec42c5479c02857cfafd5706973f84120b0d1a0"
EXPECTED_RUNNER_SHA = "e986ddf48d38bc1a525d78992b67705ba58b09d1e107382524acf34a33e059ff"
EXPECTED_PROTOCOL_SHA = "438a7f2668f4b3598a57d3fa4fba2ae7eeb473346be09c047b0fa7992be4c29e"
EXPECTED_SPLIT_SHA = "47deaf7746e89a121c0cc1571989da9dd469ab9a3f6ec29a12c3a77afc4026ba"
EXPECTED_SCHEMA_SHA = "a3e1d94d159b5688031953a6fa5878c7b886f5d8d4ab29e716e000faef25937a"
EXPECTED_GENERATOR_SHA = "4e458381938fef23cce536e45f92a19c1c24fb013b65db84915a7bdfd3e88a0f"
RUNNER=ROOT/"experiments"/"autocontract_p5t_benefit_surface.py"
PROTOCOL=ROOT/"benchmark"/"final_v1"/"p5t_benefit_surface_protocol.json"
SPLIT=ROOT/"benchmark"/"final_v1"/"p5t_div2k_split_manifest.json"
SCHEMA=ROOT/"benchmark"/"final_v1"/"p5t_benefit_surface_result.schema.json"
FREEZE=ROOT/"benchmark"/"final_v1"/"p5t_m0_execution_freeze_v3.json"
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
