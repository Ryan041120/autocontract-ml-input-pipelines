"""Resolve public Python symbols to auditable defining-source bindings.

The resolver never imports or executes the target package.  It inspects only
module-level definitions and import statements, follows explicit re-exports,
and seals the defining file with a SHA-256 digest.  Class and function bodies
are deliberately ignored by the binding algorithm.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal


Status = Literal["resolved", "unresolved"]


@dataclass(frozen=True)
class ModuleMetadata:
    module: str
    path: Path
    is_package: bool
    definitions: dict[str, int]
    imports: dict[str, tuple[str, str]]
    ambiguous_imports: frozenset[str]
    star_imports: tuple[str, ...]


@dataclass(frozen=True)
class SymbolBinding:
    public_symbol: str
    status: Status
    public_module: str
    defining_module: str | None
    defining_name: str | None
    source_path: str | None
    source_line: int | None
    source_sha256: str | None
    binding_sha256: str | None
    export_chain: tuple[str, ...]
    reason: str | None


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class SymbolOriginSealer:
    """Conservatively resolve symbols inside one source-tree package."""

    def __init__(self, repository: Path, package: str) -> None:
        self.repository = repository.resolve()
        self.package = package
        self.package_parts = tuple(package.split("."))
        self._metadata: dict[str, ModuleMetadata] = {}

        package_dir = self.repository.joinpath(*self.package_parts)
        if not package_dir.is_dir():
            raise ValueError(f"package directory does not exist: {package_dir}")

    def module_path(self, module: str) -> tuple[Path, bool]:
        parts = tuple(module.split("."))
        if parts[: len(self.package_parts)] != self.package_parts:
            raise ValueError(f"external module is outside sealed package: {module}")

        base = self.repository.joinpath(*parts)
        package_file = base / "__init__.py"
        module_file = base.with_suffix(".py")
        candidates = [
            (package_file, True),
            (module_file, False),
        ]
        for candidate, is_package in candidates:
            if candidate.is_file():
                resolved = candidate.resolve()
                if not resolved.is_relative_to(self.repository):
                    raise ValueError(f"module path escapes repository: {module}")
                return resolved, is_package
        raise FileNotFoundError(f"module source not found: {module}")

    @staticmethod
    def _relative_target(
        current_module: str,
        is_package: bool,
        imported_module: str | None,
        level: int,
    ) -> str:
        if level == 0:
            return imported_module or ""
        package = current_module if is_package else current_module.rpartition(".")[0]
        parts = package.split(".") if package else []
        if level > len(parts):
            raise ValueError("relative import escapes package root")
        base = parts[: len(parts) - (level - 1)]
        if imported_module:
            base.extend(imported_module.split("."))
        return ".".join(base)

    def metadata(self, module: str) -> ModuleMetadata:
        if module in self._metadata:
            return self._metadata[module]

        path, is_package = self.module_path(module)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        definitions: dict[str, int] = {}
        import_candidates: dict[str, list[tuple[str, str]]] = {}
        star_imports: list[str] = []

        for node in tree.body:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                definitions[node.name] = node.lineno
            elif isinstance(node, ast.ImportFrom):
                target = self._relative_target(module, is_package, node.module, node.level)
                for alias in node.names:
                    if alias.name == "*":
                        star_imports.append(target)
                        continue
                    public_name = alias.asname or alias.name
                    import_candidates.setdefault(public_name, []).append((target, alias.name))

        imports = {
            name: candidates[0]
            for name, candidates in import_candidates.items()
            if len(set(candidates)) == 1
        }
        ambiguous = frozenset(
            name for name, candidates in import_candidates.items() if len(set(candidates)) > 1
        )
        result = ModuleMetadata(
            module=module,
            path=path,
            is_package=is_package,
            definitions=definitions,
            imports=imports,
            ambiguous_imports=ambiguous,
            star_imports=tuple(star_imports),
        )
        self._metadata[module] = result
        return result

    def unresolved(
        self,
        public_symbol: str,
        public_module: str,
        chain: tuple[str, ...],
        reason: str,
    ) -> SymbolBinding:
        return SymbolBinding(
            public_symbol=public_symbol,
            status="unresolved",
            public_module=public_module,
            defining_module=None,
            defining_name=None,
            source_path=None,
            source_line=None,
            source_sha256=None,
            binding_sha256=None,
            export_chain=chain,
            reason=reason,
        )

    def resolve(self, public_symbol: str) -> SymbolBinding:
        public_module, separator, name = public_symbol.rpartition(".")
        if not separator or not name:
            return self.unresolved(public_symbol, public_module, (), "invalid_public_symbol")
        if not (
            public_module == self.package
            or public_module.startswith(self.package + ".")
        ):
            return self.unresolved(public_symbol, public_module, (), "outside_sealed_package")

        module = public_module
        current_name = name
        chain: list[str] = []
        visited: set[tuple[str, str]] = set()

        while True:
            state = (module, current_name)
            if state in visited:
                return self.unresolved(
                    public_symbol, public_module, tuple(chain), "reexport_cycle"
                )
            visited.add(state)
            chain.append(f"{module}.{current_name}")

            try:
                metadata = self.metadata(module)
            except (FileNotFoundError, SyntaxError, UnicodeDecodeError, ValueError) as error:
                return self.unresolved(
                    public_symbol,
                    public_module,
                    tuple(chain),
                    f"module_metadata_error:{type(error).__name__}",
                )

            if current_name in metadata.definitions:
                source_bytes = metadata.path.read_bytes()
                source_hash = sha256_bytes(source_bytes)
                relative_path = metadata.path.relative_to(self.repository).as_posix()
                binding_payload = {
                    "public_symbol": public_symbol,
                    "defining_module": module,
                    "defining_name": current_name,
                    "source_path": relative_path,
                    "source_line": metadata.definitions[current_name],
                    "source_sha256": source_hash,
                }
                binding_hash = sha256_bytes(
                    json.dumps(binding_payload, sort_keys=True, separators=(",", ":")).encode()
                )
                return SymbolBinding(
                    public_symbol=public_symbol,
                    status="resolved",
                    public_module=public_module,
                    defining_module=module,
                    defining_name=current_name,
                    source_path=relative_path,
                    source_line=metadata.definitions[current_name],
                    source_sha256=source_hash,
                    binding_sha256=binding_hash,
                    export_chain=tuple(chain),
                    reason=None,
                )

            if current_name in metadata.ambiguous_imports:
                return self.unresolved(
                    public_symbol, public_module, tuple(chain), "ambiguous_explicit_reexport"
                )

            imported = metadata.imports.get(current_name)
            if imported is not None:
                target_module, original_name = imported
                if not (
                    target_module == self.package
                    or target_module.startswith(self.package + ".")
                ):
                    return self.unresolved(
                        public_symbol, public_module, tuple(chain), "external_reexport"
                    )
                module, current_name = target_module, original_name
                continue

            if metadata.star_imports:
                return self.unresolved(
                    public_symbol, public_module, tuple(chain), "unresolved_star_reexport"
                )
            return self.unresolved(
                public_symbol, public_module, tuple(chain), "symbol_not_exported_or_defined"
            )


def binding_record(binding: SymbolBinding) -> dict[str, object]:
    record = asdict(binding)
    record["export_chain"] = list(binding.export_chain)
    return record


def git_revision(repository: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repository), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    return completed.stdout.strip().lower()


def seal_manifest(
    repository: Path,
    package: str,
    symbols: list[str],
    expected_revision: str | None = None,
) -> dict[str, object]:
    sealer = SymbolOriginSealer(repository, package)
    bindings = [sealer.resolve(symbol) for symbol in symbols]
    revision = git_revision(repository)
    normalized_expected = expected_revision.lower() if expected_revision else None
    if normalized_expected is not None and revision != normalized_expected:
        raise ValueError(
            f"repository revision mismatch: expected {normalized_expected}, found {revision}"
        )
    payload: dict[str, object] = {
        "schema_version": 1,
        "repository_root": str(repository.resolve()),
        "revision": revision,
        "expected_revision": normalized_expected,
        "revision_verified": normalized_expected is not None and revision == normalized_expected,
        "package": package,
        "algorithm": "explicit-reexport-top-level-ast-v1",
        "policy": {
            "executes_target_package": False,
            "class_or_function_bodies_used": False,
            "star_reexports": "unresolved",
            "ambiguous_reexports": "unresolved",
            "external_reexports": "unresolved",
        },
        "bindings": [binding_record(binding) for binding in bindings],
    }
    # The operational checkout path is informative but machine-specific.  The
    # portable seal covers revision, relative paths, source hashes, and policy.
    portable_payload = {
        key: value for key, value in payload.items() if key != "repository_root"
    }
    canonical = json.dumps(
        portable_payload, sort_keys=True, separators=(",", ":")
    ).encode()
    payload["manifest_sha256"] = sha256_bytes(canonical)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--package", required=True)
    parser.add_argument("--expected-revision")
    parser.add_argument("--output", type=Path)
    parser.add_argument("symbols", nargs="+")
    args = parser.parse_args()

    manifest = seal_manifest(
        args.repository, args.package, args.symbols, args.expected_revision
    )
    rendered = json.dumps(manifest, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if any(item["status"] != "resolved" for item in manifest["bindings"]):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
