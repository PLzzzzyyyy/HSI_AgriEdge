"""S2b boot_id HOST ONLY: actual dormant candidate, simulated byte/time/status.

No App/main/BSP build, packaging, target tool, device, entropy or network access.
The default-off check reads existing BSP headers but links no target library.
All generated artifacts stay in a fresh directory below build/host.
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
SOURCE = ROOT / "src/ps/s2b_idle_app/boot_id.cpp"
TEST = ROOT / "sim/host/test_s2b_boot_id.cpp"
BSP = ROOT / "vitis/s1b_m3a_plat/psu_cortexa53_0/standalone_domain/bsp/psu_cortexa53_0/include"
BASE = "9d4fed8c70de487653d990d88b35925b97a39299"
PROTECTED = (
    "src/ps/s2b_idle_app/main.cpp", "src/ps/s2b_idle_app/boot_id.h",
    "src/ps/s2b_idle_app/README.md", "src/ps/net/idle_lwip.cpp",
    "src/ps/net/idle_lwip.h", "src/ps/net/idle_protocol.cpp",
    "src/ps/net/idle_protocol.h", "docs/protocol.md",
)
CASES = (
    "lf", "crlf", "zero", "max", "upper", "wrap", "rx-trigger",
    "fractional-frequency", "high-frequency", "delayed-after-success",
    "empty", "missing-eol", "cr-only", "partial", "short-line", "ninth-digit",
    "prefix", "space", "crcrlf", "trailing-space", "lfcr", "double-line", "burst",
    "tail-before", "tail-equal", "tail-final", "residue64", "residue65",
    "residue-max-frame", "residue-quiet-reset", "first-empty-delay",
    "residue-equal", "residue-before", "residue-active",
    "prompt-full", "prompt-before", "prompt-equal", "prompt-rx", "prompt-final-rx",
    "total-before", "total-equal", "total-first-byte", "total-after-pop", "slow-drip",
    "prompt-total", "residue-total", "frequency-zero", "frequency-overflow", "frequency-low",
) + tuple(f"bad-{byte}" for byte in (0, 8, 9, 10, 13, 27, 32, 43, 45, 47, 58, 64, 71, 96, 103, 127, 128, 255)) + tuple(
    f"position-{pos}" for pos in range(8)
) + tuple(f"error-{mask}-{phase}" for mask in (32, 64, 128) for phase in (
    "residue", "after-discard", "prompt", "prompt-final", "frame", "after-pop",
    "after-eol", "tail", "final",
))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="D:/mingw64/bin/g++.exe")
    parser.add_argument("--bsp-include", type=Path, default=BSP)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    out = (args.out or ROOT / "build/host" / datetime.now().strftime("s2b_boot_id_%Y%m%d_%H%M%S_%f")).resolve()
    if not out.is_relative_to((ROOT / "build/host").resolve()) or out == (ROOT / "build/host").resolve():
        parser.error("--out must be a fresh subdirectory of build/host")
    out.mkdir(parents=True, exist_ok=False)
    receipt = dict(scope=__doc__, base_commit=BASE, started=datetime.now().astimezone().isoformat(),
                   result="RUNNING", commands=[], cases_expected=len(CASES), cases_passed=0)

    def save():
        (out / "manifest.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

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
                code = -1
                timed_out = True
        text = log.read_text(encoding="utf-8", errors="replace")
        ok = not timed_out and (code != 0 if expect_failure else code == 0) and (marker is None or marker in text)
        receipt["commands"].append(dict(name=name, argv=argv, exit=code, timeout=timed_out,
            expected_failure=expect_failure, passed=ok, seconds=round(time.monotonic() - start, 3),
            log=log.name, sha256=sha(log)))
        save()
        print(name, "PASS" if ok else "FAIL", flush=True)
        if not ok:
            raise RuntimeError(f"{name}: {text[-5000:]}")
        return text

    try:
        compiler = Path(shutil.which(args.cxx) or args.cxx).resolve(strict=True)
        nm = compiler.with_name("nm.exe" if compiler.suffix == ".exe" else "nm")
        receipt["compiler"] = dict(path=str(compiler), sha256=sha(compiler))
        # No mutation or build of this BSP: headers are only compilation inputs.
        headers = sorted(args.bsp_include.resolve().glob("*.h"))
        inputs = [SOURCE, TEST, Path(__file__).resolve()] + [ROOT / p for p in PROTECTED] + headers
        receipt["inputs"] = [dict(path=str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p),
                                  sha256=sha(p)) for p in inputs]
        original_hashes = {p: sha(p) for p in inputs}
        run("protected_baseline", ["git", "diff", "--exit-code", BASE, "--", *PROTECTED])
        main_text = (ROOT / PROTECTED[0]).read_text(encoding="utf-8")
        if "constexpr bool kLabNetworkConfirmed = false;" not in main_text:
            raise RuntimeError("network gate text is not closed")
        register_text = (args.bsp_include / "xuartps_hw.h").read_text(encoding="utf-8")
        source_text = SOURCE.read_text(encoding="utf-8")
        bits = dict(re.findall(r"constexpr uint32_t (XUARTPS_\w+) = (0x[0-9a-fA-F]+)U;", source_text))
        if len(bits) != 8:
            raise RuntimeError("unexpected adapter register surface")
        for name, value in bits.items():
            match = re.search(r"#define\s+" + name + r"\s+(0x[0-9a-fA-F]+)U", register_text)
            if not match or int(value, 16) != int(match[1], 16):
                raise RuntimeError(f"adapter/BSP register mismatch: {name}")
        receipt["register_mapping"] = "8 private constants match existing BSP header"
        run("compiler", [compiler, "--version"])
        common = ["-std=c++14", "-Wall", "-Wextra", "-Werror", "-pedantic"]
        binary = out / "test_s2b_boot_id.exe"
        run("compile_link_host", [compiler, *common, "-O2", "-DS2B_BOOT_ID_HOST_TEST=1", TEST, "-o", binary])
        # Test the REAL default-off source separately, using only existing headers.
        # O0 ensures the closed entry is not an O2-only accident. No BSP library.
        for label, flags in (("absent", ["-O0"]), ("zero", ["-O2", "-DS2B_BOOT_ID_HOST_TEST=0"])):
            closed = out / ("default_off_" + label + ".exe")
            obj = out / ("default_off_" + label + ".o")
            run("compile_default_" + label, [compiler, *common, *flags, "-isystem", args.bsp_include,
                "-c", SOURCE, "-o", obj])
            symbols = run("symbols_default_" + label, [nm, "-C", obj])
            if any(s in symbols for s in ("XTime", "XUart", "Uart0BootIdCandidate", "boot_id_host_io", "uart_read", "uart_write")):
                raise RuntimeError("default-off object unexpectedly contains platform/candidate symbols")
            run("link_default_" + label, [compiler, *common, *flags, TEST, obj, "-o", closed])
            run("run_default_" + label, [closed], "S2B_BOOT_ID DEFAULT_OFF PASS", timeout=10)
        run("reject_target_adapter", [compiler, *common, "-DS2B_BOOT_ID_HOST_TEST=1", "-D__aarch64__",
            "-fsyntax-only", TEST], "must not be used in a target App", expect_failure=True)
        run("reject_invalid_switch", [compiler, *common, "-DS2B_BOOT_ID_HOST_TEST=2",
            "-fsyntax-only", SOURCE], "must be 0 or 1", expect_failure=True)
        failed = []
        for case in CASES:
            try:
                run(case, [binary, case], "S2B_BOOT_ID PASS " + case, timeout=10)
                receipt["cases_passed"] += 1
            except RuntimeError as exc:
                failed.append(case)
                print(exc, flush=True)
        receipt["failed_cases"] = failed
        receipt["inputs_unchanged_after_run"] = all(sha(p) == value for p, value in original_hashes.items())
        receipt["artifacts"] = [dict(path=p.name, sha256=sha(p)) for p in sorted(out.iterdir())
                                if p.suffix in (".exe", ".o")]
        if failed or not receipt["inputs_unchanged_after_run"]:
            raise RuntimeError(f"failed cases={failed}; inputs unchanged={receipt['inputs_unchanged_after_run']}")
        receipt["result"] = "PASS"
    except (RuntimeError, OSError, ValueError) as exc:
        receipt["result"] = "FAIL"
        receipt["error"] = str(exc)
        print(exc, flush=True)
    finally:
        receipt["finished"] = datetime.now().astimezone().isoformat()
        save()
    print("S2B_BOOT_ID_SUITE", receipt["result"], out, flush=True)
    return 0 if receipt["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
