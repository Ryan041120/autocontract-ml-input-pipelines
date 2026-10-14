#!/usr/bin/env python3
"""Write-once generator for the attempt3 frozen launcher."""
from __future__ import annotations
import argparse, hashlib, json, os, subprocess, sys, tempfile
from pathlib import Path
from typing import Any
ROOT=Path(__file__).resolve().parents[1]
CANONICAL_TARGET=ROOT/"experiments"/"autocontract_p5t_frozen_launcher_v5.py"
CANONICAL_FREEZE=ROOT/"benchmark"/"final_v1"/"p5t_attempt3_freeze_v5.json"
def sha(path: Path)->str: return hashlib.sha256(path.read_bytes()).hexdigest()
def launcher_text(bindings: dict[str,Any])->str:
 required={"runner_path","runner_sha256","core_path","core_sha256","protocol_path","protocol_sha256","result_schema_path","result_schema_sha256","freeze_path","freeze_sha256","generator_path","generator_sha256","contracts_path","contracts_sha256","fixed_python","fixed_python_sha256"}
 if set(bindings)!=required: raise ValueError("launcher_bindings_closed")
 frozen=json.dumps(bindings,ensure_ascii=False,sort_keys=True,separators=(",",":"))
 return f'''#!/usr/bin/env python3
import argparse, hashlib, json, pathlib, subprocess, sys
BINDINGS=json.loads({frozen!r})
def digest(path): return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()
def die(message): print(message,file=sys.stderr); return 2
def main():
 p=argparse.ArgumentParser(add_help=False); p.add_argument("--execution-closure"); p.add_argument("--expected-execution-closure-sha"); p.add_argument("--expected-launcher-sha"); a,rest=p.parse_known_args()
 if not (a.execution_closure and a.expected_execution_closure_sha and a.expected_launcher_sha): return die("launcher arguments invalid")
 if len(a.expected_execution_closure_sha)!=64 or digest(a.execution_closure)!=a.expected_execution_closure_sha: return die("execution closure invalid")
 if digest(__file__)!=a.expected_launcher_sha: return die("launcher self hash invalid")
 for path_key,hash_key in (("runner_path","runner_sha256"),("core_path","core_sha256"),("protocol_path","protocol_sha256"),("result_schema_path","result_schema_sha256"),("freeze_path","freeze_sha256"),("generator_path","generator_sha256"),("contracts_path","contracts_sha256"),("fixed_python","fixed_python_sha256")):
  try:
   if digest(BINDINGS[path_key])!=BINDINGS[hash_key]: return die("launcher binding invalid")
  except OSError: return die("launcher binding missing")
 if "--output" not in rest: return die("output required")
 output=pathlib.Path(rest[rest.index("--output")+1]) if rest.index("--output")+1<len(rest) else None
 if output is None or output.exists(): return die("output invalid")
 command=[BINDINGS["fixed_python"],BINDINGS["runner_path"],"--execution-closure",a.execution_closure,"--expected-execution-closure-sha",a.expected_execution_closure_sha,"--launcher",str(pathlib.Path(__file__).resolve()),"--expected-launcher-sha",a.expected_launcher_sha,*rest]
 result=subprocess.run(command,stdout=subprocess.DEVNULL,check=False)
 return result.returncode if result.returncode else (0 if output.is_file() else 2)
if __name__=="__main__": raise SystemExit(main())
'''
def publish(path: Path,payload: bytes,expected_launcher_sha: str,canonical_target: Path|None=None,link: Any=os.link,after_fsync: Any=None,after_link: Any=None)->str:
 """Publish precisely the supplied bytes; do not give Windows a newline conversion opportunity."""
 target=CANONICAL_TARGET if canonical_target is None else canonical_target
 if path.resolve()!=target.resolve() or path.parent.resolve()!=target.parent.resolve(): raise ValueError("launcher_target_noncanonical")
 if path.exists(): raise FileExistsError("output_exists")
 if not isinstance(payload,bytes) or not isinstance(expected_launcher_sha,str) or len(expected_launcher_sha)!=64 or hashlib.sha256(payload).hexdigest()!=expected_launcher_sha: raise ValueError("launcher_expected_sha")
 temporary=None
 try:
  path.parent.mkdir(parents=True,exist_ok=True)
  with tempfile.NamedTemporaryFile("wb",dir=path.parent,prefix=f".{path.name}.",suffix=".tmp",delete=False) as f:
   temporary=Path(f.name); f.write(payload); f.flush(); os.fsync(f.fileno())
  if after_fsync is not None: after_fsync(temporary)
  if sha(temporary)!=expected_launcher_sha: raise ValueError("launcher_temp_sha")
  link(temporary,path)
  if after_link is not None: after_link(path)
  if sha(path)!=expected_launcher_sha:
   # A target may only be removed when it is demonstrably our own hardlink.
   if temporary.exists() and path.exists() and os.path.samefile(temporary,path): path.unlink()
   raise ValueError("launcher_published_sha")
  return expected_launcher_sha
 finally:
  if temporary is not None and temporary.exists(): temporary.unlink()

def _need(ok: bool,message: str)->None:
 if not ok: raise ValueError(message)

def bindings_from_freeze(freeze: Path,expected_freeze_sha: str)->dict[str,Any]:
 """Extract only launcher-owned bindings from an already closed canonical freeze."""
 _need(freeze.resolve()==CANONICAL_FREEZE.resolve() and isinstance(expected_freeze_sha,str) and len(expected_freeze_sha)==64,"freeze_path_or_hash")
 _need(freeze.is_file() and sha(freeze)==expected_freeze_sha,"freeze_hash")
 try: raw=json.loads(freeze.read_text(encoding="utf-8"))
 except (OSError,UnicodeDecodeError,json.JSONDecodeError) as exc: raise ValueError("freeze_json") from exc
 _need(isinstance(raw,dict) and raw.get("schema_version")=="autocontract.p5t-attempt3-freeze.v5" and raw.get("status")=="pass","freeze_shape")
 bindings=raw.get("bindings",{}); active=bindings.get("active_sources",{}); runtime=bindings.get("runtime",{})
 paths={"runner":ROOT/"experiments"/"autocontract_p5t_attempt3_v11.py","core":ROOT/"experiments"/"autocontract_p5t_benefit_surface.py","protocol":ROOT/"benchmark"/"final_v1"/"p5t_benefit_surface_protocol.json","result_schema":ROOT/"benchmark"/"final_v1"/"p5t_attempt3_result_v1.schema.json","generator":Path(__file__),"contracts":ROOT/"experiments"/"autocontract_p5t_attempt3_contracts_v2.py"}
 extracted: dict[str,Any]={}
 for name,path in paths.items():
  doc=active.get(name,{}).get("doc",{}) if isinstance(active.get(name),dict) else {}
  _need(doc.get("path")==str(path.resolve()) and doc.get("sha256")==sha(path),"freeze_active_"+name)
  extracted[name]=path
 fixed=Path(runtime.get("fixed_python","") or "")
 _need(fixed.is_file() and runtime.get("fixed_python")==str(fixed.resolve()) and runtime.get("fixed_python_sha256")==sha(fixed),"freeze_runtime")
 return {"runner_path":str(extracted["runner"].resolve()),"runner_sha256":sha(extracted["runner"]),"core_path":str(extracted["core"].resolve()),"core_sha256":sha(extracted["core"]),"protocol_path":str(extracted["protocol"].resolve()),"protocol_sha256":sha(extracted["protocol"]),"result_schema_path":str(extracted["result_schema"].resolve()),"result_schema_sha256":sha(extracted["result_schema"]),"freeze_path":str(CANONICAL_FREEZE.resolve()),"freeze_sha256":expected_freeze_sha,"generator_path":str(Path(__file__).resolve()),"generator_sha256":sha(Path(__file__)),"contracts_path":str(extracted["contracts"].resolve()),"contracts_sha256":sha(extracted["contracts"]),"fixed_python":str(fixed.resolve()),"fixed_python_sha256":sha(fixed)}

def synthetic_selftest()->dict[str,Any]:
 bindings={"runner_path":"C:/fixture/runner.py","runner_sha256":"a"*64,"core_path":"C:/fixture/core.py","core_sha256":"b"*64,"protocol_path":"C:/fixture/protocol.json","protocol_sha256":"c"*64,"result_schema_path":"C:/fixture/schema.json","result_schema_sha256":"d"*64,"freeze_path":"C:/fixture/freeze.json","freeze_sha256":"e"*64,"generator_path":"C:/fixture/generator.py","generator_sha256":"f"*64,"contracts_path":"C:/fixture/contracts.py","contracts_sha256":"1"*64,"fixed_python":"C:/fixture/python.exe","fixed_python_sha256":"0"*64}
 text=launcher_text(bindings); payload=text.encode("utf-8"); rejected=False
 try: launcher_text({})
 except ValueError: rejected=True
 with tempfile.TemporaryDirectory(prefix="p5t_launcher_v5_bytes_") as raw:
  root=Path(raw); target=root/"launcher.py"; competitor=root/"competitor.py"; expected=hashlib.sha256(payload).hexdigest()
  actual=publish(target,payload,expected,target); bytes_equal=target.read_bytes()==payload and actual==expected
  mismatch_rejected=False
  try: publish(root/"bad.py",payload,"0"*64,root/"bad.py")
  except ValueError: mismatch_rejected=not (root/"bad.py").exists()
  prelink=root/"prelink-tamper.py"; prelink_rejected=False
  try: publish(prelink,payload,expected,prelink,after_fsync=lambda temp: temp.write_bytes(temp.read_bytes()+b"x"))
  except ValueError: prelink_rejected=not prelink.exists()
  competitor.write_bytes(b"competitor")
  competitor_preserved=False
  try: publish(competitor,payload,expected,competitor)
  except FileExistsError: competitor_preserved=competitor.read_bytes()==b"competitor"
  race=root/"race.py"; race_preserved=False
  try: publish(race,payload,expected,race,after_fsync=lambda _temp: race.write_bytes(b"competitor-race"))
  except FileExistsError: race_preserved=race.read_bytes()==b"competitor-race"
  postlink=root/"postlink.py"; postlink_cleanup=False
  try: publish(postlink,payload,expected,postlink,after_link=lambda target: target.write_bytes(b"tampered"))
  except ValueError: postlink_cleanup=not postlink.exists()
 return {"schema_version":"autocontract.p5t-attempt3-launcher-generator-selftest.v2","phase":"selftest","status":"pass","scientific_evidence":False,"dataset_access":"not_attempted","real_dataset_execution_performed":False,"checks":{"closed_bindings":all(value in text for value in (bindings["runner_path"],bindings["freeze_sha256"])),"invalid_rejected":rejected,"actual_bytes_equal":bytes_equal,"expected_sha_mismatch_no_target":mismatch_rejected,"prelink_tamper_no_target":prelink_rejected,"competitor_preserved":competitor_preserved,"competitor_race_preserved":race_preserved,"postlink_owned_target_removed":postlink_cleanup},"claim_boundary":"Synthetic launcher-generator bytes test only; no canonical artifact was written."}

def main(argv: list[str]|None=None)->int:
 parser=argparse.ArgumentParser(); parser.add_argument("--mode",required=True,choices=("publish-v5","selftest")); parser.add_argument("--freeze",type=Path); parser.add_argument("--expected-freeze-sha"); parser.add_argument("--expected-launcher-sha"); parser.add_argument("--output",type=Path); args=parser.parse_args(argv)
 try:
  if args.mode=="selftest": print(json.dumps(synthetic_selftest(),ensure_ascii=False,indent=2)); return 0
  _need(args.freeze is not None and args.expected_freeze_sha and args.expected_launcher_sha and args.output is not None and args.output.resolve()==CANONICAL_TARGET.resolve() and not args.output.exists(),"publish_args")
  bindings=bindings_from_freeze(args.freeze,args.expected_freeze_sha)
  verified=subprocess.run([bindings["fixed_python"],"-B",bindings["runner_path"],"--mode","verify-freeze-v5","--freeze",str(args.freeze),"--expected-freeze-sha",args.expected_freeze_sha],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False)
  _need(verified.returncode==0,"freeze_runner_verification")
  payload=launcher_text(bindings).encode("utf-8")
  digest=publish(args.output,payload,args.expected_launcher_sha,CANONICAL_TARGET); print(digest); return 0
 except (OSError,ValueError) as exc: print(f"{type(exc).__name__}:{exc}",file=sys.stderr); return 2

if __name__=="__main__": raise SystemExit(main())
