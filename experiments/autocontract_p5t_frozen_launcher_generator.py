#!/usr/bin/env python3
"""Create the one-time P5T M0 launcher from a v2 refreeze."""
from __future__ import annotations
import argparse, hashlib, json, os, subprocess, sys, tempfile
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
RUNNER=ROOT/"experiments"/"autocontract_p5t_benefit_surface.py"
PROTOCOL=ROOT/"benchmark"/"final_v1"/"p5t_benefit_surface_protocol.json"
SPLIT=ROOT/"benchmark"/"final_v1"/"p5t_div2k_split_manifest.json"
SCHEMA=ROOT/"benchmark"/"final_v1"/"p5t_benefit_surface_result.schema.json"
FREEZE=ROOT/"benchmark"/"final_v1"/"p5t_m0_execution_freeze_v3.json"
INCIDENT=ROOT/"benchmark"/"final_v1"/"p5t_m0_launcher_incident_v1.json"
DEPENDENCY_INCIDENT=ROOT/"benchmark"/"final_v1"/"p5t_m0_dependency_incident_v1.json"
LAUNCHER=ROOT/"experiments"/"autocontract_p5t_frozen_launcher_v3.py"
SELFTEST=ROOT/"outputs"/"autocontract_p5t_m0_selftest_v7.json"
SMOKE=ROOT/"outputs"/"autocontract_p5t_launcher_smoke_v2.json"
CEDAR_IMPORT_SMOKE=ROOT/"outputs"/"autocontract_p5t_cedar_import_smoke_v1.json"
P5S_PINNED={"runner":"5453de6a8b5c97e6b30999aabbc3a6030b3c586cc6e96b013f10b0ccc501d7cc","manifest":"255c725ea321b653925cd530f2664c7760d6d651745cf200258b58d9661005c8","manifest_schema":"d57d0710722c97fc587b863b4433c6eecf754aa03afcae7631f81e72ecc0794d","p5a":"c96ed767f97ecd82d6ea7bc574d4a0211bb530464ec42c9960d9459598f5d0ab","p5m":"42ac1f44c01e027467d87216f76e78fb89a0cdc610cf544130687ca7c71e52ec","v0":"77da9d207f62a3e732f5242aebf76bcdae43acebf16baa02cbb3f9879d93a5ae","v2":"26d5e37606c6098b2009832706c04fd0ff99dde377d91ffdaf80041b1b3b4e35","v3":"f74b37993e7dc5d4b5c304c7f3f0facabfae61ca4eecc9a8896bae372d179333","r3_source_index_v1":"7e6251c0388fce23c115919258ac43fb9d620ea38f8902082fe6da7cfbb5238c","r3_source_index_v0":"02a10103e26cb4a55f646428d7e24f14bdf73b133149e29c220a78f38829ab2b"}

def sha(path: Path)->str:
    digest=hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda:handle.read(1024*1024),b""): digest.update(block)
    return digest.hexdigest()
def require(ok:bool,message:str)->None:
    if not ok: raise ValueError(message)
def p5s_inputs()->dict[str,str]:
    paths={"runner":ROOT/"experiments"/"autocontract_p5s_div2k_e2e.py","manifest":ROOT/"outputs"/"autocontract_p5s_div2k_manifest.json","manifest_schema":ROOT/"benchmark"/"final_v1"/"p5s_div2k_manifest.schema.json","p5a":ROOT/"experiments"/"autocontract_p5a_constraint_compiler.py","p5m":ROOT/"experiments"/"autocontract_p5m_relation_boundary_falsification.py","v0":ROOT/"experiments"/"autocontract_reorder_capability_v0.py","v2":ROOT/"experiments"/"autocontract_reorder_capability_v2.py","v3":ROOT/"experiments"/"autocontract_reorder_capability_v3.py","r3_source_index_v1":ROOT/"experiments"/"autocontract_r3_source_index_v1.py","r3_source_index_v0":ROOT/"experiments"/"autocontract_r3_source_index.py"}
    value={name:sha(path) for name,path in paths.items()}; require(value==P5S_PINNED,"p5s_frozen_input_drift"); return value

def dispatch(command:list[str],output:Path,validator:Any)->int:
    require(not output.exists(),"output_already_exists")
    completed=subprocess.run(command,check=False)
    if completed.returncode!=0: return completed.returncode
    if not output.is_file(): return 1
    try: validator(output)
    except (OSError,ValueError,json.JSONDecodeError): return 1
    return 0

def launcher_text(freeze_sha:str,runner_sha:str,protocol_sha:str,split_sha:str,schema_sha:str,generator_sha:str)->str:
    return f'''#!/usr/bin/env python3
"""Frozen P5T M0 launcher. Generated once; do not edit."""
from __future__ import annotations
import argparse, hashlib, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
EXPECTED_FREEZE_SHA = "{freeze_sha}"
EXPECTED_RUNNER_SHA = "{runner_sha}"
EXPECTED_PROTOCOL_SHA = "{protocol_sha}"
EXPECTED_SPLIT_SHA = "{split_sha}"
EXPECTED_SCHEMA_SHA = "{schema_sha}"
EXPECTED_GENERATOR_SHA = "{generator_sha}"
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
'''

def write_once(path:Path,text:str)->None:
    require(not path.exists(),"launcher_already_exists")
    with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",dir=path.parent,prefix=f".{path.name}.",suffix=".tmp",delete=False) as handle:
        temporary=Path(handle.name); handle.write(text); handle.flush(); os.fsync(handle.fileno())
    try:
        fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY); os.close(fd); os.replace(temporary,path)
    finally:
        if temporary.exists(): temporary.unlink()

def main()->int:
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument("--approved-freeze-sha",required=True); args=parser.parse_args()
    require(not LAUNCHER.exists() and FREEZE.is_file() and sha(FREEZE)==args.approved_freeze_sha,"freeze_or_launcher_anchor_mismatch")
    freeze=json.loads(FREEZE.read_text(encoding="utf-8"))
    expected={"schema_version":"autocontract.p5t-m0-freeze.v3","phase":"freeze","status":"pass","scientific_evidence":False,"protocol_sha256":sha(PROTOCOL),"runner_sha256":sha(RUNNER),"split_manifest_sha256":sha(SPLIT),"schema_sha256":sha(SCHEMA),"p5s_inputs":p5s_inputs(),"cedar_commit":"f062305fcdab196e871c5d09b4c82ab788b4da79","selftest_sha256":sha(SELFTEST),"incident_sha256":sha(INCIDENT),"dependency_incident_sha256":sha(DEPENDENCY_INCIDENT),"generator_sha256":sha(Path(__file__)),"launcher_smoke_sha256":sha(SMOKE),"cedar_import_smoke_sha256":sha(CEDAR_IMPORT_SMOKE)}
    require(freeze==expected,"freeze_contents_mismatch")
    write_once(LAUNCHER,launcher_text(sha(FREEZE),sha(RUNNER),sha(PROTOCOL),sha(SPLIT),sha(SCHEMA),sha(Path(__file__))))
    print(json.dumps({"status":"pass","launcher":str(LAUNCHER),"launcher_sha256":sha(LAUNCHER)},indent=2)); return 0
if __name__=="__main__": raise SystemExit(main())
