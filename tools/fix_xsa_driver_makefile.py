#!/usr/bin/env python3
"""把 XSA 里 HLS 驱动 Makefile 的 `TAB + #echo` 行删掉，让 Vitis 在 Windows 上直接能建平台。

背景见 tools/fix_hls_driver_makefile.py：HLS 导出的驱动 Makefile 把 `#echo ...` 写在 recipe 行里，
Vitis 在 Windows 下用 CMD 当 shell，会把 `#echo` 当程序执行而失败。Vivado 的 write_hw_platform 把
IP 仓里的 drivers/ 原样打进 XSA，用户 Update Hardware Specification 时又原样解出来，所以坑会复现。
XSA 就是一个 zip（xsa.json / sysdef.xml 里没有任何文件校验和），直接改 zip 里的 Makefile 即可。

用法：python tools/fix_xsa_driver_makefile.py <xsa> [<xsa> ...]
    原文件备份为 <xsa>.orig（已存在则不覆盖），改完后校验：其他条目字节不变、zip 可完整读取。
"""
import re
import shutil
import sys
import zipfile
from pathlib import Path

RECIPE_COMMENT = re.compile(r'^\t\s*#')


def fix_xsa(path: Path) -> int:
    with zipfile.ZipFile(path) as z:
        entries = [(info, z.read(info.filename)) for info in z.infolist()]
    fixed, removed = [], 0
    for info, data in entries:
        if info.filename.lower().endswith('makefile') and '/drivers/' in ('/' + info.filename):
            lines = data.decode('utf-8', 'replace').splitlines(keepends=True)
            kept = [l for l in lines if not RECIPE_COMMENT.match(l)]
            removed += len(lines) - len(kept)
            data = ''.join(kept).encode('utf-8')
        fixed.append((info, data))
    if removed == 0:
        print(f'{path}: nothing to fix')
        return 0
    backup = path.with_suffix(path.suffix + '.orig')
    if not backup.exists():
        shutil.copy2(path, backup)
    tmp = path.with_suffix(path.suffix + '.tmp')
    with zipfile.ZipFile(tmp, 'w') as out:
        for info, data in fixed:
            new = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            new.compress_type = info.compress_type
            new.external_attr = info.external_attr
            out.writestr(new, data)
    # 校验：可完整读取；除 Makefile 外每个条目逐字节相同
    with zipfile.ZipFile(tmp) as z:
        assert z.testzip() is None, 'rewritten XSA failed zip test'
        for info, data in entries:
            if info.filename.lower().endswith('makefile'):
                assert not any(RECIPE_COMMENT.match(l) for l in z.read(info.filename).decode().splitlines()), 'fix failed'
            else:
                assert z.read(info.filename) == data, f'{info.filename} changed unexpectedly'
    tmp.replace(path)
    print(f'{path}: removed {removed} recipe-comment line(s); original kept at {backup.name}')
    return removed


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for arg in sys.argv[1:]:
        fix_xsa(Path(arg))
