"""Check a source bundle and compile its five apps with EXISTING matching BSPs.

No XSCT, IDE, platform generation, hardware connection or download is performed.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
from datetime import datetime
from prepare_vitis_sources import ROOT, APPS, sha

def verify(bundle: Path, out: Path, vitis: Path) -> None:
    if out.exists(): raise FileExistsError(f"Refusing to overwrite {out}")
    data = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    for entry in data["files"]:
        p = (bundle / entry["path"]).resolve()
        if not p.is_relative_to(bundle) or not p.is_file(): raise ValueError(f"Invalid bundle path: {p}")
        if p.stat().st_size != entry["bytes"] or sha(p) != entry["sha256"]:
            raise ValueError(f"Bundle changed: {p}")
        if entry.get("source"):
            source = (ROOT / entry["source"]).resolve()
            if not source.is_relative_to(ROOT) or sha(source) != entry["source_sha256"]:
                raise ValueError(f"Source changed since packaging: {source}")
            if entry["transform"] == "incbin-relative":
                expected = source.read_text(encoding="utf-8").replace(
                    "D:/HSI_AgriEdge/model/data/block/region_f32.bin", "../src/region_f32.bin")
                if p.read_text(encoding="utf-8") != expected: raise ValueError(f"Unexpected source transform: {p}")
            elif p.read_bytes() != source.read_bytes(): raise ValueError(f"Copy mismatch: {p}")
    if set(data["apps"]) != set(APPS): raise ValueError("Expected exactly the five intended apps")
    out.mkdir(parents=True)
    ccdir = vitis / "gnu/aarch64/nt/aarch64-none/bin"
    results = []
    for app, cfg in data["apps"].items():
        if app == "c3":
            ws, plat, original = ROOT / "build/board/periph_formal_20260928", "periph_plat", "periph_zu5ev"
        elif app.startswith("m2"):
            ws, plat, original = ROOT / "build/vivado/chk_m2_zu5ev", "chk_plat", "tt_m2_zu5ev"
        else:
            ws, plat, original = ROOT / "build/vivado/chk_zu5ev", "chk_plat", "tt_bench_zu5ev"
        exported = ws / plat / "export" / plat
        bsp = exported / "sw" / plat / "standalone_domain"
        hardware = list((exported / "hw").glob("*.xsa"))
        bundle_xsa = bundle / APPS[app][0] / cfg["xsa"]
        if len(hardware) != 1 or sha(hardware[0]) != sha(bundle_xsa):
            raise ValueError(f"BSP/XSA mismatch for {app}: {hardware}")
        ld = ws / original / "src/lscript.ld"
        for p in [ld, bsp / "bsplib/lib/libxil.a", ccdir / "aarch64-none-elf-gcc.exe"]:
            if not p.is_file(): raise FileNotFoundError(p)
        work = out / app
        shutil.copytree(bundle / cfg["directory"] / "src", work / "src")
        release = work / "Release"
        release.mkdir()
        logfile = work / "build.log"
        def run(cmd: list[str]) -> str:
            cmd = [str(x) for x in cmd]
            p = subprocess.run(cmd, cwd=release, capture_output=True)
            text = (p.stdout + p.stderr).decode("utf-8", errors="replace")
            with logfile.open("a", encoding="utf-8") as f:
                f.write(subprocess.list2cmdline(cmd) + "\n" + text + "\n")
            if p.returncode: raise RuntimeError(f"{app}: command failed ({p.returncode}); see {logfile}\n{text}")
            return text
        objects = []
        for src in sorted((work / "src").iterdir()):
            if src.suffix not in (".c", ".cpp"): continue
            compiler = "g++" if src.suffix == ".cpp" else "gcc"
            obj = release / (src.stem + ".o")
            run([ccdir / f"aarch64-none-elf-{compiler}.exe", *cfg["compiler_flags"],
                 *("-D" + x for x in cfg["defines"]), "-I" + str(bsp / "bspinclude/include"),
                 "-c", src, "-o", obj])
            objects.append(obj)
        elf = release / (app + ".elf")
        libraries = ["xil", "gcc", "c", *cfg["extra_libraries"]]
        if cfg["language"] == "c++": libraries.append("stdc++")
        linker = "gcc" if cfg["language"] == "c" else "g++"
        run([ccdir / f"aarch64-none-elf-{linker}.exe", "-Wl,-T," + str(ld), "-L" + str(bsp / "bsplib/lib"),
             "-Wl,-Map," + str(release / (app + ".map")), "-o", elf, *objects,
             "-Wl,--start-group," + ",".join("-l" + x for x in libraries) + ",--end-group"])
        buildlog = logfile.read_text(encoding="utf-8")
        if re.search(r"warning:", buildlog, re.I): raise RuntimeError(f"Application warning in {logfile}")
        header = run([ccdir / "aarch64-none-elf-readelf.exe", "-h", "-lW", elf])
        if "AArch64" not in header: raise ValueError("Wrong ELF architecture")
        for line in header.splitlines():
            fields = line.split()
            if fields and fields[0] == "LOAD":
                address, size = int(fields[2], 16), int(fields[5], 16)
                if address + size > 0x7FF00000: raise ValueError("ELF segment outside the selected low DDR")
        if app == "phy_id":
            symbols = run([ccdir / "aarch64-none-elf-nm.exe", "--defined-only", elf])
            if re.search(r"\b(lwip_init|xemac_add|XEmacPs_PhyWrite|XEmacPs_PhyRead)\b", symbols):
                raise ValueError("PHY diagnostic unexpectedly links a network/unsafe polling implementation")
        files = [elf, logfile, ld, bsp / "bsplib/lib/libxil.a", hardware[0]]
        for lib in cfg["extra_libraries"]:
            local = bsp / "bsplib/lib" / ("lib" + lib + ".a")
            if local.exists(): files.append(local)
        result = dict(app=app, status="cross-build-pass; no new platform or board validation", source_units=len(objects),
                      files=[dict(path=str(p), bytes=p.stat().st_size, sha256=sha(p)) for p in files])
        results.append(result)
        (out / "results.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
        print(f"PASS {app}: {len(objects)} source units, zero application warnings, matching BSP/XSA, AArch64 low DDR", flush=True)
    print(f"VERIFY PASS: {len(data['files'])} bundle entries; all {len(results)} apps; results: {out}")

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("bundle", type=Path)
    p.add_argument("--out", type=Path, default=ROOT / "build/board" / datetime.now().strftime("vitis_sources_verify_%Y%m%d_%H%M%S"))
    p.add_argument("--vitis", type=Path, default=Path("D:/xilinx/Vitis/2020.2"))
    args = p.parse_args()
    verify(args.bundle.resolve(), args.out.resolve(), args.vitis.resolve())
