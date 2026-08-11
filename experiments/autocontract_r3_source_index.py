"""Portable executable-source indexes and process-local hot-path sentinels.

The portable index is intended for registration/deployment boundaries.  The
sentinel intentionally contains process-local identities and is only valid in
the process where it was created.
"""

from __future__ import annotations

import ast
import functools
import hashlib
import inspect
import json
import os
import textwrap
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable


DEFAULT_CALLABLE_NAMES = (
    "forward",
    "forward_parameters",
    "generate_parameters",
    "compute_transformation",
    "apply_transform",
    "transform_inputs",
    "transform_masks",
)


def _json_digest(value: object) -> str:
    rendered = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


class _DocstringStripper(ast.NodeTransformer):
    def _strip(self, node: Any) -> Any:
        node = self.generic_visit(node)
        body = getattr(node, "body", None)
        if (
            isinstance(body, list)
            and body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            node.body = body[1:]
        return node

    def visit_Module(self, node: ast.Module) -> ast.Module:  # noqa: N802
        return self._strip(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:  # noqa: N802
        return self._strip(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AsyncFunctionDef:  # noqa: N802
        return self._strip(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.ClassDef:  # noqa: N802
        return self._strip(node)


def canonical_ast(source: str) -> str:
    tree = ast.parse(textwrap.dedent(source))
    tree = _DocstringStripper().visit(tree)
    ast.fix_missing_locations(tree)
    return ast.dump(tree, annotate_fields=True, include_attributes=False)


def canonical_source_digest(source: str) -> str:
    return hashlib.sha256(canonical_ast(source).encode("utf-8")).hexdigest()


def _origin(value: object, repository_root: Path | None) -> str:
    path: str | None = None
    if isinstance(value, types.ModuleType):
        path = getattr(value, "__file__", None)
    if path is None:
        try:
            path = inspect.getsourcefile(value) or inspect.getfile(value)
        except (OSError, TypeError):
            code = getattr(value, "__code__", None)
            path = getattr(code, "co_filename", None)
    if not path:
        return "unknown"
    candidate = Path(path).resolve()
    if repository_root is not None:
        try:
            return "repo:" + candidate.relative_to(repository_root.resolve()).as_posix()
        except ValueError:
            pass
    return "external:" + os.path.normcase(str(candidate))


def _portable_value(value: object, repository_root: Path | None, depth: int = 0) -> tuple[object, bool]:
    if depth > 5:
        return {"kind": "depth_limit", "type": type(value).__qualname__}, False
    if value is None or isinstance(value, (bool, int, float, str)):
        return value, True
    if isinstance(value, bytes):
        return {"kind": "bytes", "length": len(value), "sha256": hashlib.sha256(value).hexdigest()}, True
    if isinstance(value, (tuple, list)):
        items, supported = [], True
        for item in value:
            record, ok = _portable_value(item, repository_root, depth + 1)
            items.append(record)
            supported &= ok
        return {"kind": type(value).__name__, "items": items}, supported
    if isinstance(value, dict):
        items, supported = {}, True
        for key in sorted(value, key=lambda item: str(item)):
            record, ok = _portable_value(value[key], repository_root, depth + 1)
            items[str(key)] = record
            supported &= ok
        return {"kind": "dict", "items": items}, supported
    if isinstance(value, (set, frozenset)):
        records, supported = [], True
        for item in value:
            record, ok = _portable_value(item, repository_root, depth + 1)
            records.append(record)
            supported &= ok
        records.sort(key=lambda item: json.dumps(item, sort_keys=True, default=str))
        return {"kind": type(value).__name__, "items": records}, supported
    if isinstance(value, Path):
        return {"kind": "path", "value": str(value)}, True
    if value.__class__.__module__ == "typing":
        return {"kind": "typing", "repr": repr(value)}, True
    if isinstance(value, functools.partial):
        function, function_ok = _portable_value(value.func, repository_root, depth + 1)
        arguments, arguments_ok = _portable_value(value.args, repository_root, depth + 1)
        keywords, keywords_ok = _portable_value(value.keywords or {}, repository_root, depth + 1)
        return {
            "kind": "partial",
            "function": function,
            "arguments": arguments,
            "keywords": keywords,
        }, function_ok and arguments_ok and keywords_ok
    if isinstance(value, types.ModuleType):
        return {"kind": "module", "name": value.__name__, "origin": _origin(value, repository_root)}, True
    if inspect.isclass(value) or inspect.isfunction(value) or inspect.ismethod(value) or inspect.isbuiltin(value):
        target = getattr(value, "__func__", value)
        return {
            "kind": "callable_ref",
            "module": getattr(target, "__module__", ""),
            "qualname": getattr(target, "__qualname__", repr(target)),
            "origin": _origin(target, repository_root),
        }, not inspect.isbuiltin(target)
    return {
        "kind": "unsupported",
        "type": f"{value.__class__.__module__}.{value.__class__.__qualname__}",
    }, False


def _function_layers(value: Callable[..., Any]) -> tuple[list[Any], bool]:
    target = getattr(value, "__func__", value)
    layers: list[Any] = []
    seen: set[int] = set()
    for _ in range(9):
        if id(target) in seen:
            return layers, False
        seen.add(id(target))
        layers.append(target)
        wrapped = getattr(target, "__wrapped__", None)
        if wrapped is None:
            return layers, True
        target = getattr(wrapped, "__func__", wrapped)
    return layers, False


def _portable_layer(target: Any, repository_root: Path | None) -> tuple[dict[str, Any], bool]:
    identity = {
        "module": getattr(target, "__module__", ""),
        "qualname": getattr(target, "__qualname__", repr(target)),
        "origin": _origin(target, repository_root),
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
    defaults, defaults_ok = _portable_value(getattr(target, "__defaults__", None), repository_root)
    kwdefaults, kwdefaults_ok = _portable_value(getattr(target, "__kwdefaults__", None), repository_root)
    closure_records: list[object] = []
    closure_ok = True
    for cell in getattr(target, "__closure__", None) or ():
        try:
            cell_value = cell.cell_contents
        except ValueError:
            closure_records.append({"kind": "empty_cell"})
            closure_ok = False
            continue
        record, ok = _portable_value(cell_value, repository_root)
        closure_records.append(record)
        closure_ok &= ok
    global_records: dict[str, object] = {}
    globals_ok = True
    namespace = getattr(target, "__globals__", {})
    for name in sorted(set(code.co_names)):
        if name not in namespace or name == "__builtins__":
            continue
        record, ok = _portable_value(namespace[name], repository_root)
        global_records[name] = record
        globals_ok &= ok
    record = {
        **identity,
        "kind": source_kind,
        "semantic_ast": semantic,
        "bytecode_sha256": hashlib.sha256(code.co_code).hexdigest(),
        "constants": repr(code.co_consts),
        "names": list(code.co_names),
        "defaults": defaults,
        "kwdefaults": kwdefaults,
        "closure": closure_records,
        "globals": global_records,
    }
    return record, defaults_ok and kwdefaults_ok and closure_ok and globals_ok


def portable_callable_record(value: Callable[..., Any], repository_root: Path | None = None) -> dict[str, Any]:
    layers, chain_ok = _function_layers(value)
    records: list[dict[str, Any]] = []
    supported = chain_ok
    for layer in layers:
        record, ok = _portable_layer(layer, repository_root)
        records.append(record)
        supported &= ok
    return {"status": "supported" if supported else "unknown", "layers": records}


def _operator_slots(operator: Any, callable_names: Iterable[str]) -> list[tuple[str, str, Callable[..., Any]]]:
    slots: list[tuple[str, str, Callable[..., Any]]] = []
    modules = operator.named_modules() if hasattr(operator, "named_modules") else [("", operator)]
    for path, module in modules:
        for name in callable_names:
            candidate = getattr(module, name, None)
            if callable(candidate):
                slots.append((str(path), name, candidate))
    return slots


def portable_operator_index(
    operator: Any,
    *,
    repository_root: Path | None = None,
    callable_names: Iterable[str] = DEFAULT_CALLABLE_NAMES,
) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    supported = True
    for path, slot, candidate in _operator_slots(operator, callable_names):
        record = portable_callable_record(candidate, repository_root)
        entries.append({"path": path, "slot": slot, "callable": record})
        supported &= record["status"] == "supported"
    payload = {"schema": "autocontract.executable-source-index.v0", "entries": entries}
    return {
        **payload,
        "status": "supported" if supported else "unknown",
        "sha256": _json_digest(payload),
    }


def _fast_value(value: object, depth: int = 0) -> tuple[object, bool]:
    if depth > 4:
        return ("depth_limit", type(value).__qualname__), False
    if value is None or isinstance(value, (bool, int, float, str)):
        return value, True
    if isinstance(value, bytes):
        return ("bytes", len(value), hashlib.sha256(value).hexdigest()), True
    if isinstance(value, (tuple, list)):
        records, supported = [], True
        for item in value:
            record, ok = _fast_value(item, depth + 1)
            records.append(record)
            supported &= ok
        return (type(value).__name__, records), supported
    if isinstance(value, dict):
        records, supported = [], True
        for key in sorted(value, key=lambda item: str(item)):
            record, ok = _fast_value(value[key], depth + 1)
            records.append((str(key), record))
            supported &= ok
        return ("dict", records), supported
    if isinstance(value, (set, frozenset)):
        records, supported = [], True
        for item in value:
            record, ok = _fast_value(item, depth + 1)
            records.append(record)
            supported &= ok
        records.sort(key=repr)
        return (type(value).__name__, records), supported
    if isinstance(value, types.ModuleType):
        return ("module", value.__name__, getattr(value, "__file__", None)), True
    if value.__class__.__module__ == "typing":
        return ("typing", repr(value)), True
    if isinstance(value, functools.partial):
        function, function_ok = _fast_value(value.func, depth + 1)
        arguments, arguments_ok = _fast_value(value.args, depth + 1)
        keywords, keywords_ok = _fast_value(value.keywords or {}, depth + 1)
        return ("partial", function, arguments, keywords), function_ok and arguments_ok and keywords_ok
    if inspect.isfunction(value) or inspect.ismethod(value) or inspect.isclass(value):
        target = getattr(value, "__func__", value)
        code = getattr(target, "__code__", None)
        return ("callable", id(target), id(code), getattr(target, "__qualname__", "")), code is not None or inspect.isclass(target)
    if inspect.isbuiltin(value):
        return ("native", getattr(value, "__module__", ""), getattr(value, "__qualname__", repr(value))), False
    return ("unsupported", f"{value.__class__.__module__}.{value.__class__.__qualname__}"), False


def _hot_layer(target: Any) -> tuple[object, bool]:
    if inspect.isbuiltin(target) or not hasattr(target, "__code__"):
        return ("unsupported_native", getattr(target, "__module__", ""), getattr(target, "__qualname__", repr(target))), False
    code = target.__code__
    defaults, defaults_ok = _fast_value(getattr(target, "__defaults__", None))
    kwdefaults, kwdefaults_ok = _fast_value(getattr(target, "__kwdefaults__", None))
    closure, closure_ok = [], True
    for cell in getattr(target, "__closure__", None) or ():
        try:
            record, ok = _fast_value(cell.cell_contents)
        except ValueError:
            record, ok = ("empty_cell",), False
        closure.append(record)
        closure_ok &= ok
    globals_record, globals_ok = [], True
    namespace = getattr(target, "__globals__", {})
    for name in sorted(set(code.co_names)):
        if name not in namespace or name == "__builtins__":
            continue
        record, ok = _fast_value(namespace[name])
        globals_record.append((name, record))
        globals_ok &= ok
    record = (
        id(target),
        id(code),
        hashlib.sha256(code.co_code).hexdigest(),
        defaults,
        kwdefaults,
        tuple(closure),
        tuple(globals_record),
    )
    return record, defaults_ok and kwdefaults_ok and closure_ok and globals_ok


@dataclass(frozen=True)
class HotSentinel:
    status: str
    digest: str
    entry_count: int


def hot_sentinel(
    operator: Any,
    *,
    callable_names: Iterable[str] = DEFAULT_CALLABLE_NAMES,
) -> HotSentinel:
    entries: list[object] = []
    supported = True
    for path, slot, candidate in _operator_slots(operator, callable_names):
        layers, chain_ok = _function_layers(candidate)
        layer_records = []
        supported &= chain_ok
        for layer in layers:
            record, ok = _hot_layer(layer)
            layer_records.append(record)
            supported &= ok
        entries.append((path, slot, tuple(layer_records)))
    return HotSentinel("supported" if supported else "unknown", _json_digest(entries), len(entries))


def compare_hot_sentinel(expected: HotSentinel, operator: Any) -> tuple[str, tuple[str, ...]]:
    actual = hot_sentinel(operator)
    if actual.status != "supported":
        return "unknown", ("unsupported_runtime_callable_or_dependency",)
    if expected.status != "supported":
        return "unknown", ("deployment_sentinel_was_unknown",)
    if actual.digest != expected.digest or actual.entry_count != expected.entry_count:
        return "reject", ("hot_callable_sentinel_mismatch",)
    return "admit", ()
