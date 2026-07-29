from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from autocontract_symbol_origin import SymbolOriginSealer, seal_manifest


class SymbolOriginSealerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        package = self.repo / "demo"
        package.mkdir()
        (package / "__init__.py").write_text(
            "from .public import Direct, PublicAlias, MissingExternal\n",
            encoding="utf-8",
        )
        (package / "public.py").write_text(
            "from .definitions import Direct\n"
            "from .definitions import Internal as PublicAlias\n"
            "from outside import MissingExternal\n",
            encoding="utf-8",
        )
        (package / "definitions.py").write_text(
            "class Direct:\n    pass\n\nclass Internal:\n    pass\n",
            encoding="utf-8",
        )
        self.sealer = SymbolOriginSealer(self.repo, "demo")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_resolves_recursive_reexport(self) -> None:
        binding = self.sealer.resolve("demo.Direct")
        self.assertEqual(binding.status, "resolved")
        self.assertEqual(binding.defining_module, "demo.definitions")
        self.assertEqual(binding.source_path, "demo/definitions.py")
        self.assertEqual(
            binding.export_chain,
            ("demo.Direct", "demo.public.Direct", "demo.definitions.Direct"),
        )
        self.assertIsNotNone(binding.source_sha256)
        self.assertIsNotNone(binding.binding_sha256)

    def test_resolves_aliased_reexport(self) -> None:
        binding = self.sealer.resolve("demo.PublicAlias")
        self.assertEqual(binding.status, "resolved")
        self.assertEqual(binding.defining_name, "Internal")

    def test_rejects_external_reexport(self) -> None:
        binding = self.sealer.resolve("demo.MissingExternal")
        self.assertEqual(binding.status, "unresolved")
        self.assertEqual(binding.reason, "external_reexport")

    def test_rejects_missing_symbol(self) -> None:
        binding = self.sealer.resolve("demo.NotThere")
        self.assertEqual(binding.status, "unresolved")
        self.assertEqual(binding.reason, "symbol_not_exported_or_defined")

    def test_rejects_ambiguous_explicit_reexport(self) -> None:
        (self.repo / "demo" / "ambiguous.py").write_text(
            "from .definitions import Direct as Duplicate\n"
            "from .definitions import Internal as Duplicate\n",
            encoding="utf-8",
        )
        binding = self.sealer.resolve("demo.ambiguous.Duplicate")
        self.assertEqual(binding.status, "unresolved")
        self.assertEqual(binding.reason, "ambiguous_explicit_reexport")

    def test_rejects_star_reexport(self) -> None:
        (self.repo / "demo" / "star.py").write_text(
            "from .definitions import *\n", encoding="utf-8"
        )
        binding = self.sealer.resolve("demo.star.Direct")
        self.assertEqual(binding.status, "unresolved")
        self.assertEqual(binding.reason, "unresolved_star_reexport")

    def test_manifest_hash_does_not_depend_on_checkout_path(self) -> None:
        first = seal_manifest(self.repo, "demo", ["demo.Direct"])
        second_root = self.repo / "copy"
        second_package = second_root / "demo"
        second_package.mkdir(parents=True)
        for source in (self.repo / "demo").glob("*.py"):
            (second_package / source.name).write_bytes(source.read_bytes())
        second = seal_manifest(second_root, "demo", ["demo.Direct"])
        self.assertNotEqual(first["repository_root"], second["repository_root"])
        self.assertEqual(first["manifest_sha256"], second["manifest_sha256"])


if __name__ == "__main__":
    unittest.main()
