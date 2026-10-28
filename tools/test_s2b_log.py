"""S2b actual private logging: HOST ONLY, no App entry execution or target build.

Compile/link/run only sim/host/test_s2b_log.cpp including actual main.cpp logs.
The default-off production branches are PREPROCESSED ONLY with existing BSP
headers; no App object, target library, identity source, device or network use.
All generated artifacts go into a fresh build/host subdirectory; never overwrite.
"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src/ps/s2b_idle_app/main.cpp"
TEST = ROOT / "sim/host/test_s2b_log.cpp"
BSP = ROOT / "vitis/s1b_m3a_plat/psu_cortexa53_0/standalone_domain/bsp/psu_cortexa53_0/include"
BASE = "4b0cc9f"
PROTECTED = (
    "src/ps/s2b_idle_app/boot_id.cpp", "src/ps/s2b_idle_app/boot_id.h",
    "src/ps/s2b_idle_app/README.md", "src/ps/net", "docs/protocol.md",
    "sim/host/test_s2b_boot_id.cpp", "tools/test_s2b_boot_id.py",
)
CASES = tuple(f"length-{n}" for n in (0, 1, 2, 93, 94, 95, 96, 97, 98, 1024)) + tuple(
    f"txfull-{n}" for n in range(96)
) + tuple(f"status-bit-{n}" for n in range(32)) + tuple(
    f"stop-length-{n}" for n in (0, 1, 94, 95, 96, 97, 1024)
) + (
    "status-all", "nul-short-circuit", "byte-domain", "repeated-calls",
    "format-matrix", "format-txfull", "stop-txfull", "stop-embedded-nul", "guard-pages",
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def body(text, signature):
    """Extract known source function bodies for a narrow, non-behavioral audit."""
    start = text.index("{", text.index(signature))
    depth = 1
    end = start + 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="D:/mingw64/bin/g++.exe")
    parser.add_argument("--bsp-include", type=Path, default=BSP)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    out = (args.out or ROOT / "build/host" / datetime.now().strftime("s2b_log_%Y%m%d_%H%M%S_%f")).resolve()
    host = (ROOT / "build/host").resolve()
    if not out.is_relative_to(host) or out == host:
        parser.error("--out must be a fresh subdirectory of build/host")
    out.mkdir(parents=True, exist_ok=False)
    receipt = dict(scope=__doc__, base_commit=BASE, started=datetime.now().astimezone().isoformat(),
                   result="RUNNING", commands=[], scenarios_per_configuration=len(CASES),
                   scenarios_expected=2 * len(CASES), scenarios_passed=0, checked_calls=0)
    audit = {}
    inputs = set()

    def save():
        (out / "manifest.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        (out / "audit.json").write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")

    def run(name, argv, marker=None, expect_failure=False, timeout=60):
        argv = list(map(str, argv))
        log = out / (name + ".txt")
        start = time.monotonic()
        timed_out = False
        with log.open("wb") as stream:
            try:
                code = subprocess.run(argv, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                                      timeout=timeout, shell=False).returncode
            except subprocess.TimeoutExpired:
                code, timed_out = -1, True
        text = log.read_text(encoding="utf-8", errors="replace")
        ok = not timed_out and (code != 0 if expect_failure else code == 0) and (marker is None or marker in text)
        receipt["commands"].append(dict(name=name, argv=argv, exit=code, timed_out=timed_out,
            expected_failure=expect_failure, ok=ok, seconds=round(time.monotonic() - start, 4),
            log=log.name, log_sha256=sha(log)))
        save()
        if not ok:
            raise RuntimeError(f"{name} failed; see {log}")
        return text

    def collect_headers(text):
        for path in re.findall(r'^#\s+\d+\s+"([^"<>]+)"', text, re.MULTILINE):
            p = Path(path)
            if not p.is_absolute():
                p = ROOT / p
            if p.is_file():
                inputs.add(p.resolve())

    try:
        compiler = Path(shutil.which(args.cxx) or args.cxx).resolve()
        nm = compiler.with_name("nm.exe" if compiler.suffix == ".exe" else "nm")
        if not compiler.is_file() or not nm.is_file():
            raise RuntimeError("host g++ and adjacent nm are required")
        inputs.update((SOURCE, TEST, Path(__file__).resolve(), compiler, nm))
        receipt["head_at_start"] = run("head", ["git", "rev-parse", "HEAD"]).strip()
        if run("protected_diff", ["git", "diff", BASE, "--", *PROTECTED]).strip():
            raise RuntimeError("protected source differs from authorized starting point")
        for path in PROTECTED:
            p = ROOT / path
            inputs.update(p.rglob("*")) if p.is_dir() else inputs.add(p)
        source = SOURCE.read_text(encoding="utf-8")
        baseline = run("base_main", ["git", "show", f"{BASE}:src/ps/s2b_idle_app/main.cpp"])
        # Detect accidental unrelated edits in the dormant App body/formatting.
        old_format = baseline[baseline.index("    // Fixed-width formatting"):baseline.index("    for (;;) {", baseline.index("    // Fixed-width formatting"))]
        expected_main = body(baseline, "int main()").replace(old_format, "    log_bound(boot_id);\n")
        if body(source, "int main()") != expected_main:
            raise RuntimeError("App body changed beyond the private formatting extraction")
        expected_format = old_format[old_format.index("    char bound[]"):]
        actual_format = body(source, "void log_bound(")
        if expected_format.rstrip() not in actual_format:
            raise RuntimeError("private formatter differs from original inline implementation")
        expected_log = body(baseline, "bool try_log(").replace(
            "XUartPs_ReadReg(\n            XPAR_XUARTPS_0_BASEADDR, XUARTPS_SR_OFFSET)", "log_uart_status()"
        ).replace("XUartPs_WriteReg(XPAR_XUARTPS_0_BASEADDR, XUARTPS_FIFO_OFFSET,\n                        static_cast<uint8_t>(text[i]))",
                  "log_uart_byte(static_cast<uint8_t>(text[i]))")
        if body(source, "bool try_log(") != expected_log:
            raise RuntimeError("try_log changed beyond private I/O adaptation")
        if "constexpr bool kLabNetworkConfirmed = false;" not in source:
            raise RuntimeError("network gate not closed")
        boot = (ROOT / PROTECTED[0]).read_text(encoding="utf-8")
        audit["production_provider_body"] = body(boot, "bool acquire_boot_id(")
        if not re.fullmatch(r"\{\s*//[^\n]*\n\s*\(void\)out;\s*return false;\s*\}", audit["production_provider_body"]):
            # Permit its existing explanatory comments, not arbitrary statements.
            clean = re.sub(r"//[^\n]*", "", audit["production_provider_body"])
            if re.sub(r"\s+", "", clean) != "{(void)out;returnfalse;}":
                raise RuntimeError("production provider is not a no-write false stub")
        register_header = args.bsp_include / "xuartps_hw.h"
        inputs.add(register_header.resolve())
        registers = register_header.read_text(encoding="utf-8")
        bits = dict(re.findall(r"constexpr uint32_t (XUARTPS_\w+) = (0x[0-9a-fA-F]+)U;", source))
        if len(bits) != 3:
            raise RuntimeError("unexpected private register surface")
        for name, value in bits.items():
            match = re.search(r"#define\s+" + name + r"\s+(0x[0-9a-fA-F]+)U", registers)
            if not match or int(value, 16) != int(match[1], 16):
                raise RuntimeError(f"private/BSP register mismatch: {name}")
        audit.update(protected_paths_unchanged=list(PROTECTED), network_gate=False,
                     app_body_only_formatter_extracted=True, formatter_verbatim=True,
                     logger_only_io_adapted=True, register_mapping=bits)
        run("compiler", [compiler, "--version"])
        common = ["-std=c++14", "-Wall", "-Wextra", "-Werror", "-pedantic"]
        # Host preprocessing only, NOT compiling a target App or running its main.
        pp_texts = []
        for label, flags in (("absent", []), ("zero", ["-DS2B_LOG_HOST_TEST=0"])):
            pp = out / ("production_" + label + ".ii")
            run("preprocess_production_" + label, [compiler, "-std=c++14", "-E", *flags,
                "-D__aarch64__", "-isystem", args.bsp_include, "-I", ROOT / "src/ps/net",
                SOURCE, "-o", pp])
            text = pp.read_text(encoding="utf-8")
            collect_headers(text)
            if any(s in text for s in ("LogHostIo", "log_host_io")):
                raise RuntimeError("test adapter leaked into default-off production preprocessing")
            stop_body = body(text, "void stop(")
            if "msr DAIF" not in stop_body or "for (;;) {}" not in stop_body:
                raise RuntimeError("production STOP lost disable/permanent loop")
            audit["production_stop_body"] = stop_body
            pp_texts.append(re.sub(r"^#.*$", "", text, flags=re.MULTILINE))
        if pp_texts[0] != pp_texts[1]:
            raise RuntimeError("default-off and explicit-zero production differ")
        audit["default_off"] = "absent == zero, test hooks absent; preprocessing ONLY"
        host_pp = out / "host.ii"
        run("preprocess_host", [compiler, "-std=c++14", "-E", "-DS2B_LOG_HOST_TEST=1", TEST, "-o", host_pp])
        text = host_pp.read_text(encoding="utf-8")
        collect_headers(text)
        if any(s in text for s in ("s2b::acquire_boot_id", "xemac_add(", "XTime_GetTime(", "class StackTimers")):
            raise RuntimeError("App/network/timer path leaked into host harness")
        if len(re.findall(r"\bint main\s*\(", text)) != 1:
            raise RuntimeError("host preprocessing does not contain exactly the test entry")
        audit["host_app_excluded"] = True
        for label, flags in (("aarch64", ["-D__aarch64__"]), ("arm", ["-D__arm__"]),
                             ("invalid", ["-US2B_LOG_HOST_TEST", "-DS2B_LOG_HOST_TEST=2"])):
            marker = "must be 0 or 1" if label == "invalid" else "must not be used in a target App"
            run("reject_" + label, [compiler, *common, "-DS2B_LOG_HOST_TEST=1", *flags,
                "-fsyntax-only", SOURCE], marker, expect_failure=True)
        failures = []
        for label, flags in (("o0_signed", ["-O0", "-fsigned-char"]),
                             ("o2_unsigned", ["-O2", "-funsigned-char"])):
            obj = out / (label + ".o")
            binary = out / (label + ".exe")
            run("compile_" + label, [compiler, *common, *flags, "-DS2B_LOG_HOST_TEST=1", "-c", TEST, "-o", obj])
            run("link_" + label, [compiler, obj, "-o", binary])
            symbols = run("symbols_" + label, [nm, "-C", obj])
            if any(s in symbols for s in ("acquire_boot_id", "XTime", "XUart", "lwip", "xemac", "StackTimers")):
                raise RuntimeError("unexpected target symbol in host object")
            for case in CASES:
                try:
                    text = run(label + "_" + case, [binary, case], "S2B_LOG PASS " + case + " calls=", timeout=10)
                    receipt["scenarios_passed"] += 1
                    receipt["checked_calls"] += int(re.search(r"calls=(\d+)", text)[1])
                except RuntimeError as exc:
                    failures.append(str(exc))
            print(f"{label}: completed {len(CASES)} scenarios", flush=True)
        if failures:
            receipt["failures"] = failures
            raise RuntimeError(f"{len(failures)} host scenarios failed")
        receipt["result"] = "PASS"
    except Exception as exc:
        receipt["result"] = "FAIL"
        receipt["error"] = repr(exc)
    finally:
        receipt["finished"] = datetime.now().astimezone().isoformat()
        receipt["input_hashes"] = [dict(path=str(p), bytes=p.stat().st_size, sha256=sha(p))
                                   for p in sorted(inputs) if p.is_file()]
        receipt["outputs"] = [dict(path=p.name, bytes=p.stat().st_size, sha256=sha(p))
                              for p in sorted(out.iterdir()) if p.suffix in (".o", ".exe", ".ii")]
        save()
    print(f"S2B_LOG {receipt['result']} {receipt['scenarios_passed']}/{receipt['scenarios_expected']} "
          f"scenarios, {receipt['checked_calls']} calls; {out}")
    return 0 if receipt["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
