"""Build one serial-switchable PS-only / PS+PL ELF using an existing Vitis BSP.

Run from the repository root:
    D:/pytorch/python.exe tools/build_board_benchmarks.py
    D:/pytorch/python.exe tools/build_board_benchmarks.py --source-dir board/vitis/tsamapp/src --check-only
No platform rebuild, application-project modification or board programming.
Migrated from TT_HSI_FPGA as the 7020 (Cortex-A9, aarch32) build: the --toolchain/--bsp/--linker-script defaults
and the hard-coded -mcpu=cortex-a9 flags must change for ZU5EV (aarch64, Cortex-A53); see PLAN section 17 C2.
"""
import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
SOURCE_NAMES = ('tt_net.cpp', 'tt_data.c', 'tt_hw_sim.cpp', 'tt_hw_xil.cpp', 'tt_hw_switch.cpp',
                'tt_block_app.cpp', 'tt_block_render.cpp', 'tt_block_data.c')
HEADER_NAMES = ('tt_net.h', 'tt_data.h', 'tt_hw.h', 'tt_hw_switch.h', 'tt_ref_int.h',
                'tt_block_app.h', 'tt_block_render.h', 'tt_block_data.h')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--toolchain', type=Path, default=Path(
        'D:/xilinx/Vitis/2020.2/gnu/aarch32/nt/gcc-arm-none-eabi/bin'))
    parser.add_argument('--bsp', type=Path, default=ROOT / 'board/vitis/tsam/export/tsam/sw/tsam/standalone_domain')
    parser.add_argument('--linker-script', type=Path, default=ROOT / 'board/vitis/tsamapp/src/lscript.ld')
    parser.add_argument('--runs', type=int, default=10)
    parser.add_argument('--source-dir', type=Path, help='compile this source directory, including its main_benchmark.cpp')
    parser.add_argument('--output-dir', type=Path, help='build output directory (default: build/board[/source project])')
    parser.add_argument('--check-only', action='store_true', help='check required inputs and synchronized source hashes without compiling')
    args = parser.parse_args()
    if not 1 <= args.runs <= 1000:
        parser.error('--runs must be between 1 and 1000')
    compiler = args.toolchain.resolve() / 'arm-none-eabi-g++.exe'
    size_tool = args.toolchain.resolve() / 'arm-none-eabi-size.exe'
    include = args.bsp.resolve() / 'bspinclude/include'
    library = args.bsp.resolve() / 'bsplib/lib'
    linker = args.linker_script.resolve()
    source_dir = args.source_dir.resolve() if args.source_dir else ROOT / 'src/ps'
    main_source = source_dir / 'main_benchmark.cpp' if args.source_dir else ROOT / 'src/ps/main_benchmark.cpp'
    sources = [main_source] + [source_dir / name for name in SOURCE_NAMES]
    headers = [source_dir / name for name in HEADER_NAMES]
    specs = linker.with_name('Xilinx.spec')
    required = [compiler, size_tool, linker, specs, library / 'libxil.a',
                include / 'xparameters.h', include / 'xtucker_proj.h', *sources, *headers]
    for path in required:
        if not path.is_file():
            parser.error(f'required file not found: {path}')
    # The assembler reads this file independently of the C include paths. Hash
    # the actual .incbin target, including when compiling synchronized sources.
    block_source = (source_dir / 'tt_block_data.c').read_text(encoding='utf-8')
    match = re.search(r'\.incbin \\"([^"]+)\\"', block_source)
    if not match:
        parser.error('tt_block_data.c has no valid .incbin path; regenerate with model/export_block.py --c-only')
    region = Path(match.group(1))
    region = (ROOT / region).resolve() if not region.is_absolute() else region.resolve()
    if not region.is_file() or region.stat().st_size != 70 * 70 * 270 * 4:
        parser.error(f'missing or invalid 64 x 64 block region: {region}')
    files = [*sources, *headers, region, linker, specs, library / 'libxil.a',
             include / 'xparameters.h', include / 'xtucker_proj.h']
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    sync_mismatches = []
    if args.source_dir:
        for source in [*sources, *headers]:
            canonical = ROOT / 'src/ps/main_benchmark.cpp' if source == main_source else ROOT / 'src/ps' / source.name
            if not canonical.is_file() or before[str(source)] != hashlib.sha256(canonical.read_bytes()).hexdigest():
                sync_mismatches.append(source.name)
    if args.check_only:
        if sync_mismatches:
            parser.error('sources differ from canonical repository files: ' + ', '.join(sync_mismatches))
        print(f'PASS: {len(files)} inputs checked; source directory={source_dir}')
        print(f'region_f32.bin: {region.stat().st_size} bytes; SHA256={before[str(region)]}')
        if args.source_dir:
            print('PASS: synchronized main, sources and headers match repository SHA256 hashes')
        return
    output = args.output_dir.resolve() if args.output_dir else ROOT / 'build/board'
    if args.source_dir and not args.output_dir:
        output = output / source_dir.parent.name
    output.mkdir(parents=True, exist_ok=True)
    arch = ['-mcpu=cortex-a9', '-mfpu=vfpv3', '-mfloat-abi=hard']
    common = [str(compiler), *arch, '-O2', '-std=c++11', '-ffp-contract=off', '-Wall', '-DTT_HW_RUNTIME_SWITCH',
              f'-DTT_BENCH_RUNS={args.runs}',
              '-I' + str(source_dir), '-I' + str(include)]
    with (output / 'build.log').open('w', encoding='utf-8') as log:
        def run(command):
            result = subprocess.run(command, cwd=ROOT, text=True, encoding='utf-8', errors='replace',
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            log.write(subprocess.list2cmdline([str(v) for v in command]) + '\n' + result.stdout + '\n')
            log.flush()
            if result.returncode:
                print(result.stdout)
                raise SystemExit(result.returncode)
            return result.stdout.strip()

        compiler_version = run([str(compiler), '--version']).splitlines()[0]
        objects = []
        for source in sources:
            print(f'Compiling {source.name}...', flush=True)
            obj = output / (source.stem + '.o')
            run([*common, '-c', str(source), '-o', str(obj)])
            objects.append(str(obj))
        elf = output / 'tt_bench_switch.elf'
        # 把库作为一组直接交给链接器，避免 g++ 把 -lc/-lm 移到组外导致 BSP syscall 未解析。
        run([str(compiler), *arch, '-Wl,-build-id=none', '-specs=' + str(specs),
             '-Wl,-T', '-Wl,' + str(linker), '-L' + str(library),
             '-Wl,-Map,' + str(output / 'tt_bench_switch.map'), '-o', str(elf), *objects,
             '-Wl,--start-group,-lxil,-lgcc,-lc,-lm,-lstdc++,--end-group'])
        print(run([str(size_tool), str(elf)]))
    after = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    if before != after:
        raise SystemExit('Inputs changed while building; rerun before comparing these ELFs.')
    report = dict(built_at_utc=datetime.now(timezone.utc).isoformat(), compiler=compiler_version,
                  options=common[1:], runs=args.runs, warmup=1, source_sha256=before,
                  source_directory=str(source_dir), main_source=str(main_source),
                  canonical_source_mismatches=sync_mismatches,
                  data_header=(source_dir / 'tt_data.h').read_text(encoding='utf-8'),
                  block_data_header=(source_dir / 'tt_block_data.h').read_text(encoding='utf-8'),
                  elf_sha256={elf.name: hashlib.sha256(elf.read_bytes()).hexdigest()},
                  board_execution='not performed; build only')
    (output / 'build_manifest.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(f'ELF and build metadata: {output}')


if __name__ == '__main__':
    main()
