"""Small symbolic transition proof under explicit trusted primitive semantics.

No Torch import or execution. This verifies a model theorem, not native kernels
or arbitrary Python source. Binary32 sub and div remain distinct expressions.
"""
from fractions import Fraction
import copy
import math

from autocontract_baseline_catalog import digest


ASSUMPTIONS = (
    "trusted_startup_and_exact_builtin_source_to_model_correspondence",
    "binary32_RNE_sub_then_div_same_coordinate_semantics_preserve_denormals",
    "out_of_place_sub_and_copying_flip_fresh_canonical_storage_div_preserves_layout",
    "one_CPU_rand_draw_for_flip_no_other_declared_rng_or_object_input_writes",
    "serial_no_concurrent_mutation_hooks_modes_or_external_intermediate_observer",
    "sufficient_resources_no_external_interrupts_unmodeled_telemetry_excluded",
)
HISTORY = "arbitrary_finite_serial_calls_fresh_nonshared_legal_inputs_no_external_mutation"
HALF = "0x1.0000000000000p-1"
CANONICAL_LAYOUT = {"shape": [3, "H", "W"], "stride": [["mul", "H", "W"], "W", 1], "storage_offset": 0}
ENTRY_CONTRACT = {"ordinary_dense_tensor": True, "requires_grad": False, "contiguous": True,
                  "storage_offset": 0, "fresh_nonshared_inputs": True,
                  "fresh_builtin_objects_no_hooks_extra_state_or_overrides": True}


def _check_target(context):
    if (context.get("boundary") != "pair_exit_strict"
            or context.get("proof_semantics") != "trusted_binary32_normalize_half_and_copying_hflip"
            or context.get("trusted_assumptions") != list(ASSUMPTIONS)
            or context.get("entry_contract") != ENTRY_CONTRACT
            or context.get("source_to_model_mapping") != "trusted_exact_builtin_mapping_not_Python_or_native_formal_verification"
            or context.get("allowed_history") != HISTORY):
        raise ValueError("target_or_explicit_trust_policy_mismatch")
    domain = context["domain"]
    if (domain["type"] != "torch.Tensor" or domain["layout"] != "CHW" or domain["channels"] != 3
            or domain["dtype"] != "torch.float32" or domain["device"] != "cpu" or domain["allow_nonfinite"] is not False
            or not math.isfinite(domain["value_min"]) or not math.isfinite(domain["value_max"])
            or not 0 <= domain["value_min"] <= domain["value_max"] <= 1
            or any(type(domain[k]) is not int for k in ("height_min", "height_max", "width_min", "width_max"))
            or not 2 <= domain["height_min"] <= domain["height_max"]
            or not 2 <= domain["width_min"] <= domain["width_max"]):
        raise ValueError("unsupported_model_domain")
    n, f = context["operator_ir"]
    if (n["operator_type"] != "torchvision.transforms.v2._misc.Normalize"
            or n["config"] != {"mean_hex": [HALF]*3, "std_hex": [HALF]*3, "inplace": False}
            or f["operator_type"] != "torchvision.transforms.v2._geometry.RandomHorizontalFlip"
            or f["config"]["axis"] != "horizontal"):
        raise ValueError("unsupported_model_operators")
    p = float.fromhex(f["config"]["probability_hex"])
    if not math.isfinite(p) or not 0 <= p <= 1:
        raise ValueError("unsupported_flip_probability")
    return domain


def _read(image, coordinate):
    tag = image[0]
    if tag == "input":
        return ["input_binary32_bits_at", *coordinate]
    if tag == "normalize_half":
        return ["binary32_div_RNE", ["binary32_sub_RNE", _read(image[1], coordinate), HALF], HALF]
    if tag == "copy_hflip":
        c, h, w = coordinate
        return _read(image[1], (c, h, ["sub_int", ["sub_int", "W", 1], w]))
    raise ValueError("unsupported_symbolic_image")


def _transition(order, flip_branch, probability_hex):
    image, fresh, draws, allocations = ["input"], False, [], 0
    for name in order:
        if name == "normalize":
            image = ["normalize_half", image]
            fresh = True
            allocations += 1
        elif name == "hflip":
            draws.append(["torch_cpu_rand", 1])  # p=0 and p=1 still draw.
            if flip_branch:
                image = ["copy_hflip", image]
                fresh = True
                allocations += 1
        else:
            raise ValueError("unsupported_transition")
    observation = {"definedness": "normal_return_under_resource_assumption",
        "output_value_at_arbitrary_coordinate": _read(image, ("c", "h", "w")),
        "output_metadata": {"dtype": "float32", "device": "cpu", "layout": "strided", "requires_grad": False, **copy.deepcopy(CANONICAL_LAYOUT)},
        "input_post_state": "input_bits_metadata_and_root_aliases_unchanged",
        "object_post_state": "normalize_and_flip_transparent_state_unchanged",
        "tensor_alias_relations": {"output_fresh_disjoint_from_input_state_and_past_live_roots": fresh,
                                  "protected_root_aliases": "unchanged"},
        "rng_post_state": {"python": "P", "numpy": "N", "torch_cpu": ["advance_exact_draw_trace", "R", draws]},
        "branch_predicate": ["same_rand1_result_ge_probability", "R", probability_hex]}
    return {"order": list(order), "image_expression": image, "allocations_not_in_observer": allocations,
            "observation": observation}


def derive(context):
    """Universal coordinate derivation; two symbolic branches, no sampled x."""
    _check_target(context)
    p_hex = context["operator_ir"][1]["config"]["probability_hex"]
    branches = []
    for flip in (False, True):
        a = _transition(("normalize", "hflip"), flip, p_hex)
        b = _transition(("hflip", "normalize"), flip, p_hex)
        if a["observation"] != b["observation"]:
            raise ValueError("symbolic_transition_not_equivalent")
        branches.append({"flip_branch": flip, "baseline": a, "swapped": b,
                         "observations_equal": True})
    # Under the trusted coordinatewise RNE primitive contract, representable
    # interval endpoints enclose the rounded result. Signed zero is preserved
    # in the value term above, not simplified by this totality range argument.
    sub_range = [Fraction(0)-Fraction(1,2), Fraction(1)-Fraction(1,2)]
    div_range = [v/Fraction(1,2) for v in sub_range]
    if sub_range != [Fraction(-1,2), Fraction(1,2)] or div_range != [Fraction(-1), Fraction(1)]:
        raise ValueError("totality_range_derivation_failed")
    return {"proof_kind": "symbolic_transition_equality_under_declared_primitive_axioms",
        "context_sha256": digest(context), "arbitrary_coordinate": {"c": "0<=c<3", "h": "0<=h<H", "w": "0<=w<W"},
        "branches": branches,
        "totality": {"input_interval_enclosure": ["0", "1"], "sub_interval": [str(v) for v in sub_range],
                     "div_interval": [str(v) for v in div_range], "std_exact_nonzero": HALF,
                     "representable_endpoints_and_no_overflow_under_RNE_contract": True,
                     "normal_return_conditional_on_resource_and_dispatch_assumptions": True},
        "history_argument": {"base": "equal_declared_initial_rng_input_and_object_state",
            "step": "both_branches_equal_observation_and_equal_next_protected_state",
            "closed_state": "fresh_output_canonical_and_disjoint_protected_states_unchanged_rng_trace_equal",
            "result": HISTORY},
        "trusted_assumptions": list(ASSUMPTIONS), "native_formally_verified": False,
        "execution_authorized": False}


def verify(context, certificate):
    """Reconstruct the derivation in this small trusted checker."""
    try:
        expected = derive(context)
        if digest(certificate) != digest(expected):
            return {"verified": False, "reason": "certificate_does_not_replay", "execution_authorized": False}
        return {"verified": True, "reason": "conditional_symbolic_relation_verified",
                "proof_scope": "declared_trusted_primitive_model_only", "native_formally_verified": False,
                "execution_authorized": False}
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        return {"verified": False, "reason": str(exc), "execution_authorized": False}
