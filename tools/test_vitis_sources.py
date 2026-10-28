"""Regression checks for the source-only package; no Vitis process or board."""
import contextlib
import io
import json
from pathlib import Path
import re
import unittest
from prepare_vitis_sources import ROOT, sha, stage

BUNDLE = None

class SourcePackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if BUNDLE is None:
            raise unittest.SkipTest("Provide a generated source package directory")
        cls.manifest = json.loads((BUNDLE / "manifest.json").read_text(encoding="utf-8"))

    def test_xsa_and_all_file_hashes(self):
        self.assertEqual(len(list(BUNDLE.rglob("*.xsa"))), 2)
        for f in self.manifest["files"]:
            p = BUNDLE / f["path"]
            self.assertEqual(sha(p), f["sha256"])
            self.assertEqual(p.stat().st_size, f["bytes"])

    def test_no_workspace_or_generated_bsp(self):
        forbidden = {".project", ".cproject", ".metadata", "libxil.a", "xparameters.h", "lscript.ld"}
        self.assertFalse(any(p.name in forbidden or p.suffix == ".elf" for p in BUNDLE.rglob("*")))

    def test_one_main_and_correct_backend_per_app(self):
        for app, cfg in self.manifest["apps"].items():
            src = BUNDLE / cfg["directory"] / "src"
            mains = sum(len(re.findall(r"\bint\s+main\s*\(", p.read_text(encoding="utf-8")))
                        for p in src.iterdir() if p.suffix in (".c", ".cpp"))
            self.assertEqual(mains, 1, app)
            self.assertEqual((src / "tt_hw_xil.cpp").exists(), app == "m1")
            self.assertEqual((src / "tt_hw_engine.cpp").exists(), app.startswith("m2"))
            self.assertEqual((src / "tt_engine_regs.h").exists(), app.startswith("m2"))
        self.assertIn("TT_ENG_SELFCHECK", self.manifest["apps"]["m2_selfcheck"]["defines"])
        self.assertNotIn("TT_ENG_SELFCHECK", self.manifest["apps"]["m2"]["defines"])

    def test_block_data_is_self_contained_and_only_path_changes(self):
        source = ROOT / "src/ps/tt_block_data.c"
        for app in ("m1", "m2", "m2_selfcheck"):
            src = BUNDLE / self.manifest["apps"][app]["directory"] / "src"
            text = (src / source.name).read_text(encoding="utf-8")
            expected = source.read_text(encoding="utf-8").replace(
                "D:/HSI_AgriEdge/model/data/block/region_f32.bin", "../src/region_f32.bin")
            self.assertEqual(text, expected)
            self.assertEqual(sha(src / "region_f32.bin"), sha(ROOT / "model/data/block/region_f32.bin"))

    def test_existing_directory_refused_without_changing_manifest(self):
        old = (BUNDLE / "manifest.json").read_bytes()
        with self.assertRaises(FileExistsError), contextlib.redirect_stdout(io.StringIO()):
            stage(BUNDLE)
        self.assertEqual(old, (BUNDLE / "manifest.json").read_bytes())

if __name__ == "__main__":
    import sys
    # Optional package path, keeping unittest's own flags available after it.
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        BUNDLE = Path(sys.argv.pop(1)).resolve()
    else:
        sys.exit("Usage: test_vitis_sources.py <source-package-directory> [unittest flags]")
    unittest.main(verbosity=2)
