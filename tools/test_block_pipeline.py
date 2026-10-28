"""Compile and validate block inference on the host (never board measurements).

Runs two genuinely different patches with delayed PL stubs, covers synthetic
N=10 token inputs, compares patch extraction to the NumPy preprocessing path,
then checks sequential/pair equality and compares all 4096 host predictions
with the existing PC fixed-point and all-float references.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "model"))
from preprocess import patch_tensor


def run(command: list[str]) -> str:
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}): {command}\n{result.stdout}\n{result.stderr}")
    return result.stdout


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", default="D:/mingw64/bin/g++.exe")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--smoke-only", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "build" / "host" / "block_pipeline_host")
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    executable = output / "test_block_pipeline.exe"
    sources = [ROOT / "sim" / "host" / "test_block_pipeline.cpp", ROOT / "src" / "ps" / "tt_net.cpp",
               ROOT / "src" / "ps" / "tt_hw_sim.cpp"]
    print(run([args.compiler, "-O2", "-std=c++11", "-ffp-contract=off", "-DTT_HW_RUNTIME_SWITCH",
               *map(str, sources), "-o", str(executable)]), end="", flush=True)
    print(run([str(executable), "--smoke", str(ROOT), str(output / "smoke")]), end="", flush=True)
    block = ROOT / "model" / "data" / "block"
    meta = dict(line.split("=", 1) for line in (block / "meta.txt").read_text().splitlines() if "=" in line)
    size = int(meta["size"])
    if size != 64 or meta["model"] != "unoverlapping":
        raise ValueError("This host regression requires the exported 64x64 unoverlapping block")
    region = np.fromfile(block / "region_f32.bin", dtype="<f4").reshape(size + 6, size + 6, 270)
    coords = [(0, 0), (0, 63), (63, 0), (63, 63), (32, 32), (5, 7), (17, 51), (47, 9), (31, 32)]
    actual_patches = np.fromfile(output / "smoke_patches_f32.bin", dtype="<f4").reshape(len(coords), 270, 7, 7)
    expected_patches = np.stack([patch_tensor(region, row, col) for row, col in coords])
    patch_error = float(np.max(np.abs(actual_patches.astype(np.float64) - expected_patches)))
    np.testing.assert_allclose(actual_patches, expected_patches, rtol=2e-6, atol=2e-6)
    print(f"PASS host patch extraction vs independent NumPy preprocessing: {len(coords)} windows, max_abs={patch_error:.9g}", flush=True)
    report = {"source": "host simulation; delayed PL stub uses integer software projections; NOT board measurements",
              "model": meta["model"], "size": size, "origin": [int(meta["row0"]), int(meta["col0"])],
              "patch_windows": len(coords), "patch_max_abs_error_vs_numpy": patch_error,
              "N6_real_pair_bitwise_equal": True, "N10_synthetic_pair_bitwise_equal": True,
              "source_sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}}
    if args.smoke_only:
        (output / "host_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        return

    start = time.perf_counter()
    total = size * size
    chunks = [(first, min(128, total - first)) for first in range(0, total, 128)]
    host_logits = np.empty((total, 9), dtype=np.float32)

    def task(first: int, count: int):
        prefix = output / f"chunk_{first:04d}"
        stdout = run([str(executable), "--block", str(ROOT), str(prefix), str(first), str(count), str(size)])
        values = np.fromfile(str(prefix) + "_host_logits_f32.bin", dtype="<f4").reshape(count, 9)
        return first, count, values, stdout

    completed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(task, first, count) for first, count in chunks]
        for future in as_completed(futures):
            first, count, values, stdout = future.result()
            host_logits[first:first + count] = values
            completed += count
            print(f"Host sequential + pair validated: {completed}/{total} ({time.perf_counter() - start:.1f}s)", flush=True)
    if not np.isfinite(host_logits).all():
        raise AssertionError("non-finite host block logits")
    labels = (host_logits.argmax(axis=1) + 1).astype(np.uint8)
    ref_logits = np.fromfile(block / "ref_fixed_logits.bin", dtype="<f8").reshape(total, 9)
    ref_fixed = np.fromfile(block / "ref_fixed_u8.bin", dtype=np.uint8)
    ref_float = np.fromfile(block / "ref_float_u8.bin", dtype=np.uint8)
    gt = np.fromfile(block / "gt_u8.bin", dtype=np.uint8)
    difference = np.abs(host_logits.astype(np.float64) - ref_logits)
    per_pixel_error = difference.max(axis=1)
    mismatch_fixed = np.flatnonzero(labels != ref_fixed)
    mismatch_float = np.flatnonzero(labels != ref_float)
    worst = int(per_pixel_error.argmax())
    report.update({"host_seconds": time.perf_counter() - start, "pixels": total,
                   "all_sequential_vs_pair_logits_and_final_activations_bitwise_equal": True,
                   "deferred_projection_calls_per_pair": 48,
                   "max_logit_abs_error_vs_pc_fixed": float(difference.max()),
                   "worst_error_local_pixel": [worst // size, worst % size],
                   "pixels_exceeding_single_patch_0p01_tolerance": int((per_pixel_error >= 1e-2).sum()),
                   "label_agreement_vs_pc_fixed": float(np.mean(labels == ref_fixed)),
                   "label_agreement_vs_pc_float": float(np.mean(labels == ref_float)),
                   "host_labeled_accuracy": float(np.mean(labels[gt > 0] == gt[gt > 0])),
                   "mismatch_fixed_local_pixels": [[int(i // size), int(i % size)] for i in mismatch_fixed],
                   "mismatch_float_local_pixels": [[int(i // size), int(i % size)] for i in mismatch_float]})
    host_logits.astype("<f4").tofile(output / "host_logits_f32.bin")
    labels.tofile(output / "host_labels_u8.bin")
    (output / "host_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    print(f"PASS host pipeline validation; outputs: {output}", flush=True)


if __name__ == "__main__":
    main()
