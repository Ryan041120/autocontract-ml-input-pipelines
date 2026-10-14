"""Candidate portable source index with recursive canonical code constants.

This module intentionally leaves the frozen V0 hot sentinel unchanged.  It
only replaces V0's process-dependent ``repr(code.co_consts)`` field.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import math
import types
from pathlib import Path
from typing import Any, Callable, Iterable

import autocontract_r3_source_index as v0


DEFAULT_CALLABLE_NAMES = v0.DEFAULT_CALLABLE_NAMES
canonical_ast = v0.canonical_ast
canonical_source_digest = v0.canonical_source_digest
hot_sentinel = v0.hot_sentinel
compare_hot_sentinel = v0.compare_hot_sentinel
HotSentinel = v0.HotSentinel


def _canonical_float(value: float) -> dict[str, str]:
    if math.isnan(value):
        return {"kind": "float", "value": "nan"}
    if math.isinf(value):
        return {"kind": "float", "value": "+inf" if value > 0 else "-inf"}
    return {"kind": "float", "value": value.hex()}


def canonical_constant(value: object, depth: int = 0) -> tuple[object, bool]:
    if depth > 20:
        return {"kind": "constant_depth_limit"}, False
    if value is None:
        return {"kind": "none"}, True
    if value is Ellipsis:
        return {"kind": "ellipsis"}, True
    if value is NotImplemented:
        return {"kind": "not_implemented"}, True
    if isinstance(value, bool):
        return {"kind": "bool", "value": value}, True
    if isinstance(value, int):
        return {"kind": "int", "value": str(value)}, True
    if isinstance(value, float):
        return _canonical_float(value), True
    if isinstance(value, complex):
        return {
            "kind": "complex",
            "real": _canonical_float(value.real)["value"],
            "imag": _canonical_float(value.imag)["value"],
        }, True
    if isinstance(value, str):
        return {"kind": "str", "value": value}, True
    if isinstance(value, bytes):
        return {
            "kind": "bytes",
            "length": len(value),
            "sha256": hashlib.sha256(value).hexdigest(),
        }, True
    if isinstance(value, tuple):
        items: list[object] = []
        supported = True
        for item in value:
            record, ok = canonical_constant(item, depth + 1)
            items.append(record)
            supported &= ok
        return {"kind": "tuple", "items": items}, supported
    if isinstance(value, frozenset):
        items = []
        supported = True
        for item in value:
            record, ok = canonical_constant(item, depth + 1)
            items.append(record)
            supported &= ok
        items.sort(key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=True))
        return {"kind": "frozenset", "items": items}, supported
    if isinstance(value, types.CodeType):
        return canonical_code_object(value, depth + 1)
    return {
        "kind": "unsupported_constant",
        "type": f"{type(value).__module__}.{type(value).__qualname__}",
    }, False


def canonical_code_object(code: types.CodeType, depth: int = 0) -> tuple[dict[str, object], bool]:
    constants = list(code.co_consts)
    if constants and isinstance(constants[0], str) and not code.co_name.startswith("<"):
        constants[0] = {"__autocontract_ignored_docstring__": True}
    constant_records: list[object] = []
    supported = True
    for item in constants:
        if isinstance(item, dict) and item == {"__autocontract_ignored_docstring__": True}:
            record, ok = {"kind": "ignored_docstring"}, True
        else:
            record, ok = canonical_constant(item, depth + 1)
        constant_records.append(record)
        supported &= ok
    record: dict[str, object] = {
        "kind": "code",
        "name": code.co_name,
        "qualname": getattr(code, "co_qualname", code.co_name),
        "argcount": code.co_argcount,
        "posonlyargcount": getattr(code, "co_posonlyargcount", 0),
        "kwonlyargcount": code.co_kwonlyargcount,
        "nlocals": code.co_nlocals,
        "stacksize": code.co_stacksize,
        "flags": code.co_flags,
        "bytecode_sha256": hashlib.sha256(code.co_code).hexdigest(),
        "names": list(code.co_names),
        "varnames": list(code.co_varnames),
        "freevars": list(code.co_freevars),
        "cellvars": list(code.co_cellvars),
        "constants": constant_records,
    }
    return record, supported


def _portable_layer(target: Any, repository_root: Path | None) -> tuple[dict[str, Any], bool]:
    identity = {
        "module": getattr(target, "__module__", ""),
        "qualname": getattr(target, "__qualname__", repr(target)),
        "origin": v0._origin(target, repository_root),
    }
    if inspect.isbuiltin(target) or not hasattr(target, "__code__"):
        return {**identity, "kind": "unsupported_native"}, False
    code = target.__code__
    try:
        semantic = canonical_ast(inspect.getsource(target))
        source_kind = "ast"
    except (OSError, TypeError, IndentationError, SyntaxError):
        semantic = ""
        source_kind = "code_only"
    defaults, defaults_ok = v0._portable_value(getattr(target, "__defaults__", None), repository_root)
    kwdefaults, kwdefaults_ok = v0._portable_value(getattr(target, "__kwdefaults__", None), repository_root)
    constants, constants_ok = canonical_code_object(code)
    closure_records: list[object] = []
    closure_ok = True
    for cell in getattr(target, "__closure__", None) or ():
        try:
            cell_value = cell.cell_contents
        except ValueError:
            closure_records.append({"kind": "empty_cell"})
            closure_ok = False
            continue
        record, ok = v0._portable_value(cell_value, repository_root)
        closure_records.append(record)
        closure_ok &= ok
    global_records: dict[str, object] = {}
    globals_ok = True
    namespace = getattr(target, "__globals__", {})
    for name in sorted(set(code.co_names)):
        if name not in namespace or name == "__builtins__":
            continue
        record, ok = v0._portable_value(namespace[name], repository_root)
        global_records[name] = record
        globals_ok &= ok
    record = {
        **identity,
        "kind": source_kind,
        "semantic_ast": semantic,
        "bytecode_sha256": hashlib.sha256(code.co_code).hexdigest(),
        "constants": constants,
        "names": list(code.co_names),
        "defaults": defaults,
        "kwdefaults": kwdefaults,
        "closure": closure_records,
        "globals": global_records,
    }
    return record, defaults_ok and kwdefaults_ok and closure_ok and globals_ok and constants_ok


def portable_callable_record(value: Callable[..., Any], repository_root: Path | None = None) -> dict[str, Any]:
    layers, chain_ok = v0._function_layers(value)
    records: list[dict[str, Any]] = []
    supported = chain_ok
    for layer in layers:
        record, ok = _portable_layer(layer, repository_root)
        records.append(record)
        supported &= ok
    return {"status": "supported" if supported else "unknown", "layers": records}


def portable_operator_index(
    operator: Any,
    *,
    repository_root: Path | None = None,
    callable_names: Iterable[str] = DEFAULT_CALLABLE_NAMES,
) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    supported = True
    for path, slot, candidate in v0._operator_slots(operator, callable_names):
        record = portable_callable_record(candidate, repository_root)
        entries.append({"path": path, "slot": slot, "callable": record})
        supported &= record["status"] == "supported"
    payload = {"schema": "autocontract.executable-source-index.v1", "entries": entries}
    return {
        **payload,
        "status": "supported" if supported else "unknown",
        "sha256": v0._json_digest(payload),
    }
