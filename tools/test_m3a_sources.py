"""M3a package integrity/fixture/gating tests only; never test older board projects."""
import contextlib
import io
import json
from pathlib import Path
import re
import struct
import unittest
from unittest.mock import patch
import prepare_m3a_sources as pkg

BUNDLE = None

class M3aPackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = json.loads((BUNDLE / "manifest.json").read_text())
        cls.src = BUNDLE / pkg.APP / "src"

    def test_integrity_and_exact_file_set(self):
        self.assertEqual({p.relative_to(BUNDLE).as_posix() for p in BUNDLE.rglob("*") if p.is_file()},
                         {f["path"] for f in self.m["files"]} | {"manifest.json"})
        for f in self.m["files"]:
            self.assertEqual(pkg.sha(BUNDLE / f["path"]), f["sha256"])
            self.assertEqual((BUNDLE / f["path"]).stat().st_size, f["bytes"])
        for f in self.m["inputs"]:
            self.assertEqual(pkg.sha(pkg.ROOT / f["path"]), f["sha256"], f["path"])

    def test_only_serial_xsa_and_source_app(self):
        xsas = list(BUNDLE.rglob("*.xsa"))
        self.assertEqual(len(xsas), 1)
        self.assertEqual(pkg.sha(xsas[0]), pkg.XSA_SHA)
        forbidden = {".project", ".cproject", ".metadata", "libxil.a", "xparameters.h", "lscript.ld",
                     "tt_hw_engine.cpp", "tt_hw_xil.cpp", "tt_engine.cpp", "main_benchmark.cpp"}
        self.assertFalse(any(p.name in forbidden or p.suffix == ".elf" for p in BUNDLE.rglob("*")))
        self.assertEqual(sum(len(re.findall(r"\bint\s+main\s*\(", p.read_text(encoding="utf-8")))
            for p in self.src.iterdir() if p.suffix in (".cpp", ".c")), 1)

    def test_generated_arrays_roundtrip(self):
        text = (self.src / "m3a_vectors.c").read_text()
        arrays, _ = pkg.vectors()
        for typ, name, expected in arrays:
            m = re.search(rf"const {typ} {name}\[(\d+)\].*?= \{{(.*?)\}};", text, re.S)
            self.assertIsNotNone(m, name)
            values = [int(x.rstrip("u")) for x in m[2].replace("\n", "").split(",") if x.strip()]
            self.assertEqual(int(m[1]), len(expected))
            self.assertEqual(values, expected, name)
        weights = arrays[0][2]
        self.assertEqual(struct.pack("<" + str(len(weights)) + "I", *weights),
                         (pkg.ROOT/pkg.GOLDEN/"weights_engine.bin").read_bytes())

    def test_settings_no_legacy_defines(self):
        cfg = json.loads((BUNDLE/pkg.APP/"settings.json").read_text())
        self.assertEqual(cfg, pkg.SETTINGS)
        self.assertEqual(cfg["defines"], [])
        self.assertIn("-ffp-contract=off", cfg["compiler_flags"])
        self.assertIn("-std=c++14", cfg["cxx_flags"])

    def test_existing_directory_refused(self):
        before = pkg.sha(BUNDLE/"manifest.json")
        with self.assertRaises(FileExistsError), contextlib.redirect_stdout(io.StringIO()):
            pkg.stage(BUNDLE)
        self.assertEqual(pkg.sha(BUNDLE/"manifest.json"), before)

    def test_replacement_xsa_rejected(self):
        real_sha = pkg.sha
        with patch.object(pkg, "sha", side_effect=lambda p: "bad" if p == pkg.ROOT/pkg.XSA else real_sha(p)):
            with self.assertRaisesRegex(ValueError, "Serial XSA hash mismatch"):
                pkg.verify_frozen(pkg.ROOT, [])

    def test_changed_golden_rejected(self):
        rel = pkg.GOLDEN/"a/class_u32.bin"
        real_sha = pkg.sha
        with patch.object(pkg, "sha", side_effect=lambda p: "bad" if p == pkg.ROOT/rel else real_sha(p)):
            with self.assertRaisesRegex(ValueError, "snapshot mismatch"):
                pkg.verify_frozen(pkg.ROOT, [rel])

if __name__ == "__main__":
    import sys
    BUNDLE = Path(sys.argv.pop(1)).resolve()
    unittest.main(verbosity=2)
