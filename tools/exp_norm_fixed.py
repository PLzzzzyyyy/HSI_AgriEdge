"""Host experiment for hardware round 4: integer normalize in the PL model, x stored as float (F=24, Q8.24 view)
or as int16 Q3.12 (F=12). Runs sim/host/exp_norm_fixed.cpp over the 4096-pixel block in parallel chunks and
compares with the PC fixed/float references and with the production float32 host path. Never a board measurement.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import math
from pathlib import Path
import subprocess
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str]) -> str:
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}): {command}\n{result.stdout}\n{result.stderr}")
    return result.stdout


def merge_stats(files: list[Path]) -> dict:
    merged: dict[str, float] = {}
    for path in files:
        for line in path.read_text().splitlines():
            key, value = line.split("=", 1)
            v = float(value)
            if key in ("saturated", "calls", "elements", "flips1", "flips_gt1"):
                merged[key] = merged.get(key, 0) + v
            elif key == "min_inv":
                merged[key] = min(merged.get(key, math.inf), v)
            else:
                merged[key] = max(merged.get(key, -math.inf), v)
    return merged


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", default="D:/mingw64/bin/g++.exe")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--modes", default="24,12")
    parser.add_argument("--pixels", type=int, default=0, help="0 = whole block")
    parser.add_argument("--output", type=Path, default=ROOT / "build" / "host" / "exp_norm_fixed")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    exe = output / "exp_norm_fixed.exe"
    sources = [ROOT / "sim" / "host" / "exp_norm_fixed.cpp", ROOT / "src" / "ps" / "tt_net.cpp", ROOT / "src" / "ps" / "tt_hw_sim.cpp"]
    run([args.compiler, "-O2", "-std=gnu++11", "-ffp-contract=off", *map(str, sources), "-o", str(exe)])

    block = ROOT / "model" / "data" / "block"
    meta = dict(line.split("=", 1) for line in (block / "meta.txt").read_text().splitlines() if "=" in line)
    side = int(meta["size"])
    total = side * side if args.pixels == 0 else args.pixels
    ref_logits = np.fromfile(block / "ref_fixed_logits.bin", dtype="<f8").reshape(side * side, 9)[:total]
    ref_fixed = np.fromfile(block / "ref_fixed_u8.bin", dtype=np.uint8)[:total]
    ref_float = np.fromfile(block / "ref_float_u8.bin", dtype=np.uint8)[:total]
    gt = np.fromfile(block / "gt_u8.bin", dtype=np.uint8)[:total]
    chunks = [(first, min(128, total - first)) for first in range(0, total, 128)]
    report: dict = {"source": "host simulation (integer projection + integer normalize model); NOT board measurements",
                    "pixels": total, "modes": {}}

    for F in (int(m) for m in args.modes.split(",")):
        start = time.perf_counter()
        exp_logits = np.empty((total, 9), dtype=np.float32)
        host_logits = np.empty((total, 9), dtype=np.float32)

        def task(first: int, count: int):
            prefix = output / f"F{F}_chunk_{first:04d}"
            run([str(exe), str(ROOT), str(prefix), str(F), str(first), str(count), str(side)])
            e = np.fromfile(str(prefix) + "_exp_logits_f32.bin", dtype="<f4").reshape(count, 9)
            r = np.fromfile(str(prefix) + "_ref_logits_f32.bin", dtype="<f4").reshape(count, 9)
            return first, count, e, r, Path(str(prefix) + "_stats.txt")

        stat_files = []
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for future in as_completed([pool.submit(task, f, c) for f, c in chunks]):
                first, count, e, r, sf = future.result()
                exp_logits[first:first + count] = e
                host_logits[first:first + count] = r
                stat_files.append(sf)
        if not np.isfinite(exp_logits).all():
            raise AssertionError("non-finite experiment logits")
        stats = merge_stats(stat_files)
        labels = (exp_logits.argmax(axis=1) + 1).astype(np.uint8)
        host_labels = (host_logits.argmax(axis=1) + 1).astype(np.uint8)
        d_pc = np.abs(exp_logits.astype(np.float64) - ref_logits).max(axis=1)
        d_host = np.abs(exp_logits.astype(np.float64) - host_logits.astype(np.float64)).max(axis=1)
        max_x = [stats[f"max_abs_x_{s}"] for s in range(2 * 12 + 1)]
        mode = {
            "seconds": round(time.perf_counter() - start, 1),
            "label_agreement_vs_pc_fixed": float(np.mean(labels == ref_fixed)),
            "mismatch_pc_fixed_pixels": [[int(i // side), int(i % side)] for i in np.flatnonzero(labels != ref_fixed)],
            "label_agreement_vs_pc_float": float(np.mean(labels == ref_float)),
            "label_agreement_vs_host_float32_path": float(np.mean(labels == host_labels)),
            "host_float32_path_vs_pc_fixed": float(np.mean(host_labels == ref_fixed)),
            "labeled_accuracy": float(np.mean(labels[gt > 0] == gt[gt > 0])),
            "host_labeled_accuracy": float(np.mean(host_labels[gt > 0] == gt[gt > 0])),
            "max_dlogit_vs_pc_fixed": float(d_pc.max()),
            "pixels_dlogit_vs_pc_ge_0p01": int((d_pc >= 1e-2).sum()),
            "max_dlogit_vs_host_float32_path": float(d_host.max()),
            "max_abs_x_after_embed": max_x[0],
            "max_abs_x_overall": max(max_x),
            "max_abs_x_per_layer_after_mlp_residual": [max_x[2 * l + 2] for l in range(12)],
            "int16_saturated_elements": int(stats["saturated"]),
            "normalize_calls": int(stats["calls"]),
            "q_elements_compared": int(stats["elements"]),
            "q_flips_pm1_vs_float_normalize": int(stats["flips1"]),
            "q_flips_gt1_vs_float_normalize": int(stats["flips_gt1"]),
            "q_flip_rate": stats["flips1"] / stats["elements"],
            "bits_abs_s1_q24": math.log2(stats["max_abs_s1_q24"]),
            "bits_var_num_q48": math.log2(stats["max_var_num_q48"]),
            "bits_abs_mean_q24": math.log2(max(stats["max_abs_mean_q24"], 1)),
            "bits_abs_d_q24": math.log2(stats["max_abs_d_q24"]),
            "inv_range": [stats["min_inv"], stats["max_inv"]],
        }
        report["modes"][f"F{F}"] = mode
        exp_logits.tofile(output / f"F{F}_exp_logits_f32.bin")
        labels.tofile(output / f"F{F}_labels_u8.bin")
        print(f"=== F={F} ({'int16 Q3.12 x' if F == 12 else 'float x, Q8.24 PL view'}) ===")
        print(json.dumps(mode, indent=2), flush=True)
    host_logits.astype("<f4").tofile(output / "host_float32_logits_f32.bin")
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"report: {output / 'report.json'}")


if __name__ == "__main__":
    main()
