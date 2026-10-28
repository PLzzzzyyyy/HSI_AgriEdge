"""Readiness gate tests; simulated fixture text is not hardware evidence."""
import tempfile
from pathlib import Path
import unittest
from check_m3a_ready import check, read_log, synthesis_text, validate_log


def good_log():
    return "\n".join(["tt_engine M3a tb: TT_K3=7, layers=12", "error codes: PASS",
                     *(f"layer {i:2d}: x_out mismatches=0" for i in range(12)),
                     "batch n_patch=3 (A, B embed, A): LOGITS + CLASS mismatches=0 (ncls 9)",
                     "layers 5..11 from L4 x_out: FEAT + CLASS mismatches=0",
                     "PROJ layer 0 (QKV + MLP, int16 sat): mismatches=0",
                     "INFO: [COSIM 212-1000] *** C/RTL co-simulation finished: PASS ***"])


class ReadinessTest(unittest.TestCase):
    def test_provenance_changes_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            build = root / "build/hls/optimization_build/tt_engine_m3_k7"
            snap = build / "snapshot"
            names = ["src/hls/"+n for n in ("tt_engine.cpp", "tt_engine.h", "tt_engine_regs.h", "tt_types.h", "tt_attn.cpp", "tt_attn.h")]
            names += ["src/ps/tt_ref_int.h", "sim/hls_tb/tb_tt_engine_full.cpp", "sim/golden/n6_engine/test.bin"]
            for name in names:
                for base in (root, snap):
                    p = base / name
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text("fixture")
            (snap / "flags.txt").write_text("flags=-DTT_K3=7 -DTT_DB=18\nclock_ns=5\n")
            for name in ("sol/syn/verilog/tt_engine.v", "sol/impl/ip/hdl/verilog/tt_engine.v"):
                p = build / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("module top; endmodule")
            log = root / "cosim.log"
            log.write_text(good_log())
            self.assertEqual(check(root, log)["export_rtl_files_matched"], 1)
            changed = root / "src/hls/tt_engine.cpp"
            changed.write_text("changed")
            with self.assertRaises(ValueError):
                check(root, log)
            changed.write_text("fixture")
            exported = build / "sol/impl/ip/hdl/verilog/tt_engine.v"
            exported.write_text("module different; endmodule")
            with self.assertRaises(ValueError):
                check(root, log)
            exported.write_text("module top; endmodule")
            (root / "sim/golden/n6_engine/test.bin").unlink()
            with self.assertRaises(ValueError):
                check(root, log)

    def test_full_coverage(self):
        validate_log(good_log())

    def test_partial_layer_count(self):
        with self.assertRaises(ValueError):
            validate_log(good_log().replace("layers=12", "layers=1"))

    def test_missing_layer_or_batch_or_final(self):
        for line in good_log().splitlines():
            with self.subTest(line=line), self.assertRaises(ValueError):
                validate_log(good_log().replace(line, ""))

    def test_failures_not_hidden_by_pass(self):
        for error in ("ERROR: failed", "FATAL: bad", "FAIL: guard", "mismatches=3"):
            with self.subTest(error=error), self.assertRaises(ValueError):
                validate_log(good_log()+"\n"+error)

    def test_utf16_powershell_and_utf8_vendor_logs(self):
        with tempfile.TemporaryDirectory() as d:
            for enc in ("utf-16", "utf-8"):
                p = Path(d) / enc
                p.write_text(good_log(), encoding=enc)
                validate_log(read_log(p))

    def test_only_export_simulation_addition_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d)/"a.v", Path(d)/"b.v"
            a.write_text("module top;\nassign y=x;\nendmodule\n")
            b.write_text('module top;\nassign y=x;\n// synthesis translate_off\n`include "debug.vh"\n// synthesis translate_on\nendmodule\n')
            self.assertEqual(synthesis_text(a), synthesis_text(b))
            b.write_text(b.read_text().replace("y=x", "y=~x"))
            self.assertNotEqual(synthesis_text(a), synthesis_text(b))


if __name__ == "__main__":
    unittest.main()
