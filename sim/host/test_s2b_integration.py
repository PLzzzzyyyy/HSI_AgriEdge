"""New checker regression only: in-memory files, no C++/BSP/device/network."""
import contextlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import check_s2b_integration as c


class IntegrationCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = {p: c.read_repo(p) for p in c.SOURCES + c.EVIDENCE + (c.LOCK,)}

    def setUp(self):
        self.files = self.original.copy()
        self.names = ["main.cpp", "boot_id.cpp", "boot_id.h"]
        self.reads = []

    def read(self, path):
        self.reads.append(path)
        return self.files[path]

    def change_lock(self, edit):
        lock = json.loads(self.files[c.LOCK])
        edit(lock)
        self.files[c.LOCK] = json.dumps(lock).encode()

    def fail_at(self, name):
        result = c.check(self.read, self.names)
        self.assertEqual(result["result"], "FAIL")
        self.assertEqual(result["identity"], "UNVERIFIED_DO_NOT_RUN")
        self.assertTrue(any(r["name"] == name and not r["ok"] for r in result["checks"]), result)

    def mutate(self, path, old, new):
        self.assertIn(old, self.files[path])
        self.files[path] = self.files[path].replace(old, new)

    def test_baseline_and_no_external_reads(self):
        result = c.check(self.read, self.names)
        self.assertEqual(result["result"], "PASS", result)
        self.assertEqual(result["build"], "NOT_RUN")
        self.assertEqual(result["old_tests"], "NOT_RERUN")
        self.assertEqual(result["live_bsp"], "NOT_READ_OR_VALIDATED")
        self.assertEqual(set(self.reads), set(self.original))
        self.assertEqual(len(result["copy_sources"]), 7)

    def test_missing_file(self):
        del self.files[c.APP + "boot_id.h"]
        self.fail_at("input_error")

    def test_source_drift(self):
        p = c.APP + "boot_id.cpp"
        self.files[p] += b" // drift"
        self.fail_at("sha256:" + p)

    def test_evidence_drift(self):
        self.files[c.EVIDENCE[-1]] += b"changed"
        self.fail_at("sha256:" + c.EVIDENCE[-1])

    def test_duplicate_source(self):
        self.change_lock(lambda d: d["sources"].append(d["sources"][0]))
        self.fail_at("copy_set")
        self.assertEqual(self.reads, [c.LOCK])

    def test_missing_source_inventory(self):
        self.change_lock(lambda d: d["sources"].pop())
        self.fail_at("copy_set")

    def test_wrong_destination(self):
        self.change_lock(lambda d: d["sources"][0].update(destination="src/boot_id.cpp"))
        self.fail_at("copy_set")

    def test_external_input_rejected_before_read(self):
        self.change_lock(lambda d: d["evidence"][0].update(path="vitis/platform/bsp.h"))
        self.fail_at("evidence_set")
        self.assertEqual(self.reads, [c.LOCK])

    def test_extra_app_translation_unit(self):
        self.names.append("platform.c")
        self.fail_at("app_inventory")

    def test_invalid_json(self):
        self.files[c.LOCK] = b"{broken"
        self.fail_at("input_error")

    def test_invalid_schema(self):
        self.change_lock(lambda d: d.update(schema=2))
        self.fail_at("lock_version")

    def test_wrong_stage(self):
        self.change_lock(lambda d: d.update(stage="network-enabled"))
        self.fail_at("lock_version")

    def test_new_include(self):
        p = c.APP + "main.cpp"
        self.files[p] += b'\n#include "unlisted.h"\n'
        self.fail_at("includes:" + p)

    def test_identity_gate_open(self):
        self.mutate(c.APP + "boot_id.cpp", b"(void)out;",
                    b"return Uart0BootIdCandidate::acquire(out);")
        self.fail_at("closed_gates")

    def test_network_gate_open(self):
        self.mutate(c.APP + "main.cpp", b"kLabNetworkConfirmed = false", b"kLabNetworkConfirmed = true")
        self.fail_at("closed_gates")

    def test_initialization_before_gates(self):
        self.mutate(c.APP + "main.cpp", b"int main() {", b"int main() {\n    lwip_init();")
        self.fail_at("startup_order")

    def test_host_adapter_enabled(self):
        self.mutate(c.APP + "main.cpp", b"#define S2B_LOG_HOST_TEST 0", b"#define S2B_LOG_HOST_TEST 1")
        self.fail_at("host_adapters_default_off")

    def test_relock_does_not_transfer_old_test_coverage(self):
        p = c.APP + "main.cpp"
        self.files[p] += b" // new version"
        self.change_lock(lambda d: d["sources"][0].update(sha256=c.digest(self.files[p])))
        self.fail_at("source_provenance")

    def test_prior_failure_cannot_be_reused(self):
        data = json.loads(self.files[c.LOG_MANIFEST])
        data["result"] = "FAIL"
        self.files[c.LOG_MANIFEST] = json.dumps(data).encode()
        self.fail_at("prior_receipts")

    def test_path_traversal_and_windows_paths(self):
        for p in ("../outside", "/outside", "D:/outside", "src/../../outside", "src\\outside"):
            with self.subTest(path=p), self.assertRaises(ValueError):
                c.safe_path(ROOT, p)

    def test_fixed_read_allowlist(self):
        with self.assertRaises(ValueError):
            c.read_repo("vitis/s1b_m3a_plat/secret.h")

    def test_no_build_option(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            c.main(["--build"])
        self.assertEqual(cm.exception.code, 2)

    def test_cli_failure_exit(self):
        self.files[c.APP + "main.cpp"] += b" // drift"
        self.files["tools/check_s2b_integration.py"] = c.read_repo("tools/check_s2b_integration.py")
        out = io.StringIO()
        with patch.object(c, "read_repo", self.read), contextlib.redirect_stdout(out):
            rc = c.main([])
        self.assertEqual(rc, 1)
        self.assertEqual(json.loads(out.getvalue())["result"], "FAIL")


if __name__ == "__main__":
    unittest.main(verbosity=2)
