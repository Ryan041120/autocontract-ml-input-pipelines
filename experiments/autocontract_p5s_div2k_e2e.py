#!/usr/bin/env python3
"""P5S DIV2K streaming E2E runner.

``profile`` and ``smoke`` are the only modes exercised during construction.
``confirm`` and ``aggregate`` are implemented for the frozen protocol but must
not be run until a separate acquisition review authorizes them.
"""
from __future__ import annotations

import argparse, copy, hashlib, json, math, os, pickle, random, statistics, subprocess, sys, tempfile, time, uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn.functional as functional
from PIL import Image
from torchvision.models import mobilenet_v3_small
from torchvision.transforms import v2

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "benchmark" / "final_v1" / "p5s_div2k_e2e_protocol.json"
PROFILE = ROOT / "benchmark" / "final_v1" / "p5s_div2k_cedar_profile.yml"
MANIFEST = ROOT / "outputs" / "autocontract_p5s_div2k_manifest.json"
MANIFEST_SCHEMA = ROOT / "benchmark" / "final_v1" / "p5s_div2k_manifest.schema.json"
FREEZE = ROOT / "benchmark" / "final_v1" / "p5s_div2k_execution_freeze.json"
LAUNCHER = ROOT / "experiments" / "autocontract_p5s_frozen_launcher.py"
AMENDMENT = ROOT / "benchmark" / "final_v1" / "p5s_div2k_incident_amendment_v1.json"
CONTROL_SELFTEST = ROOT / "outputs" / "autocontract_p5s_confirm_control_selftest.json"
CEDAR_COMMIT = "f062305fcdab196e871c5d09b4c82ab788b4da79"
BOOTSTRAP_SEED = 20260807
IDS = ("decode", "to_float", "guard", "normalize", "random_crop")
TIMER_BOUNDARY = "load_from_plan through final optimizer.step; planning/model construction excluded"
FROZEN_PROTOCOL_SHA = "d78c1a6c6e662b374dea5624fe2804baeac50564f2505c919d57a26e33e6a77a"
FROZEN_AMENDMENT_SHA = "035f9e2a6bce4a4cd3248e6bc401e6b6c077911542af8023572c58eb05724fcd"
EXPECTED_RUNTIME = {"cedar_commit": CEDAR_COMMIT, "python": "3.11.9", "torch": "2.0.1+cpu", "torchvision": "0.15.2+cpu", "torch_threads": 1}
HEX64 = set("0123456789abcdef")
DEPENDENCY_FILES = {
    "p5a": ROOT / "experiments" / "autocontract_p5a_constraint_compiler.py",
    "p5m": ROOT / "experiments" / "autocontract_p5m_relation_boundary_falsification.py",
    "v0": ROOT / "experiments" / "autocontract_reorder_capability_v0.py",
    "v2": ROOT / "experiments" / "autocontract_reorder_capability_v2.py",
    "v3": ROOT / "experiments" / "autocontract_reorder_capability_v3.py",
    "r3_source_index_v1": ROOT / "experiments" / "autocontract_r3_source_index_v1.py",
    "r3_source_index_v0": ROOT / "experiments" / "autocontract_r3_source_index.py",
    "manifest_schema": MANIFEST_SCHEMA,
}
FROZEN_DEPENDENCY_CLOSURE = {
    "p5a": "c96ed767f97ecd82d6ea7bc574d4a0211bb530464ec42c9960d9459598f5d0ab",
    "p5m": "42ac1f44c01e027467d87216f76e78fb89a0cdc610cf544130687ca7c71e52ec",
    "v0": "77da9d207f62a3e732f5242aebf76bcdae43acebf16baa02cbb3f9879d93a5ae",
    "v2": "26d5e37606c6098b2009832706c04fd0ff99dde377d91ffdaf80041b1b3b4e35",
    "v3": "f74b37993e7dc5d4b5c304c7f3f0facabfae61ca4eecc9a8896bae372d179333",
    "r3_source_index_v1": "7e6251c0388fce23c115919258ac43fb9d620ea38f8902082fe6da7cfbb5238c",
    "r3_source_index_v0": "02a10103e26cb4a55f646428d7e24f14bdf73b133149e29c220a78f38829ab2b",
    "manifest_schema": "d57d0710722c97fc587b863b4433c6eecf754aa03afcae7631f81e72ecc0794d",
}


class P5SError(ValueError): pass
def require(ok: bool, message: str) -> None:
    if not ok: raise P5SError(message)
def sha(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda:f.read(1024*1024),b""): h.update(block)
    return h.hexdigest()
def is_sha256(value: Any) -> bool:
    return isinstance(value,str) and len(value)==64 and set(value)<=HEX64
def exact_keys(value: Any, keys: set[str], message: str) -> dict[str,Any]:
    require(isinstance(value,dict) and set(value)==keys,message); return value
def finite_number(value: Any, message: str, *, positive: bool=False) -> float:
    require(type(value) in (int,float) and math.isfinite(float(value)) and (not positive or float(value)>0),message); return float(value)
def dependency_closure() -> dict[str,str]:
    closure={name:sha(path) for name,path in DEPENDENCY_FILES.items()}
    require(closure==FROZEN_DEPENDENCY_CLOSURE,"dependency_closure_drift")
    # V2 deliberately depends on V1 for portable indexes and V0 for canonical receipts.
    v2_source=DEPENDENCY_FILES["v2"].read_text(encoding="utf-8")
    require("import autocontract_r3_source_index_v1 as source_index_v1" in v2_source and "import autocontract_reorder_capability_v0 as v0" in v2_source,"v2_source_index_import_closure_drift")
    return closure
def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
def write_yaml(path: Path, records: dict[int,dict[str,float|int]]) -> None:
    lines=["baseline:","  input_sizes:"]
    for node in range(6): lines.append(f"    {node}: {records[node]['input']}")
    lines.append("  latencies:")
    for node in range(6): lines.append(f"    {node}: {float(records[node]['latency']):.9f}")
    lines.append("  output_sizes:")
    for node in range(6): lines.append(f"    {node}: {records[node]['output']}")
    lines.append("  throughput: 1")
    path.write_text("\n".join(lines)+"\n",encoding="utf-8")
def seed_everything(seed:int) -> None:
    random.seed(seed); np.random.seed(seed%(2**32-1)); torch.manual_seed(seed)
def rng_digest()->dict[str,str]:
    return {"python":hashlib.sha256(pickle.dumps(random.getstate(),protocol=4)).hexdigest(),"numpy":hashlib.sha256(pickle.dumps(np.random.get_state(),protocol=4)).hexdigest(),"torch":hashlib.sha256(torch.get_rng_state().numpy().tobytes()).hexdigest()}
def tensor_digest(value:torch.Tensor)->str:
    x=value.detach().cpu().contiguous(); h=hashlib.sha256(); h.update(str(x.dtype).encode()); h.update(json.dumps(list(x.shape)).encode()); h.update(x.numpy().tobytes()); return h.hexdigest()
def named_digest(items:list[tuple[str,torch.Tensor]])->str:
    h=hashlib.sha256()
    for name,value in sorted(items): h.update(name.encode()); h.update(tensor_digest(value).encode())
    return h.hexdigest()
def tensor_record(value:torch.Tensor)->dict[str,Any]:
    x=value.detach().cpu().contiguous()
    return {"sha256":tensor_digest(x),"shape":list(x.shape),"dtype":str(x.dtype),"bytes":x.numel()*x.element_size()}
def ordered_path(graph:dict[int,set[int]])->list[int]:
    node=max(graph); path=[node]
    while graph[node]: require(len(graph[node])==1,"nonlinear_cedar_plan"); node=next(iter(graph[node])); path.append(node)
    return path
def plan_tags(feature:Any, graph:dict[int,set[int]])->list[str]:
    return [str(getattr(feature.logical_pipes[n],"tag","")) for n in ordered_path(graph) if getattr(feature.logical_pipes.get(n),"tag",None)]
def check(checks:list[dict[str,Any]], name:str, passed:bool, observed:Any=None)->None:
    item={"name":name,"passed":bool(passed)}
    if observed is not None:item["observed"]=observed
    checks.append(item)


def load_manifest() -> tuple[dict[str,Any],list[dict[str,Any]]]:
    import jsonschema
    manifest=json.loads(MANIFEST.read_text(encoding="utf-8")); schema=json.loads(MANIFEST_SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(manifest,schema)
    require(manifest["status"]=="acquired" and manifest["license_accepted"] is True,"manifest_not_acquired")
    require(sha(MANIFEST)=="255c725ea321b653925cd530f2664c7760d6d651745cf200258b58d9661005c8","manifest_sha_drift")
    archive=manifest["archive"]; archive_path=Path(archive["path"])
    require(archive["bytes"]==448993893 and archive["zip_crc_checked"] is True and len(archive["sha256"])==64,"frozen_archive_record_invalid")
    files=manifest["files"]
    require([x["name"] for x in files]==[f"{i:04d}.png" for i in range(801,901)],"manifest_filename_set")
    require(Counter(x["fold"] for x in files)=={"calibration":10,"A":32,"B":32,"reserved":26},"manifest_fold_counts")
    dataset=archive_path.parent/"DIV2K_valid_HR"; require(dataset.is_dir(),"dataset_missing")
    return manifest,files


def verify_used_files(manifest:dict[str,Any], files:list[dict[str,Any]]) -> dict[str,Any]:
    """Validate only the selected fixed fold; profile must never decode A/B images."""
    dataset=Path(manifest["archive"]["path"]).parent/"DIV2K_valid_HR"
    warmed=0; names=[]
    for item in files:
        p=dataset/item["name"]; require(p.is_file() and p.stat().st_size==item["bytes"] and sha(p)==item["sha256"],f"file_integrity:{item['name']}")
        with Image.open(p) as image: require(image.mode=="RGB" and image.width==item["width"] and image.height==item["height"] and image.width>=224 and image.height>=224,f"file_decode_metadata:{item['name']}")
        warmed+=item["bytes"]; names.append(item["name"])
    return {"procedure":"timer-outside SHA-256 verification reads each selected PNG once; OS cache is thereby warmed before feature construction","fold":files[0]["fold"],"files":names,"files_count":len(names),"bytes_read":warmed,"archive_attestation":"not reread here; acquisition manifest is the frozen archive-attestation boundary"}


class StreamOps:
    """Stateful counters make accidental pre-decode visible in every measured arm."""
    def __init__(self, domain:dict[str,Any]): self.domain=domain; self.open_count=0; self.decode_count=0
    def decode(self, path:str)->torch.Tensor:
        self.open_count+=1
        with Image.open(path) as image:
            require(image.mode=="RGB",f"stream_not_rgb:{Path(path).name}")
            array=np.array(image,dtype=np.uint8,copy=True)
        self.decode_count+=1
        return torch.from_numpy(array).permute(2,0,1).contiguous()
    def to_float(self,x:torch.Tensor)->torch.Tensor: return x.to(torch.float32).div_(255.0)
    def guard(self,x:torch.Tensor)->torch.Tensor:
        require(x.dtype==torch.float32 and x.ndim==3 and x.shape[0]==3 and torch.isfinite(x).all().item(),"runtime_domain_dtype_or_finite")
        require(float(x.min())>=0.0 and float(x.max())<=1.0 and self.domain["height_min"]<=x.shape[1]<=self.domain["height_max"] and self.domain["width_min"]<=x.shape[2]<=self.domain["width_max"],"runtime_domain_membership")
        return x


def build_feature(recipe:list[dict[str,Any]], paths:list[str], ops:dict[str,Any])->Any:
    from cedar.compose import Feature
    from cedar.pipes import MapperPipe
    from cedar.sources import IterSource
    class FiveNodeFeature(Feature):
        def _compose(self,sources:list[Any])->Any:
            pipe=sources[0]
            for hint,operator_id in zip(recipe,IDS,strict=True):
                pipe=MapperPipe(pipe,ops[operator_id],tag=hint["tag"],is_random=hint["random"])
                if hint["fix"]: pipe=pipe.fix()
            return pipe
    feature=FiveNodeFeature(); feature.apply(IterSource(paths)); return feature


def v3_context(files:list[dict[str,Any]])->tuple[dict[str,Any],dict[str,Any],dict[str,Any],Any]:
    sys.path.insert(0,str(ROOT/"experiments"))
    import autocontract_p5a_constraint_compiler as compiler
    import autocontract_p5m_relation_boundary_falsification as p5m
    import autocontract_reorder_capability_v0 as v0
    import autocontract_reorder_capability_v2 as v2cap
    import autocontract_reorder_capability_v3 as v3
    domain=p5m.input_domain(); domain.update({"height_min":min(x["height"] for x in files),"height_max":max(x["height"] for x in files),"width_min":min(x["width"] for x in files),"width_max":max(x["width"] for x in files)})
    semantic={"normalize":v2.Normalize([.45,.4,.35],[.25,.3,.35]),"random_crop":v2.RandomCrop((224,224))}
    base=p5m.make_bundle(compiler,v0,v2cap,["normalize","random_crop"],semantic,domain)
    receipt=v2cap.make_verified_receipt(base,"normalize","random_crop",semantic,domain)
    return domain,semantic,base,(v2cap,receipt,v3)


def cedar_options()->Any:
    from cedar.compose import OptimizerOptions
    return OptimizerOptions(enable_prefetch=False,available_local_cpus=1,enable_offload=False,enable_reorder=True,enable_local_parallelism=False,enable_fusion=False,enable_caching=False,disable_physical_opt=True,num_samples=10)


def profile_records(paths:list[str], domain:dict[str,Any], semantic:dict[str,Any], seed:int)->dict[int,dict[str,float|int]]:
    stream=StreamOps(domain); operators=[stream.decode,stream.to_float,stream.guard,semantic["normalize"],semantic["random_crop"]]
    current: list[Any]=paths[:] ; records={5:{"input":0,"output":sum(Path(x).stat().st_size for x in paths),"latency":0.001}}
    for node,operator in zip((4,3,2,1,0),operators,strict=True):
        seed_everything(seed); before=sum((x.numel()*x.element_size()) if isinstance(x,torch.Tensor) else Path(x).stat().st_size for x in current)
        started=time.perf_counter_ns(); current=[operator(x) for x in current]; elapsed=(time.perf_counter_ns()-started)/1e6
        after=sum(x.numel()*x.element_size() for x in current); records[node]={"input":before,"output":after,"latency":max(elapsed/len(paths),.001)}
    require(stream.open_count==len(paths) and stream.decode_count==len(paths),"profile_stream_count")
    return records


def compile_arms(files:list[dict[str,Any]], paths:list[str])->tuple[dict[str,Any],dict[str,Any],dict[str,Any],dict[str,Any],list[dict[str,Any]]]:
    domain,semantic,base,parts=v3_context(files); v2cap,receipt,v3=parts
    baseline=v3.compile_relation_aware(base,[],semantic,domain); authorized=v3.compile_relation_aware(base,[receipt],semantic,domain)
    checks=[]; check(checks,"receipt_verified_exact_pair",authorized["pair_audit"]==[{"pair":["normalize","random_crop"],"verified":True,"reason":"locally_replayed_relation_supported"}])
    bad=copy.deepcopy(receipt); bad["left"]["source_index_sha256"]="0"*64
    mixed=v3.compile_relation_aware(base,[receipt,bad],semantic,domain)
    config={**semantic,"normalize":v2.Normalize([.46,.4,.35],[.25,.3,.35])}
    domain_bad={**domain,"height_min":223}
    negatives={"no":baseline,"tampered":v3.compile_relation_aware(base,[bad],semantic,domain),"mixed":mixed,"config":v3.compile_relation_aware(base,[receipt],config,domain),"domain":v3.compile_relation_aware(base,[receipt],semantic,domain_bad)}
    check(checks,"negative_receipts_fail_closed",all(x["candidate_count"]==1 for x in negatives.values()),{k:x["candidate_count"] for k,x in negatives.items()})
    return domain,semantic,baseline,authorized,checks


def execute_preprocess(recipe:dict[str,Any], paths:list[str], domain:dict[str,Any], semantic:dict[str,Any], *, timed:bool=False)->dict[str,Any]:
    from cedar.compose.utils import calculate_reorderings
    from cedar.config import CedarContext
    stream=StreamOps(domain); ops={"decode":stream.decode,"to_float":stream.to_float,"guard":stream.guard,**semantic}
    feature=build_feature(recipe["backends"]["cedar"]["operators"],paths,ops)
    candidates=calculate_reorderings(feature.logical_pipes,feature.logical_adj_list)
    require(len(candidates)==recipe["candidate_count"],f"cedar_candidate_mismatch:{len(candidates)}")
    plan=feature.optimize(cedar_options(),str(PROFILE))
    tags=plan_tags(feature,plan.graph)
    if timed: started=time.perf_counter_ns()
    iterator=feature.load_from_plan(CedarContext(),plan)
    outputs=[item.data for item in iterator]
    elapsed=(time.perf_counter_ns()-started)/1e6 if timed else None
    require(stream.open_count==len(paths) and stream.decode_count==len(paths),"measured_arm_open_decode_count")
    return {"candidate_count":len(candidates),"tags":tags,"fix":[x["fix"] for x in recipe["backends"]["cedar"]["operators"]],"random_crop_random":recipe["backends"]["cedar"]["operators"][-1]["random"],"outputs":outputs,"shapes":[list(x.shape) for x in outputs],"rng":rng_digest(),"open_count":stream.open_count,"decode_count":stream.decode_count,"wall_ms":elapsed}


def train(outputs:list[torch.Tensor], labels:torch.Tensor, seed:int)->dict[str,Any]:
    seed_everything(seed); model=mobilenet_v3_small(weights=None,num_classes=10); model.train(); opt=torch.optim.SGD(model.parameters(),lr=.01,momentum=0.0)
    opt.zero_grad(set_to_none=True); logits=model(torch.stack(outputs)); loss=functional.cross_entropy(logits,labels); loss.backward(); opt.step()
    grads=[(name,p.grad) for name,p in model.named_parameters() if p.grad is not None]
    require(all(torch.isfinite(x).all().item() for x in outputs),"train_nonfinite_outputs")
    require(torch.isfinite(loss).all().item() and torch.isfinite(logits).all().item(),"train_nonfinite_loss_or_logits")
    require(all(torch.isfinite(value).all().item() for _,value in grads),"train_nonfinite_gradients")
    require(all(torch.isfinite(value).all().item() for _,value in model.state_dict().items() if value.is_floating_point()),"train_nonfinite_model_state")
    return {"loss_hex":float(loss.detach()).hex(),"logits":tensor_digest(logits.detach()),"gradients":named_digest(grads),"model_state":named_digest(list(model.state_dict().items()))}


def execute_e2e_timed(recipe:dict[str,Any], paths:list[str], domain:dict[str,Any], semantic:dict[str,Any], labels:torch.Tensor, seed:int)->dict[str,Any]:
    """The frozen confirm arm: planning/model construction are outside this timer."""
    from cedar.compose.utils import calculate_reorderings
    from cedar.config import CedarContext
    stream=StreamOps(domain); ops={"decode":stream.decode,"to_float":stream.to_float,"guard":stream.guard,**semantic}
    feature=build_feature(recipe["backends"]["cedar"]["operators"],paths,ops)
    candidates=calculate_reorderings(feature.logical_pipes,feature.logical_adj_list); require(len(candidates)==recipe["candidate_count"],"confirm_candidate_mismatch")
    plan=feature.optimize(cedar_options(),str(PROFILE))  # optimizer planning outside the warm primary timer
    seed_everything(seed); model=mobilenet_v3_small(weights=None,num_classes=10); model.train(); optimizer=torch.optim.SGD(model.parameters(),lr=.01,momentum=0.0)
    seed_everything(seed)
    started=time.perf_counter_ns()
    iterator=feature.load_from_plan(CedarContext(),plan)
    outputs=[item.data for item in iterator]
    optimizer.zero_grad(set_to_none=True); logits=model(torch.stack(outputs)); loss=functional.cross_entropy(logits,labels); loss.backward(); optimizer.step()
    wall_ms=(time.perf_counter_ns()-started)/1e6
    require(stream.open_count==len(paths) and stream.decode_count==len(paths),"confirm_arm_open_decode_count")
    grads=[(name,p.grad) for name,p in model.named_parameters() if p.grad is not None]
    require(all(torch.isfinite(x).all().item() for x in outputs),"confirm_nonfinite_outputs")
    require(torch.isfinite(loss).all().item() and torch.isfinite(logits).all().item(),"confirm_nonfinite_loss_or_logits")
    require(all(torch.isfinite(value).all().item() for _,value in grads),"confirm_nonfinite_gradients")
    require(all(torch.isfinite(value).all().item() for _,value in model.state_dict().items() if value.is_floating_point()),"confirm_nonfinite_model_state")
    hints=recipe["backends"]["cedar"]["operators"]
    return {"wall_ms":wall_ms,"candidate_count":len(candidates),"tags":plan_tags(feature,plan.graph),"fix":[x["fix"] for x in hints],"random_crop_random":hints[-1]["random"],"tensors":[tensor_record(x) for x in outputs],"shapes":[list(x.shape) for x in outputs],"open_count":stream.open_count,"decode_count":stream.decode_count,"rng":rng_digest(),"loss_hex":float(loss.detach()).hex(),"logits":tensor_digest(logits.detach()),"gradients":named_digest(grads),"model_state":named_digest(list(model.state_dict().items()))}


def runtime_record(cedar_root:Path)->dict[str,Any]:
    head=subprocess.run(["git","-C",str(cedar_root),"rev-parse","HEAD"],check=True,capture_output=True,text=True).stdout.strip(); status=subprocess.run(["git","-C",str(cedar_root),"status","--porcelain=v1"],check=True,capture_output=True,text=True).stdout.strip()
    require(head==CEDAR_COMMIT and not status,"cedar_not_pinned_clean")
    runtime={"cedar_commit":head,"python":sys.version.split()[0],"torch":torch.__version__,"torchvision":__import__("torchvision").__version__,"torch_threads":torch.get_num_threads()}
    require(runtime==EXPECTED_RUNTIME,"runtime_not_exactly_frozen")
    return runtime


def common(cedar_root:Path, fold:str)->tuple[dict[str,Any],dict[str,Any],list[dict[str,Any]],list[str],dict[str,Any],dict[str,Any]]:
    protocol=json.loads(PROTOCOL.read_text(encoding="utf-8")); require(sha(PROTOCOL)==FROZEN_PROTOCOL_SHA and protocol["schema_version"]=="autocontract.p5s-div2k-e2e-protocol.v2" and sha(AMENDMENT)==FROZEN_AMENDMENT_SHA,"protocol_or_amendment_drift"); dependency_closure()
    manifest,all_files=load_manifest(); files=[x for x in all_files if x["fold"]==fold]; require(files,"empty_fold"); warming=verify_used_files(manifest,files)
    paths=[str(Path(manifest["archive"]["path"]).parent/"DIV2K_valid_HR"/x["name"]) for x in files]
    if str(cedar_root) not in sys.path: sys.path.insert(0,str(cedar_root))
    torch.set_num_threads(1); torch.use_deterministic_algorithms(True); runtime=runtime_record(cedar_root)
    return protocol,manifest,files,paths,runtime,warming


def profile(cedar_root:Path, output:Path)->dict[str,Any]:
    protocol,manifest,files,paths,runtime,warming=common(cedar_root,"calibration"); domain,semantic,baseline,authorized,checks=compile_arms(files,paths)
    records=profile_records(paths,domain,semantic,BOOTSTRAP_SEED); write_yaml(PROFILE,records)
    check(checks,"five_node_profile_generated_from_calibration_only",PROFILE.is_file(),{"nodes":sorted(records),"fold":"calibration"})
    result={"schema_version":"autocontract.p5s-phase.v1","phase":"profile","status":"pass" if all(x["passed"] for x in checks) else "fail","scientific_evidence":False,"protocol_sha256":sha(PROTOCOL),"runner_sha256":sha(Path(__file__)),"manifest_sha256":sha(MANIFEST),"manifest_schema_sha256":sha(MANIFEST_SCHEMA),"dependency_closure":dependency_closure(),"workload_profile":{"path":str(PROFILE.relative_to(ROOT)),"sha256":sha(PROFILE),"records":records},"manifest_fold":"calibration","cache_warming":warming,"runtime":runtime,"checks":checks,"claim_boundary":"Calibration/profile only; no fold A/B confirmation, aggregate, or benefit result."}
    write_json(output,result); return result


def smoke(cedar_root:Path, profile_output:Path, output:Path)->dict[str,Any]:
    protocol,manifest,files,paths,runtime,warming=common(cedar_root,"calibration"); prior=json.loads(profile_output.read_text(encoding="utf-8")); require(prior["phase"]=="profile" and prior["status"]=="pass" and prior["scientific_evidence"] is False and prior["protocol_sha256"]==sha(PROTOCOL) and prior["runner_sha256"]==sha(Path(__file__)) and prior["manifest_sha256"]==sha(MANIFEST) and prior["manifest_schema_sha256"]==sha(MANIFEST_SCHEMA) and prior["dependency_closure"]==dependency_closure() and prior["workload_profile"]["sha256"]==sha(PROFILE),"profile_not_frozen")
    domain,semantic,baseline,authorized,checks=compile_arms(files,paths)
    seed_everything(BOOTSTRAP_SEED); left=execute_preprocess(baseline,paths,domain,semantic); seed_everything(BOOTSTRAP_SEED); right=execute_preprocess(authorized,paths,domain,semantic)
    check(checks,"actual_cedar_candidates_and_rng",left["candidate_count"]==1 and right["candidate_count"]==2 and right["random_crop_random"] and left["rng"]==right["rng"],{"baseline":left["candidate_count"],"authorized":right["candidate_count"]})
    left_order=[x for x in left["tags"] if not x.startswith("IterSourcePipe_")]; right_order=[x for x in right["tags"] if not x.startswith("IterSourcePipe_")]
    check(checks,"actual_cedar_orders",left_order==["autocontract:decode","autocontract:to_float","autocontract:guard","autocontract:normalize","autocontract:random_crop"] and right_order==["autocontract:decode","autocontract:to_float","autocontract:guard","autocontract:random_crop","autocontract:normalize"],{"baseline":left_order,"authorized":right_order})
    exact=len(left["outputs"])==len(right["outputs"])==len(paths) and all(torch.equal(a,b) for a,b in zip(left["outputs"],right["outputs"],strict=True))
    labels=torch.tensor([int(Path(p).stem)%10 for p in paths],dtype=torch.long); a=train(left["outputs"],labels,BOOTSTRAP_SEED); b=train(right["outputs"],labels,BOOTSTRAP_SEED)
    check(checks,"tensor_shape_definedness_exact",exact and left["shapes"]==right["shapes"])
    check(checks,"loss_logits_gradient_model_exact",a==b,{"baseline":a,"authorized":b})
    result={"schema_version":"autocontract.p5s-phase.v1","phase":"smoke","status":"pass" if all(x["passed"] for x in checks) else "fail","scientific_evidence":False,"protocol_sha256":sha(PROTOCOL),"runner_sha256":sha(Path(__file__)),"manifest_sha256":sha(MANIFEST),"manifest_schema_sha256":sha(MANIFEST_SCHEMA),"dependency_closure":dependency_closure(),"workload_profile_sha256":sha(PROFILE),"profile_output_sha256":sha(profile_output),"cache_warming":warming,"runtime":runtime,"fold":"calibration","arms":{"baseline":{k:v for k,v in left.items() if k!="outputs"},"authorized":{k:v for k,v in right.items() if k!="outputs"}},"checks":checks,"claim_boundary":"Calibration semantic smoke only. Timers are deliberately absent; no final benefit result is produced."}
    write_json(output,result); return result


def expected_warming(manifest:dict[str,Any], fold:str)->dict[str,Any]:
    files=[x for x in manifest["files"] if x["fold"]==fold]
    require(len(files)==32,"confirm_warming_fold_count")
    return {"procedure":"timer-outside SHA-256 verification reads each selected PNG once; OS cache is thereby warmed before feature construction","fold":fold,"files":[x["name"] for x in files],"files_count":32,"bytes_read":sum(x["bytes"] for x in files),"archive_attestation":"not reread here; acquisition manifest is the frozen archive-attestation boundary"}


def validate_warming(value:Any, manifest:dict[str,Any], fold:str)->None:
    expected=expected_warming(manifest,fold)
    exact_keys(value,set(expected),"confirm_cache_warming_keys")
    require(value==expected,"confirm_cache_warming_manifest_mismatch")


def validate_freeze(expected_freeze_sha:str) -> dict[str,Any]:
    require(is_sha256(expected_freeze_sha),"expected_freeze_sha_invalid")
    require(FREEZE.is_file(),"execution_freeze_missing")
    require(sha(FREEZE)==expected_freeze_sha,"execution_freeze_review_anchor_mismatch")
    freeze=json.loads(FREEZE.read_text(encoding="utf-8"))
    keys={"schema_version","phase","status","scientific_evidence","protocol_sha256","runner_sha256","dependency_closure","manifest_sha256","manifest_schema_sha256","amendment_sha256","profile_sha256","profile_output_sha256","smoke_output_sha256","confirm_control_selftest_sha256"}
    exact_keys(freeze,keys,"execution_freeze_keys")
    require(freeze["schema_version"]=="autocontract.p5s-execution-freeze.v2" and freeze["phase"]=="freeze" and freeze["status"]=="pass" and freeze["scientific_evidence"] is False,"execution_freeze_status")
    require(freeze["protocol_sha256"]==sha(PROTOCOL) and freeze["runner_sha256"]==sha(Path(__file__)) and freeze["dependency_closure"]==dependency_closure() and freeze["manifest_sha256"]==sha(MANIFEST) and freeze["manifest_schema_sha256"]==sha(MANIFEST_SCHEMA) and freeze["amendment_sha256"]==sha(AMENDMENT) and freeze["profile_sha256"]==sha(PROFILE),"execution_freeze_binding")
    profile_path=ROOT/"outputs"/"autocontract_p5s_div2k_profile.json"; smoke_path=ROOT/"outputs"/"autocontract_p5s_div2k_smoke.json"
    require(freeze["profile_output_sha256"]==sha(profile_path) and freeze["smoke_output_sha256"]==sha(smoke_path) and CONTROL_SELFTEST.is_file() and freeze["confirm_control_selftest_sha256"]==sha(CONTROL_SELFTEST),"execution_freeze_phase_output_binding")
    return freeze


def validate_launcher(expected_freeze_sha:str, launcher_path:Path, launcher_sha:str) -> None:
    require(is_sha256(launcher_sha) and launcher_path.resolve()==LAUNCHER.resolve() and LAUNCHER.is_file() and sha(LAUNCHER)==launcher_sha,"launcher_sha_or_path_mismatch")
    source=LAUNCHER.read_text(encoding="utf-8")
    require(f'EXPECTED_FREEZE_SHA = "{expected_freeze_sha}"' in source and f'EXPECTED_RUNNER_SHA = "{sha(Path(__file__))}"' in source and f'EXPECTED_PROTOCOL_SHA = "{sha(PROTOCOL)}"' in source,"launcher_anchor_constants_mismatch")


def freeze(profile_output:Path, smoke_output:Path, control_selftest_output:Path)->dict[str,Any]:
    require(not FREEZE.exists(),"execution_freeze_already_exists")
    require(profile_output.resolve()==(ROOT/"outputs"/"autocontract_p5s_div2k_profile.json").resolve() and smoke_output.resolve()==(ROOT/"outputs"/"autocontract_p5s_div2k_smoke.json").resolve() and control_selftest_output.resolve()==CONTROL_SELFTEST.resolve(),"freeze_requires_canonical_phase_outputs")
    profile_value=json.loads(profile_output.read_text(encoding="utf-8")); smoke_value=json.loads(smoke_output.read_text(encoding="utf-8")); control_value=json.loads(control_selftest_output.read_text(encoding="utf-8"))
    require(profile_value.get("phase")=="profile" and profile_value.get("status")=="pass" and smoke_value.get("phase")=="smoke" and smoke_value.get("status")=="pass" and control_value.get("phase")=="confirm-control-selftest" and control_value.get("status")=="pass","freeze_requires_passed_profile_smoke_control")
    for value in (profile_value,smoke_value):
        require(value.get("protocol_sha256")==sha(PROTOCOL) and value.get("runner_sha256")==sha(Path(__file__)) and value.get("manifest_sha256")==sha(MANIFEST) and value.get("manifest_schema_sha256")==sha(MANIFEST_SCHEMA) and value.get("dependency_closure")==dependency_closure(),"freeze_phase_binding")
    require(control_value.get("protocol_sha256")==sha(PROTOCOL) and control_value.get("runner_sha256")==sha(Path(__file__)) and control_value.get("manifest_sha256")==sha(MANIFEST) and control_value.get("manifest_schema_sha256")==sha(MANIFEST_SCHEMA) and control_value.get("dependency_closure")==dependency_closure(),"freeze_control_selftest_binding")
    return {"schema_version":"autocontract.p5s-execution-freeze.v2","phase":"freeze","status":"pass","scientific_evidence":False,"protocol_sha256":sha(PROTOCOL),"runner_sha256":sha(Path(__file__)),"dependency_closure":dependency_closure(),"manifest_sha256":sha(MANIFEST),"manifest_schema_sha256":sha(MANIFEST_SCHEMA),"amendment_sha256":sha(AMENDMENT),"profile_sha256":sha(PROFILE),"profile_output_sha256":sha(profile_output),"smoke_output_sha256":sha(smoke_output),"confirm_control_selftest_sha256":sha(control_selftest_output)}


def confirm_block_semantic_pass(arms:dict[str,dict[str,Any]], expected_count:int)->bool:
    prefix=["autocontract:decode","autocontract:to_float","autocontract:guard"]
    base_order=[x for x in arms["baseline"]["tags"] if not x.startswith("IterSourcePipe_")]
    auth_order=[x for x in arms["authorized"]["tags"] if not x.startswith("IterSourcePipe_")]
    return (arms["baseline"]["candidate_count"]==1 and arms["authorized"]["candidate_count"]==2 and arms["baseline"]["fix"]==[True]*5 and arms["authorized"]["fix"]==[True,True,True,False,False] and arms["baseline"]["random_crop_random"] is True and arms["authorized"]["random_crop_random"] is True and base_order==prefix+["autocontract:normalize","autocontract:random_crop"] and auth_order==prefix+["autocontract:random_crop","autocontract:normalize"] and all(arms[name]["open_count"]==arms[name]["decode_count"]==expected_count for name in ("baseline","authorized")) and arms["baseline"]["tensors"]==arms["authorized"]["tensors"] and arms["baseline"]["shapes"]==arms["authorized"]["shapes"] and arms["baseline"]["rng"]==arms["authorized"]["rng"] and all(arms["baseline"][name]==arms["authorized"][name] for name in ("loss_hex","logits","gradients","model_state")))


def run_confirm_blocks(baseline:dict[str,Any], authorized:dict[str,Any], semantic_ops:dict[str,Any], expected_count:int, blocks:int, executor:Any)->tuple[list[dict[str,Any]],bool]:
    """Run AB/BA blocks while preserving the semantic operator mapping by identity."""
    require(isinstance(semantic_ops,dict),"confirm_semantic_operator_mapping_corrupted")
    pairs=[]; all_semantic_pass=True
    for index in range(blocks):
        require(isinstance(semantic_ops,dict),"confirm_semantic_operator_mapping_corrupted")
        order=("baseline","authorized") if index%2==0 else ("authorized","baseline"); arms={}
        for arm in order:
            recipe=baseline if arm=="baseline" else authorized
            arms[arm]=executor(recipe,semantic_ops,BOOTSTRAP_SEED+index,arm)
        block_semantic_pass=confirm_block_semantic_pass(arms,expected_count)
        all_semantic_pass=all_semantic_pass and block_semantic_pass
        pairs.append({"block":index+1,"order":list(order),"authorized_over_baseline":arms["authorized"]["wall_ms"]/arms["baseline"]["wall_ms"],"semantic_pass":block_semantic_pass,"arms":arms})
    return pairs,all_semantic_pass


def confirm(cedar_root:Path, fold:str, profile_output:Path, output:Path, expected_freeze_sha:str, launcher_path:Path, launcher_sha:str)->dict[str,Any]:
    """Frozen 15-block AB/BA confirm implementation; intentionally not called in this task."""
    require(fold in ("A","B"),"confirm_fold_must_be_A_or_B"); validate_freeze(expected_freeze_sha); validate_launcher(expected_freeze_sha,launcher_path,launcher_sha); protocol,manifest,files,paths,runtime,warming=common(cedar_root,fold); prior=json.loads(profile_output.read_text(encoding="utf-8")); require(prior["phase"]=="profile" and prior["status"]=="pass" and prior["scientific_evidence"] is False and prior["protocol_sha256"]==sha(PROTOCOL) and prior["runner_sha256"]==sha(Path(__file__)) and prior["manifest_sha256"]==sha(MANIFEST) and prior["manifest_schema_sha256"]==sha(MANIFEST_SCHEMA) and prior["dependency_closure"]==dependency_closure() and prior["workload_profile"]["sha256"]==sha(PROFILE),"confirm_profile_mismatch")
    domain,semantic_ops,baseline,authorized,_=compile_arms(files,paths); labels=torch.tensor([int(Path(p).stem)%10 for p in paths],dtype=torch.long)
    def executor(recipe:dict[str,Any], operators:dict[str,Any], seed:int, arm:str)->dict[str,Any]:
        return execute_e2e_timed(recipe,paths,domain,operators,labels,seed)
    pairs,all_semantic_pass=run_confirm_blocks(baseline,authorized,semantic_ops,len(paths),15,executor)
    result={"schema_version":"autocontract.p5s-confirm.v1","phase":"confirm","status":"pass" if all_semantic_pass else "fail","scientific_evidence":False,"pid":os.getpid(),"uuid":str(uuid.uuid4()),"utc":datetime.now(UTC).isoformat(),"fold":fold,"protocol_sha256":sha(PROTOCOL),"runner_sha256":sha(Path(__file__)),"profile_sha256":sha(PROFILE),"profile_output_sha256":sha(profile_output),"manifest_sha256":sha(MANIFEST),"manifest_schema_sha256":sha(MANIFEST_SCHEMA),"dependency_closure":dependency_closure(),"execution_freeze_sha256":sha(FREEZE),"review_authorized_freeze_sha":expected_freeze_sha,"launcher_sha256":launcher_sha,"cache_warming":warming,"pairs":pairs,"runtime":runtime,"timer_boundary":TIMER_BOUNDARY,"semantic_pass":all_semantic_pass}
    write_json(output,result); return result


def confirm_control_selftest(cedar_root:Path, output:Path)->dict[str,Any]:
    """Regression coverage only: synthetic 15 blocks plus calibration-only 2 blocks; never A/B."""
    checks=[]; synthetic_ops={"normalize":object(),"random_crop":object()}; synthetic_calls=[]
    def fake_arm(authorized:bool)->dict[str,Any]:
        return {"wall_ms":9.0 if authorized else 10.0,"candidate_count":2 if authorized else 1,"tags":["IterSourcePipe_5","autocontract:decode","autocontract:to_float","autocontract:guard"]+(["autocontract:random_crop","autocontract:normalize"] if authorized else ["autocontract:normalize","autocontract:random_crop"]),"fix":[True,True,True,False,False] if authorized else [True]*5,"random_crop_random":True,"tensors":[{"sha256":"a"*64,"shape":[3,224,224],"dtype":"torch.float32","bytes":602112} for _ in range(32)],"shapes":[[3,224,224] for _ in range(32)],"open_count":32,"decode_count":32,"rng":{"python":"b"*64,"numpy":"c"*64,"torch":"d"*64},"loss_hex":"0x1p+0","logits":"e"*64,"gradients":"f"*64,"model_state":"0"*64}
    def fake_executor(recipe:dict[str,Any], operators:dict[str,Any], seed:int, arm:str)->dict[str,Any]:
        synthetic_calls.append({"mapping_id":id(operators),"seed":seed,"arm":arm}); return fake_arm(arm=="authorized")
    fake_pairs,fake_pass=run_confirm_blocks({"name":"baseline"},{"name":"authorized"},synthetic_ops,32,15,fake_executor)
    check(checks,"synthetic_15_block_control_flow",fake_pass and len(synthetic_calls)==30 and all(item["mapping_id"]==id(synthetic_ops) for item in synthetic_calls),{"calls":len(synthetic_calls)})
    check(checks,"synthetic_exact_ab_ba_order",[pair["order"] for pair in fake_pairs]==[["baseline","authorized"] if index%2 else ["authorized","baseline"] for index in range(1,16)])
    protocol,manifest,files,paths,runtime,warming=common(cedar_root,"calibration"); domain,semantic_ops,baseline,authorized,arm_checks=compile_arms(files,paths); calibration_calls=[]; labels=torch.tensor([int(Path(path).stem)%10 for path in paths],dtype=torch.long)
    def calibration_executor(recipe:dict[str,Any], operators:dict[str,Any], seed:int, arm:str)->dict[str,Any]:
        calibration_calls.append({"mapping_id":id(operators),"arm":arm})
        return execute_e2e_timed(recipe,paths,domain,operators,labels,seed)
    _,calibration_pass=run_confirm_blocks(baseline,authorized,semantic_ops,len(paths),2,calibration_executor)
    check(checks,"calibration_only_two_blocks_four_real_arms",calibration_pass and len(calibration_calls)==4 and all(item["mapping_id"]==id(semantic_ops) for item in calibration_calls),{"fold":"calibration","calls":len(calibration_calls)})
    checks.extend(arm_checks)
    result={"schema_version":"autocontract.p5s-confirm-control-selftest.v1","phase":"confirm-control-selftest","status":"pass" if all(item["passed"] for item in checks) else "fail","scientific_evidence":False,"protocol_sha256":sha(PROTOCOL),"runner_sha256":sha(Path(__file__)),"manifest_sha256":sha(MANIFEST),"manifest_schema_sha256":sha(MANIFEST_SCHEMA),"dependency_closure":dependency_closure(),"runtime":runtime,"fold":"calibration","cache_warming":warming,"passed":sum(item["passed"] for item in checks),"total":len(checks),"checks":checks,"claim_boundary":"Synthetic control-flow and calibration-only regression coverage; no A/B confirmation data, ratios, or benefit evidence."}
    write_json(output,result); return result


def validate_tensor_record(value:Any)->None:
    exact_keys(value,{"sha256","shape","dtype","bytes"},"confirm_tensor_record_keys")
    require(is_sha256(value["sha256"]) and isinstance(value["shape"],list) and len(value["shape"])==3 and all(type(x) is int for x in value["shape"]) and value["shape"]==[3,224,224] and value["dtype"]=="torch.float32" and type(value["bytes"]) is int and value["bytes"]==602112,"confirm_tensor_record_invalid")


def validate_arm(value:Any, authorized:bool)->dict[str,Any]:
    keys={"wall_ms","candidate_count","tags","fix","random_crop_random","tensors","shapes","open_count","decode_count","rng","loss_hex","logits","gradients","model_state"}
    arm=exact_keys(value,keys,"confirm_arm_keys")
    finite_number(arm["wall_ms"],"confirm_wall_time_invalid",positive=True)
    expected_tags=["IterSourcePipe_5","autocontract:decode","autocontract:to_float","autocontract:guard"]+(["autocontract:random_crop","autocontract:normalize"] if authorized else ["autocontract:normalize","autocontract:random_crop"])
    require(isinstance(arm["tags"],list) and all(isinstance(x,str) for x in arm["tags"]),"confirm_tags_invalid")
    require(type(arm["candidate_count"]) is int and arm["candidate_count"]==(2 if authorized else 1) and isinstance(arm["fix"],list) and len(arm["fix"])==5 and all(type(x) is bool for x in arm["fix"]) and arm["fix"]==([True,True,True,False,False] if authorized else [True]*5) and type(arm["random_crop_random"]) is bool and arm["random_crop_random"] is True,"confirm_capability_gate")
    require(arm["tags"]==expected_tags,"confirm_order_gate")
    require(type(arm["open_count"]) is int and type(arm["decode_count"]) is int and arm["open_count"]==arm["decode_count"]==32,"confirm_stream_count_gate")
    require(isinstance(arm["tensors"],list) and len(arm["tensors"])==32 and isinstance(arm["shapes"],list) and len(arm["shapes"])==32,"confirm_tensor_count")
    for record in arm["tensors"]: validate_tensor_record(record)
    require(all(isinstance(shape,list) and len(shape)==3 and all(type(x) is int for x in shape) and shape==[3,224,224] for shape in arm["shapes"]),"confirm_shapes_invalid")
    exact_keys(arm["rng"],{"python","numpy","torch"},"confirm_rng_keys"); require(all(is_sha256(arm["rng"][name]) for name in ("python","numpy","torch")),"confirm_rng_digest_invalid")
    require(isinstance(arm["loss_hex"],str),"confirm_loss_hex_missing")
    try: finite_number(float.fromhex(arm["loss_hex"]),"confirm_loss_hex_invalid")
    except ValueError as exc: raise P5SError("confirm_loss_hex_invalid") from exc
    require(all(is_sha256(arm[name]) for name in ("logits","gradients","model_state")),"confirm_model_digest_invalid")
    return arm


def validate_confirm_paths(confirm_paths:list[Path], expected_freeze_sha:str, launcher_path:Path, launcher_sha:str)->tuple[list[dict[str,Any]],list[float]]:
    require(len(confirm_paths)==2 and len({x.resolve() for x in confirm_paths})==2,"need_two_distinct_confirm_paths")
    validate_freeze(expected_freeze_sha); validate_launcher(expected_freeze_sha,launcher_path,launcher_sha); manifest,_=load_manifest(); runs=[json.loads(x.read_text(encoding="utf-8")) for x in confirm_paths]
    top={"schema_version","phase","status","scientific_evidence","pid","uuid","utc","fold","protocol_sha256","runner_sha256","profile_sha256","profile_output_sha256","manifest_sha256","manifest_schema_sha256","dependency_closure","execution_freeze_sha256","review_authorized_freeze_sha","launcher_sha256","cache_warming","pairs","runtime","timer_boundary","semantic_pass"}
    ratios=[]; identities=[]
    for run in runs:
        exact_keys(run,top,"confirm_top_keys")
        require(run["schema_version"]=="autocontract.p5s-confirm.v1" and run["phase"]=="confirm" and run["status"]=="pass" and run["scientific_evidence"] is False and run["semantic_pass"] is True and run["fold"] in ("A","B"),"confirm_schema_or_status_failure")
        require(type(run["pid"]) is int and run["pid"]>0,"confirm_pid_invalid")
        try: parsed_uuid=uuid.UUID(run["uuid"])
        except (TypeError,ValueError,AttributeError) as exc: raise P5SError("confirm_uuid_invalid") from exc
        require(parsed_uuid.version==4 and str(parsed_uuid)==run["uuid"],"confirm_uuid_not_canonical_v4")
        try: utc=datetime.fromisoformat(run["utc"])
        except (TypeError,ValueError) as exc: raise P5SError("confirm_utc_invalid") from exc
        require(utc.tzinfo is not None and utc.utcoffset() == UTC.utcoffset(utc),"confirm_utc_not_zero_offset")
        identities.append((run["pid"],run["uuid"],run["utc"]))
        require(run["protocol_sha256"]==sha(PROTOCOL) and run["runner_sha256"]==sha(Path(__file__)) and run["profile_sha256"]==sha(PROFILE) and run["profile_output_sha256"]==sha(ROOT/"outputs"/"autocontract_p5s_div2k_profile.json") and run["manifest_sha256"]==sha(MANIFEST) and run["manifest_schema_sha256"]==sha(MANIFEST_SCHEMA) and run["dependency_closure"]==dependency_closure() and run["execution_freeze_sha256"]==expected_freeze_sha and run["review_authorized_freeze_sha"]==expected_freeze_sha and run["launcher_sha256"]==launcher_sha,"confirm_hash_binding_failure")
        require(run["runtime"]==EXPECTED_RUNTIME and run["timer_boundary"]==TIMER_BOUNDARY,"confirm_runtime_or_timer_failure"); validate_warming(run["cache_warming"],manifest,run["fold"])
        require(isinstance(run["pairs"],list) and len(run["pairs"])==15,"confirm_pair_count_failure")
        for index,pair in enumerate(run["pairs"],1):
            exact_keys(pair,{"block","order","authorized_over_baseline","semantic_pass","arms"},"confirm_pair_keys")
            order=("baseline","authorized") if index%2 else ("authorized","baseline")
            require(type(pair["block"]) is int and pair["block"]==index and isinstance(pair["order"],list) and all(type(item) is str for item in pair["order"]) and pair["order"]==list(order) and pair["semantic_pass"] is True,"confirm_block_or_order_failure")
            arms=exact_keys(pair["arms"],{"baseline","authorized"},"confirm_arms_keys"); base=validate_arm(arms["baseline"],False); auth=validate_arm(arms["authorized"],True)
            require(base["tensors"]==auth["tensors"] and base["shapes"]==auth["shapes"] and base["rng"]==auth["rng"] and all(base[name]==auth[name] for name in ("loss_hex","logits","gradients","model_state")),"confirm_semantic_gate")
            recomputed=auth["wall_ms"]/base["wall_ms"]; stored=finite_number(pair["authorized_over_baseline"],"confirm_ratio_tamper",positive=True)
            require(abs(stored-recomputed)<=1e-12*max(1.0,abs(recomputed)),"confirm_ratio_tamper"); ratios.append(recomputed)
    require({run["fold"] for run in runs}=={"A","B"} and len({item[0] for item in identities})==2 and len({item[1] for item in identities})==2 and len({item[2] for item in identities})==2,"confirm_identity_or_fold_failure")
    require(len(ratios)==30,"aggregate_ratio_count_failure")
    return runs,ratios


def aggregate(confirm_paths:list[Path],output:Path, expected_freeze_sha:str, launcher_path:Path, launcher_sha:str)->dict[str,Any]:
    runs,ratios=validate_confirm_paths(confirm_paths,expected_freeze_sha,launcher_path,launcher_sha); logs=[math.log(x) for x in ratios]; gen=random.Random(BOOTSTRAP_SEED); means=sorted(statistics.fmean(logs[gen.randrange(30)] for _ in range(30)) for _ in range(10000)); lower,upper=means[249],means[9749]
    medians={run["fold"]:statistics.median([float(p["arms"]["authorized"]["wall_ms"])/float(p["arms"]["baseline"]["wall_ms"]) for p in run["pairs"]]) for run in runs}; go=all(x<.95 for x in medians.values()) and math.exp(upper)<.95
    result={"schema_version":"autocontract.p5s-aggregate.v1","scientific_evidence":False,"protocol_sha256":sha(PROTOCOL),"runner_sha256":sha(Path(__file__)),"profile_sha256":sha(PROFILE),"profile_output_sha256":sha(ROOT/"outputs"/"autocontract_p5s_div2k_profile.json"),"manifest_sha256":sha(MANIFEST),"manifest_schema_sha256":sha(MANIFEST_SCHEMA),"dependency_closure":dependency_closure(),"execution_freeze_sha256":expected_freeze_sha,"review_authorized_freeze_sha":expected_freeze_sha,"launcher_sha256":launcher_sha,"confirm_sha256":[sha(x) for x in confirm_paths],"fold_medians":medians,"bootstrap":{"seed":BOOTSTRAP_SEED,"draws":10000,"log_ci":[lower,upper],"ratio_ci":[math.exp(lower),math.exp(upper)]},"go":go,"audit":{"distinct_pid":True,"distinct_uuid":True,"pairs":30}}
    write_json(output,result); return result


def aggregate_selftest(output:Path, expected_freeze_sha:str, launcher_path:Path, launcher_sha:str)->dict[str,Any]:
    """Synthetic adversarial parser test; it never opens DIV2K fold A/B files."""
    def arm(authorized:bool)->dict[str,Any]:
        return {"wall_ms":9.0 if authorized else 10.0,"candidate_count":2 if authorized else 1,"tags":["IterSourcePipe_5","autocontract:decode","autocontract:to_float","autocontract:guard", "autocontract:random_crop" if authorized else "autocontract:normalize", "autocontract:normalize" if authorized else "autocontract:random_crop"],"fix":[True,True,True,False,False] if authorized else [True]*5,"random_crop_random":True,"tensors":[{"sha256":"a"*64,"shape":[3,224,224],"dtype":"torch.float32","bytes":602112} for _ in range(32)],"shapes":[[3,224,224] for _ in range(32)],"open_count":32,"decode_count":32,"rng":{"python":"b"*64,"numpy":"c"*64,"torch":"d"*64},"loss_hex":"0x1p+0","logits":"e"*64,"gradients":"f"*64,"model_state":"0"*64}
    def run(fold:str,pid:int,ident:str)->dict[str,Any]:
        pairs=[]
        for i in range(1,16):
            base,auth=arm(False),arm(True); pairs.append({"block":i,"order":["baseline","authorized"] if i%2 else ["authorized","baseline"],"authorized_over_baseline":.9,"semantic_pass":True,"arms":{"baseline":base,"authorized":auth}})
        manifest,_=load_manifest()
        return {"schema_version":"autocontract.p5s-confirm.v1","phase":"confirm","status":"pass","scientific_evidence":False,"pid":pid,"uuid":ident,"utc":f"2026-08-07T00:00:0{0 if fold=='A' else 1}+00:00","fold":fold,"protocol_sha256":sha(PROTOCOL),"runner_sha256":sha(Path(__file__)),"profile_sha256":sha(PROFILE),"profile_output_sha256":sha(ROOT/"outputs"/"autocontract_p5s_div2k_profile.json"),"manifest_sha256":sha(MANIFEST),"manifest_schema_sha256":sha(MANIFEST_SCHEMA),"dependency_closure":dependency_closure(),"execution_freeze_sha256":expected_freeze_sha,"review_authorized_freeze_sha":expected_freeze_sha,"launcher_sha256":launcher_sha,"cache_warming":expected_warming(manifest,fold),"pairs":pairs,"runtime":EXPECTED_RUNTIME,"timer_boundary":TIMER_BOUNDARY,"semantic_pass":True}
    temp=Path(tempfile.mkdtemp(prefix="p5s_aggregate_selftest_")); checks=[]
    try:
        good=[run("A",101,"00000000-0000-4000-8000-000000000001"),run("B",202,"00000000-0000-4000-8000-000000000002")]
        def accepts(values:list[dict[str,Any]], anchor:str=expected_freeze_sha, launch_sha:str=launcher_sha)->bool:
            paths=[]
            for i,value in enumerate(values): p=temp/f"{i}.json"; write_json(p,value); paths.append(p)
            try: validate_confirm_paths(paths,anchor,launcher_path,launch_sha); return True
            except P5SError: return False
        checks.append({"name":"valid_synthetic_confirms_accept","passed":accepts(copy.deepcopy(good))})
        checks.append({"name":"wrong_expected_freeze_argument","passed":not accepts(copy.deepcopy(good),"0"*64)})
        checks.append({"name":"wrong_launcher_sha_argument","passed":not accepts(copy.deepcopy(good),expected_freeze_sha,"0"*64)})
        cases={
            "bad_utc":lambda x:x[0].update({"utc":"not-utc"}), "non_utc":lambda x:x[0].update({"utc":"2026-08-07T00:00:00+08:00"}), "string_pid":lambda x:x[0].update({"pid":"101"}), "same_pid":lambda x:x[1].update({"pid":101}), "bad_uuid":lambda x:x[0].update({"uuid":"bad"}), "same_uuid":lambda x:x[1].update({"uuid":x[0]["uuid"]}),
            "missing_arms":lambda x:x[0]["pairs"][0].pop("arms"), "missing_rng_both":lambda x:[p["arms"][a].pop("rng") for p in x[0]["pairs"] for a in ("baseline","authorized")], "missing_model_both":lambda x:[p["arms"][a].pop("model_state") for p in x[0]["pairs"] for a in ("baseline","authorized")], "missing_shapes_both":lambda x:[p["arms"][a].pop("shapes") for p in x[0]["pairs"] for a in ("baseline","authorized")], "missing_digests_both":lambda x:[p["arms"][a].pop("logits") for p in x[0]["pairs"] for a in ("baseline","authorized")], "empty_tensor_record":lambda x:x[0]["pairs"][0]["arms"]["baseline"]["tensors"].__setitem__(0,{}),
            "tampered_ratio":lambda x:x[0]["pairs"][0].update({"authorized_over_baseline":.1}), "wrong_order":lambda x:x[0]["pairs"][0].update({"order":["authorized","baseline"]}), "wrong_digest":lambda x:x[0]["pairs"][0]["arms"]["authorized"]["tensors"][0].update({"sha256":"b"*64}), "wrong_runtime":lambda x:x[0].update({"runtime":{}}), "wrong_warming":lambda x:x[0]["cache_warming"].update({"files":[]}), "wrong_timer":lambda x:x[0].update({"timer_boundary":"wrong"}), "wrong_dependency_closure":lambda x:x[0]["dependency_closure"].update({"v2":"0"*64}),
            "bool_candidate":lambda x:x[0]["pairs"][0]["arms"]["baseline"].update({"candidate_count":True}), "float_candidate":lambda x:x[0]["pairs"][0]["arms"]["baseline"].update({"candidate_count":1.0}), "integer_fix":lambda x:x[0]["pairs"][0]["arms"]["baseline"].update({"fix":[1,1,1,1,1]}), "extra_source_tag":lambda x:x[0]["pairs"][0]["arms"]["baseline"]["tags"].append("extra"), "fake_source_tag":lambda x:x[0]["pairs"][0]["arms"]["baseline"]["tags"].__setitem__(0,"IterSourcePipe_999"), "bool_shape":lambda x:x[0]["pairs"][0]["arms"]["baseline"]["shapes"][0].__setitem__(0,True),
            "wrong_expected_freeze":lambda x:x[0].update({"review_authorized_freeze_sha":"0"*64}), "wrong_launcher_sha":lambda x:x[0].update({"launcher_sha256":"0"*64}), "nan_wall":lambda x:x[0]["pairs"][0]["arms"]["baseline"].update({"wall_ms":float("nan")}), "inf_wall":lambda x:x[0]["pairs"][0]["arms"]["baseline"].update({"wall_ms":float("inf")}), "nonnum_wall":lambda x:x[0]["pairs"][0]["arms"]["baseline"].update({"wall_ms":"ten"}), "nan_loss":lambda x:x[0]["pairs"][0]["arms"]["baseline"].update({"loss_hex":"nan"}),
        }
        for name,mutate in cases.items(): value=copy.deepcopy(good); mutate(value); checks.append({"name":name,"passed":not accepts(value)})
        def decision(ratios:list[float])->bool:
            logs=[math.log(value) for value in ratios]; gen=random.Random(BOOTSTRAP_SEED); means=sorted(statistics.fmean(logs[gen.randrange(30)] for _ in range(30)) for _ in range(10000)); return statistics.median(ratios[:15])<.95 and statistics.median(ratios[15:])<.95 and math.exp(means[9749])<.95
        checks.append({"name":"synthetic_go_bootstrap_and_medians","passed":decision([.9]*30)})
        checks.append({"name":"synthetic_no_go_bootstrap_and_medians","passed":not decision([1.1]*30)})
        suite_sha=hashlib.sha256(json.dumps([item["name"] for item in checks],sort_keys=True,separators=(",",":")).encode()).hexdigest()
        result={"schema_version":"autocontract.p5s-aggregate-selftest.v3","status":"pass" if all(x["passed"] for x in checks) else "fail","scientific_evidence":False,"protocol_sha256":sha(PROTOCOL),"runner_sha256":sha(Path(__file__)),"manifest_sha256":sha(MANIFEST),"profile_sha256":sha(PROFILE),"execution_freeze_sha256":expected_freeze_sha,"review_authorized_freeze_sha":expected_freeze_sha,"launcher_sha256":launcher_sha,"dependency_closure":dependency_closure(),"suite_sha256":suite_sha,"passed":sum(x["passed"] for x in checks),"total":len(checks),"checks":checks}
    finally:
        import shutil; shutil.rmtree(temp)
    write_json(output,result); return result


def main(argv:list[str]|None=None)->int:
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument("--cedar-root",required=True,type=Path); parser.add_argument("--mode",required=True,choices=("profile","smoke","freeze","confirm","confirm-control-selftest","aggregate","aggregate-selftest")); parser.add_argument("--output",required=True,type=Path); parser.add_argument("--profile-output",type=Path); parser.add_argument("--smoke-output",type=Path); parser.add_argument("--control-selftest-output",type=Path); parser.add_argument("--fold",choices=("A","B")); parser.add_argument("--confirm-output",action="append",type=Path); parser.add_argument("--expected-freeze-sha"); parser.add_argument("--launcher-path",type=Path); parser.add_argument("--launcher-sha")
    args=parser.parse_args(argv)
    try:
        if args.mode=="profile": result=profile(args.cedar_root.resolve(),args.output)
        elif args.mode=="smoke": require(args.profile_output is not None,"smoke_requires_profile_output"); result=smoke(args.cedar_root.resolve(),args.profile_output,args.output)
        elif args.mode=="freeze":
            require(args.profile_output is not None and args.smoke_output is not None and args.control_selftest_output is not None and args.output.resolve()==FREEZE.resolve(),"freeze_requires_canonical_output_profile_smoke_control")
            result=freeze(args.profile_output,args.smoke_output,args.control_selftest_output); write_json(FREEZE,result)
        elif args.mode=="confirm-control-selftest": result=confirm_control_selftest(args.cedar_root.resolve(),args.output)
        elif args.mode=="confirm":
            require(args.profile_output is not None and args.fold is not None and args.expected_freeze_sha is not None and args.launcher_path is not None and args.launcher_sha is not None,"confirm_requires_fold_profile_review_anchor_launcher")
            result=confirm(args.cedar_root.resolve(),args.fold,args.profile_output,args.output,args.expected_freeze_sha,args.launcher_path,args.launcher_sha)
        elif args.mode=="aggregate":
            require(args.confirm_output is not None and args.expected_freeze_sha is not None and args.launcher_path is not None and args.launcher_sha is not None,"aggregate_requires_confirm_outputs_review_anchor_launcher")
            result=aggregate(args.confirm_output,args.output,args.expected_freeze_sha,args.launcher_path,args.launcher_sha)
        else:
            require(args.expected_freeze_sha is not None and args.launcher_path is not None and args.launcher_sha is not None,"selftest_requires_review_anchor_launcher")
            result=aggregate_selftest(args.output,args.expected_freeze_sha,args.launcher_path,args.launcher_sha)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0 if result.get("status","pass")=="pass" else 1
    except (P5SError,OSError,KeyError,TypeError,ValueError,subprocess.CalledProcessError) as exc:
        print(json.dumps({"status":"error","message":f"{type(exc).__name__}:{exc}"},ensure_ascii=False)); return 2
if __name__=="__main__": raise SystemExit(main())
