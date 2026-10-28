#!/usr/bin/env python3
"""Only new production-entry wiring: host C++ tests + reviewed source boundary.
No old suite, target compiler, BSP build, entropy generation, serial or sockets.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASE = "4a602e3"
APP = "src/ps/s2b_idle_app/"
SOURCES = [APP + n for n in ("main.cpp", "boot_id.cpp", "boot_id.h")] + [
    "src/ps/net/" + n for n in ("idle_lwip.cpp", "idle_lwip.h", "idle_protocol.cpp", "idle_protocol.h")]
CASES = ("entry-lf", "entry-zero-crlf", "entry-invalid", "entry-timeout", "entry-uart-error")

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def code(text):
    return re.sub(r"\s+", "", re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S))

def main():
    out = ROOT / "build/host" / datetime.now().strftime("s2b_connected_%Y%m%d_%H%M%S_%f")
    out.mkdir(parents=True, exist_ok=False)
    receipt = dict(scope="HOST_ENTRY_WIRING_ONLY", base=BASE, result="RUNNING",
                   old_suites="NOT_RERUN", target_build="NOT_RUN", commands=[], inputs=[])
    def save():
        (out / "manifest.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    def run(name, args):
        args = [str(a) for a in args]
        p = subprocess.run(args, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
        log = out / (name + ".log"); log.write_bytes(p.stdout)
        receipt["commands"].append(dict(name=name, argv=args, exit=p.returncode, log=log.name, sha256=sha(log)))
        save()
        if p.returncode: raise RuntimeError(name + ": " + p.stdout.decode(errors="replace"))
        return p.stdout.decode(errors="replace")
    try:
        inputs = SOURCES + ["docs/protocol.md", "sim/host/test_s2b_connected.cpp", "tools/test_s2b_connected.py"]
        receipt["inputs"] = [dict(path=n, sha256=sha(ROOT/n)) for n in inputs]
        old = {}
        for n in SOURCES + ["docs/protocol.md"]:
            old[n] = run("base_" + Path(n).name, ["git", "show", BASE + ":" + n])
        for n in SOURCES[2:] + ["docs/protocol.md"]:
            assert (ROOT/n).read_text(encoding="utf-8") == old[n], "protected source drift: " + n
        boot = (ROOT/(APP+"boot_id.cpp")).read_text(encoding="utf-8")
        prior = old[APP+"boot_id.cpp"]
        seam = "bool acquire_boot_id(uint32_t &out) {"
        assert code(boot.split(seam)[0]) == code(prior.split(seam)[0]), "r1 implementation changed"
        assert code(boot.split(seam)[1]) == "returnUart0BootIdCandidate::acquire(out);}}", "provider wiring"
        current = (ROOT/(APP+"main.cpp")).read_text(encoding="utf-8")
        expected = old[APP+"main.cpp"].replace("kLabNetworkConfirmed = false", "kLabNetworkConfirmed = true").replace(
            "S2B PREPARATION ONLY:", "S2B CONNECTED SOURCE r1:").replace(
            "boot_id provider NOT CONNECTED", "boot_id acquisition FAILED")
        assert code(current) == code(expected), "unexpected main semantic delta"
        entry = current[current.index("int main() {"):]
        markers = ("if (!s2b::acquire_boot_id(boot_id))", "stop(\"boot_id acquisition FAILED;", "if (!kLabNetworkConfirmed)",
                   "Xil_ICacheEnable();", "XScuGic_LookupConfig(", "lwip_init();", "xemac_add(", "idle(boot_id)", "idle.open()")
        offsets = [entry.index(m) for m in markers]
        assert offsets == sorted(offsets), "startup source ordering"
        receipt["source_review"] = "r1/parser/logs/net/public unchanged; only provider, release and two diagnostics differ"
        cxx = Path("D:/mingw64/bin/g++.exe")
        receipt["compiler_sha256"] = sha(cxx)
        run("compiler", [cxx, "--version"])
        binary = out/"test_s2b_connected.exe"
        run("compile_link_host", [cxx, "-std=c++11", "-O2", "-Wall", "-Wextra", "-Werror", "-pedantic",
                                  "-DS2B_BOOT_ID_HOST_TEST=1", ROOT/"sim/host/test_s2b_connected.cpp", "-o", binary])
        for case in CASES:
            text = run(case, [binary, case])
            assert "S2B_CONNECTED PASS " + case in text, "missing PASS marker"
        receipt["cases_passed"] = len(CASES)
        assert all(sha(ROOT/r["path"]) == r["sha256"] for r in receipt["inputs"]), "inputs changed during test"
        receipt["result"] = "PASS"
    except (OSError, ValueError, RuntimeError, AssertionError, subprocess.TimeoutExpired) as exc:
        receipt["result"] = "FAIL"; receipt["error"] = str(exc)
    finally:
        receipt["finished"] = datetime.now(timezone.utc).isoformat(); save()
    print(receipt["result"], out)
    if "error" in receipt: print(receipt["error"])
    return 0 if receipt["result"] == "PASS" else 1

if __name__ == "__main__":
    raise SystemExit(main())
