#!/usr/bin/env python3
"""Repository-only CLOSED-gate preflight; no compiler, tool launch or live BSP.
Default: JSON stdout, no writes. --record: fresh build/host receipt only.
PASS is not Build/board acceptance or authorization. No automatic relock.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
LOCK = "tools/s2b_integration_manifest.json"
BASE = "01462f4a9d17b69206708568ac24dcb990a14cae"
APP = "src/ps/s2b_idle_app/"
SOURCES = tuple(APP + p for p in ("main.cpp", "boot_id.cpp", "boot_id.h")) + tuple(
    "src/ps/net/" + p for p in
    ("idle_lwip.cpp", "idle_lwip.h", "idle_protocol.cpp", "idle_protocol.h"))
LOG_MANIFEST = "report/system_s2b/20261010_log_host/manifest.json"
BOOT_MANIFEST = "report/system_s2b/20261010_boot_id_host_r1/manifest.json"
PREP_MANIFEST = "report/system_s2b/20261009_prepare_r1/manifest.json"
EVIDENCE = (LOG_MANIFEST, BOOT_MANIFEST, PREP_MANIFEST,
            "report/system_s2b/20261010_log_host/review.md",
            "report/system_s2b/20261010_boot_id_host_r1/review.md")
STANDARD = {"stdint.h", "stddef.h", "string.h", "cstdint"}
PLATFORM = {"xparameters.h", "xtime_l.h", "xuartps_hw.h", "xscugic.h",
            "xil_cache.h", "xil_exception.h", "lwip/init.h", "lwip/etharp.h",
            "lwip/ip4_frag.h", "lwip/priv/tcp_priv.h", "netif/xadapter.h",
            "lwip/udp.h"}
ALLOWED = set(SOURCES + EVIDENCE + (LOCK, "tools/check_s2b_integration.py"))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def safe_path(root, relative):
    """Reject traversal/Windows paths and resolved symlink/junction escapes."""
    if ("\\" in relative or ":" in relative or PurePosixPath(relative).is_absolute()
            or ".." in PurePosixPath(relative).parts):
        raise ValueError("unsafe repository path: " + relative)
    root = root.resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError("path escapes repository: " + relative)
    return path


def read_repo(relative):
    if relative not in ALLOWED:
        raise ValueError("not in fixed input allowlist: " + relative)
    return safe_path(ROOT, relative).read_bytes()


def includes(text):
    # Inventory ALL branches, including dormant host includes. NOT a parser;
    # the byte hash lock is what rejects arbitrary C++ edits.
    return sorted(set(re.findall(r'^\s*#\s*include\s*[<"]([^>"\n]+)[>"]',
                                 text, re.MULTILINE)))


def uncomment(text):
    return re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.DOTALL)


def snapshot_hash(records, relative):
    # Historical absolute names are LABELS only; never open those paths.
    matches = [r["sha256"] for r in records
               if r["path"].replace("\\", "/") == relative or
               r["path"].replace("\\", "/").endswith("/" + relative)]
    return matches[0] if len(matches) == 1 else None


def check(read_bytes, app_names):
    """File-content checks; tests use in-memory files, not board IO."""
    checks = []
    def expect(name, ok, detail):
        checks.append({"name": name, "ok": bool(ok), "detail": detail})
    result = {
        "schema": 1, "scope": "REPOSITORY_ONLY_CLOSED_GATE_SOURCE_PREFLIGHT",
        "baseline_commit": BASE, "checks": checks,
        "identity": "CLOSED", "network": "CLOSED",
        "build": "NOT_RUN", "board": "NOT_RUN", "old_tests": "NOT_RERUN",
        "live_bsp": "NOT_READ_OR_VALIDATED",
        "next": "Separate authorization, then USER manual gate-only App Build; stop for receipt review.",
    }
    try:
        raw_lock = read_bytes(LOCK)
        lock = json.loads(raw_lock)
        result["manifest_sha256"] = digest(raw_lock)
        expect("lock_version", lock["schema"] == 1 and lock["base_commit"] == BASE
               and lock["stage"] == "closed-gate", "reviewed baseline; no automatic relock")
        src, evidence = lock["sources"], lock["evidence"]
        valid_sources = (len(src) == len(SOURCES) and
                         {r["path"] for r in src} == set(SOURCES) and
                         all(r["destination"] == "src/" + PurePosixPath(r["path"]).name for r in src))
        valid_evidence = (len(evidence) == len(EVIDENCE) and
                          {r["path"] for r in evidence} == set(EVIDENCE))
        expect("copy_set", valid_sources, "exactly 4 cpp + 3 h; flat, unique destinations")
        expect("evidence_set", valid_evidence, "five archived anchors, not live BSP files")
        if not valid_sources or not valid_evidence:
            raise ValueError("invalid inventory; no manifest-supplied path will be opened")
        expect("app_inventory", set(app_names) == {"main.cpp", "boot_id.cpp", "boot_id.h"},
               "no extra C/C++/header/assembly source in private App directory")
        data = {}
        for row in src + evidence:
            path = row["path"]
            data[path] = read_bytes(path)
            expect("sha256:" + path, digest(data[path]) == row["sha256"],
                   "byte-exact baseline; drift needs review, not automatic old-test rerun")
        local = {PurePosixPath(p).name for p in SOURCES if p.endswith(".h")}
        for row in src:
            found = includes(data[row["path"]].decode("utf-8-sig"))
            expect("includes:" + row["path"], found == row["includes"] and
                   not (set(found) - local - STANDARD - PLATFORM),
                   "local closure + declared dependencies, NOT BSP header resolution")
        latest, boot, prep = (json.loads(data[p]) for p in
                              (LOG_MANIFEST, BOOT_MANIFEST, PREP_MANIFEST))
        expect("prior_receipts", latest["result"] == boot["result"] == "PASS" and
               latest["scenarios_passed"] == latest["scenarios_expected"] == 308 and
               boot["cases_passed"] == boot["cases_expected"] == 102,
               "archived results only; no compiler or prior-test invocation")
        expect("source_provenance", all(snapshot_hash(latest["input_hashes"], p) ==
               digest(data[p]) for p in SOURCES) and
               snapshot_hash(boot["inputs"], APP + "boot_id.cpp") == digest(data[APP + "boot_id.cpp"]),
               "seven files match latest snapshot; boot candidate matches its tested version")
        expect("net_provenance", all(snapshot_hash(prep["inputs"], p) == digest(data[p])
               for p in SOURCES if p.startswith("src/ps/net/")),
               "net/public unchanged since preparation; not a new net validation")
        main = uncomment(data[APP + "main.cpp"].decode())
        boot_src = uncomment(data[APP + "boot_id.cpp"].decode())
        closed = re.search(r'bool\s+acquire_boot_id\(uint32_t\s*&out\)\s*'
                           r'\{\s*\(void\)out;\s*return false;\s*\}', boot_src)
        expect("closed_gates", closed and "constexpr bool kLabNetworkConfirmed = false;" in main,
               "inert production provider + false network constant")
        entry = main[main.index("int main() {"):]
        markers = ["if (!s2b::acquire_boot_id(boot_id))", "if (!kLabNetworkConfirmed)",
                   "Xil_ICacheEnable();", "XScuGic_LookupConfig(", "lwip_init();", "xemac_add(", "idle.open()"]
        offsets = [entry.index(s) for s in markers]
        expect("startup_order", offsets == sorted(offsets), "identity -> network -> cache/GIC -> lwIP/GEM -> UDP")
        expect("host_adapters_default_off", all(
            re.search(r'#ifndef ' + macro + r'\s+#define ' + macro + r' 0\s+#endif', text)
            for text, macro in ((main, "S2B_LOG_HOST_TEST"), (boot_src, "S2B_BOOT_ID_HOST_TEST"))),
            "target Build must omit both host macros and test translation units")
        result["copy_sources"] = [{"path": r["path"], "destination": r["destination"],
                                    "sha256": digest(data[r["path"]])} for r in src]
        result["platform_includes_not_resolved"] = sorted(PLATFORM)
    except (OSError, ValueError, KeyError, TypeError, UnicodeError) as exc:
        expect("input_error", False, str(exc))
    result["result"] = "PASS" if checks and all(c["ok"] for c in checks) else "FAIL"
    if result["result"] != "PASS":
        result["identity"] = result["network"] = "UNVERIFIED_DO_NOT_RUN"
        result["next"] = "STOP: inspect failures; do not build, relock, or rerun prior suites automatically."
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", action="store_true", help="save a fresh build/host JSON receipt")
    args = parser.parse_args(argv)
    try:
        app_dir = safe_path(ROOT, APP)
        names = [p.name for p in app_dir.iterdir()
                 if p.suffix.lower() in {".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".s"}]
        result = check(read_repo, names)
        result["checker_sha256"] = digest(read_repo("tools/check_s2b_integration.py"))
        result["checked_at"] = datetime.now(timezone.utc).isoformat()
        if args.record:
            parent = safe_path(ROOT, "build/host")
            parent.mkdir(parents=True, exist_ok=True)
            out = safe_path(ROOT, "build/host/s2b_integration_" +
                            datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f"))
            out.mkdir(exist_ok=False)
            result["receipt"] = str(out / "receipt.json")
            with (out / "receipt.json").open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["result"] == "PASS" else 1
    except (OSError, ValueError) as exc:
        print(json.dumps({"result": "ERROR", "error": str(exc), "build": "NOT_RUN"}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
