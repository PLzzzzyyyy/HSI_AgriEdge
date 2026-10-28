"""Syntax-check changed PS sources with the existing reviewed A53 BSP."""
import json
import shlex
import subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
commands=json.loads(Path('D:/FPGA.GAME/dpfix/gcs_parcel_temp_mirror3/build/compile_commands.json').read_text())
entry=next(c for c in commands if Path(c['file']).name=='main.cpp')
args=shlex.split(entry['command'],posix=False)
args=args[:args.index('-o')]
args=[v for v in args if v not in ('-MMD','-MP')]
args+=['-fsyntax-only','-I'+str(ROOT/'src/ps/s2c_roi_app')]
for name in ('main.cpp','roi_protocol.cpp','roi_display.cpp','roi_canvas.cpp'):
    result=subprocess.run(args+[str(ROOT/'src/ps/s2c_roi_app'/name)],cwd=entry['directory'],capture_output=True)
    (ROOT/'.runtime-tmp'/('keys_target_'+name+'.log')).write_bytes(result.stdout+result.stderr)
    print(name,result.returncode)
    if result.returncode:print((result.stdout+result.stderr).decode(errors='replace')[-3000:]);raise SystemExit(1)
print('KEYS_TARGET_SYNTAX_PASS (existing BSP only, not new hardware acceptance)')
