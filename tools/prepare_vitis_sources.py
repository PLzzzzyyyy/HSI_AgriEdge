"""Stage XSA-matched source-only imports. Never create a Vitis workspace."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
COMMON = """main_benchmark.cpp tt_net.cpp tt_net.h tt_hw.h tt_hw_sim.cpp
tt_hw_switch.cpp tt_hw_switch.h tt_ref_int.h tt_data.c tt_data.h tt_block_app.cpp
tt_block_app.h tt_block_data.c tt_block_data.h tt_block_render.cpp tt_block_render.h""".split()
APPS = {
    "phy_id": ("tt_zu5ev", "c", [], []),
    "m1": ("tt_zu5ev", "c++", ["TT_HW_RUNTIME_SWITCH"], ["m"]),
    "c3": ("tt_zu5ev", "c++", [], ["xilffs", "lwip4"]),
    "m2": ("tt_m2_zu5ev", "c++", ["TT_HW_RUNTIME_SWITCH"], ["m"]),
    "m2_selfcheck": ("tt_m2_zu5ev", "c++", ["TT_HW_RUNTIME_SWITCH", "TT_ENG_SELFCHECK"], ["m"]),
}

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def source_paths(app: str) -> list[Path]:
    if app in ("phy_id", "c3"):
        sub = "phy_id" if app == "phy_id" else "periph"
        return sorted(p for p in (ROOT / "src/ps" / sub).iterdir() if p.suffix in (".c", ".cpp", ".h"))
    files = [ROOT / "src/ps" / f for f in COMMON]
    if app == "m1":
        files.append(ROOT / "src/ps/tt_hw_xil.cpp")
    else:
        files += [ROOT / "src/ps/tt_hw_engine.cpp", ROOT / "src/ps/tt_hw_engine.h", ROOT / "src/hls/tt_engine_regs.h"]
    files.append(ROOT / "model/data/block/region_f32.bin")
    return files

def settings(app: str) -> dict:
    xsa, lang, defines, libs = APPS[app]
    flags = ["-O2", "-mcpu=cortex-a53", "-Wall", "-Wextra", "-Werror"]
    if app == "phy_id": flags += ["-std=c11"]
    if app in ("m1", "m2", "m2_selfcheck"): flags += ["-ffp-contract=off"]
    return dict(xsa=xsa + ".xsa", language=lang, defines=defines, compiler_flags=flags,
                extra_libraries=libs, processor="psu_cortexa53_0", os="standalone",
                bsp_profile="c3" if app == "c3" else "standalone", stdout="psu_uart_0")

def stage(out: Path) -> None:
    if out.exists(): raise FileExistsError(f"Refusing to overwrite {out}; select a new output directory")
    # Check all inputs before making the output directory.
    inputs = {p for app in APPS for p in source_paths(app)}
    inputs |= {ROOT / "build/vivado" / (x + ".xsa") for x, *_ in APPS.values()}
    inputs.add(ROOT / "board/vitis_sources/README.md")
    for p in inputs:
        if not p.is_file(): raise FileNotFoundError(p)
    out.mkdir(parents=True)
    manifest = {"created": datetime.now().isoformat(timespec="seconds"),
                "status": "source-only imports; no new platform, no board validation",
                "apps": {}, "files": []}
    def copy(src: Path, dest: Path, transform: bool = False) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if transform:
            text = src.read_text(encoding="utf-8")
            # Only adapt the generated copy; Vitis compiles from Debug/Release.
            matches = re.findall(r'D:/HSI_AgriEdge/model/data/block/region_f32\.bin', text)
            if len(matches) != 2: raise ValueError("Unexpected block-data layout; inspect incbin before packaging")
            text = text.replace("D:/HSI_AgriEdge/model/data/block/region_f32.bin", "../src/region_f32.bin")
            dest.write_text(text, encoding="utf-8", newline="\n")
        else:
            shutil.copyfile(src, dest)
        manifest["files"].append(dict(path=dest.relative_to(out).as_posix(), bytes=dest.stat().st_size,
                                      sha256=sha(dest), source=src.relative_to(ROOT).as_posix(),
                                      source_sha256=sha(src), transform="incbin-relative" if transform else None))
    for xsa in sorted({x for x, *_ in APPS.values()}):
        copy(ROOT / "build/vivado" / (xsa + ".xsa"), out / xsa / (xsa + ".xsa"))
    for app, (xsa, *_) in APPS.items():
        folder = out / xsa / app
        for src in source_paths(app):
            copy(src, folder / "src" / src.name, src.name == "tt_block_data.c")
        cfg = settings(app)
        manifest["apps"][app] = dict(directory=folder.relative_to(out).as_posix(), **cfg)
        text = (f"# {app} — 手工创建 Vitis App\n\n"
                f"- XSA：上一级 `{cfg['xsa']}`，处理器 `psu_cortexa53_0`，standalone。\n"
                f"- 模板：Empty Application ({'C' if cfg['language'] == 'c' else 'C++'})。\n"
                "- 只把本目录 `src/` 的**内容**导入新 App 的 `src/`，不要嵌套成 src/src。\n"
                f"- GCC/G++ 编译选项：`{' '.join(cfg['compiler_flags'])}`。\n"
                f"- 预处理 Symbols：`{', '.join(cfg['defines']) or '无'}`（只填宏名，不带 -D）。\n"
                f"- Linker Libraries 额外添加：`{', '.join(cfg['extra_libraries']) or '无'}`（不带 -l；保留默认 xil/gcc/c）。\n"
                "- 链接脚本：保留 Vitis 为该 XSA 自动生成的 lscript.ld；所有段放低地址 psu_ddr_0_MEM_0，低于 4GB。\n"
                "- 完整 BSP 配置、PS 初始化和 Run As 步骤见导入包根目录 README.md。\n")
        if app == "c3": text += "\n**先按根 README 的 C3 配置建专用 Platform/BSP，不可直接套 PHY 的纯 standalone 平台。B 型 PHY 尚未适配，不先跑 u/a。**\n"
        if app in ("m1", "m2", "m2_selfcheck"):
            text += "\n`region_f32.bin` 必须导入 src；已将副本 .incbin 改为 ../src/region_f32.bin。不要只导入 .c/.h。\n"
        if app == "m2_selfcheck": text += "\n只验证逐位一致；自检版计时不是正式性能。\n"
        (folder / "README.md").write_text(text, encoding="utf-8")
        (folder / "settings.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    copy(ROOT / "board/vitis_sources/README.md", out / "README.md")
    # Include all generated instructions/settings in the integrity manifest too.
    recorded = {f["path"] for f in manifest["files"]}
    for p in sorted(out.rglob("*")):
        if p.is_file() and p.relative_to(out).as_posix() not in recorded:
            manifest["files"].append(dict(path=p.relative_to(out).as_posix(), bytes=p.stat().st_size,
                                          sha256=sha(p), source=None, transform="generated-guide"))
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"SOURCE PACKAGE READY: {out}")
    print(f"2 XSA, {len(APPS)} separate apps; no Vitis workspace created")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "build/board" / datetime.now().strftime("vitis_sources_%Y%m%d_%H%M%S"))
    stage(parser.parse_args().out.resolve())
