"""Gate M3a system implementation on full RTL coverage and export provenance."""
import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def read_log(path):
    data = Path(path).read_bytes()
    return data.decode("utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig")


def validate_log(text):
    required = [r"tt_engine M3a tb: TT_K3=7, layers=12", r"error codes: PASS",
                r"batch n_patch=3 \(A, B embed, A\): LOGITS \+ CLASS mismatches=0",
                r"layers 5\.\.11 from L4 x_out: FEAT \+ CLASS mismatches=0",
                r"PROJ layer 0 \(QKV \+ MLP, int16 sat\): mismatches=0",
                r"C/RTL co-simulation finished: PASS"]
    required += [rf"(?m)^layer\s+{i}: x_out mismatches=0\s*$" for i in range(12)]
    missing = [pattern for pattern in required if not re.search(pattern, text)]
    if missing:
        raise ValueError("Full M3a cosim incomplete: " + "; ".join(missing))
    if re.search(r"(?m)^\s*(ERROR:|FATAL:|FAIL:)", text) or re.search(r"mismatches=[1-9]\d*", text):
        raise ValueError("Full cosim contains errors or mismatches")


def synthesis_text(path):
    text = Path(path).read_text(encoding="utf-8")
    # HLS IP export adds a simulation-only deadlock detector at the end of top.
    text = re.sub(r"// synthesis translate_off.*?// synthesis translate_on", "", text, flags=re.S)
    return "\n".join(line.rstrip() for line in text.splitlines() if line.strip())


def check(root, log):
    validate_log(read_log(log))
    build = root / "build/hls/optimization_build/tt_engine_m3_k7"
    snapshot = build / "snapshot"
    config = dict(line.split("=", 1) for line in (snapshot / "flags.txt").read_text().splitlines() if "=" in line)
    flags = config.get("flags", "").split()
    if "-DTT_DB=18" not in flags or "-DTT_K3=7" not in flags or config.get("clock_ns") not in ("5", "5.0"):
        raise ValueError("Wrong synthesis configuration")
    paths = [Path("src/hls") / n for n in ("tt_engine.cpp", "tt_engine.h", "tt_engine_regs.h", "tt_types.h", "tt_attn.cpp", "tt_attn.h")]
    paths += [Path("src/ps/tt_ref_int.h"), Path("sim/hls_tb/tb_tt_engine_full.cpp")]
    golden = {p.relative_to(root) for p in (root / "sim/golden/n6_engine").rglob("*") if p.is_file()}
    snapshot_golden = {p.relative_to(snapshot) for p in (snapshot / "sim/golden/n6_engine").rglob("*") if p.is_file()}
    if not golden or golden != snapshot_golden:
        raise ValueError("Missing or changed golden file set")
    paths += sorted(golden)
    for rel in paths:
        if (root / rel).read_bytes() != (snapshot / rel).read_bytes():
            raise ValueError("Current source/golden differs from synthesized snapshot: " + str(rel))
    syn = build / "sol/syn/verilog"
    exported = build / "sol/impl/ip/hdl/verilog"
    rtl = [p for p in syn.iterdir() if p.suffix in (".v", ".dat") and p.name != "AESL_FPSim_pkg.v"]
    if not rtl or not (exported / "tt_engine.v").is_file():
        raise ValueError("Missing exported RTL")
    records = []
    for p in rtl:
        q = exported / p.name
        if synthesis_text(p) != synthesis_text(q):
            raise ValueError("Exported RTL differs from cosim synthesis: " + p.name)
        records.append({"name": p.name, "syn_sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                        "export_sha256": hashlib.sha256(q.read_bytes()).hexdigest()})
    return {"status": "M3A_READY_FOR_SYSTEM_BUILD", "log": str(log),
            "log_sha256": hashlib.sha256(Path(log).read_bytes()).hexdigest(),
            "snapshot_files_matched": len(paths), "export_rtl_files_matched": len(rtl),
            "note": "Source and synthesis match; IP export simulation-only blocks excluded from textual equivalence. Not a formal equivalence proof or board PASS.",
            "rtl": records}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--log", type=Path, default=ROOT / "build/host/m3a_full_20261007/vitis_hls.log")
    p.add_argument("--output", type=Path)
    args = p.parse_args()
    try:
        result = check(ROOT, args.log.resolve())
    except (OSError, ValueError) as exc:
        p.exit(1, "M3A_NOT_READY: " + str(exc) + "\n")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
            f.write("\n")
    print(result["status"], "snapshot=", result["snapshot_files_matched"], "rtl=", result["export_rtl_files_matched"])


if __name__ == "__main__":
    main()
