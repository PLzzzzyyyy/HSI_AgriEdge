"""把 model/data 下的权重、参数和一个黄金 patch 生成为 C 数组（src/ps/tt_data.c / tt_data.h），
板上程序直接链接，不需要 SD 卡或 QSPI。约 500 KB 数据 → 约 3 MB 源码，Vitis 编译几十秒。

用法：D:/pytorch/python.exe export_c_arrays.py     （需先跑 export_golden.py）
"""
from pathlib import Path
import numpy as np

DATA = Path(__file__).resolve().parent / 'data'
OUT = Path(__file__).resolve().parents[1] / 'src' / 'ps'


def c_array(f, ctype, name, arr, fmt, per_line=16):
    arr = np.asarray(arr).ravel()
    f.write(f'const {ctype} {name}[{len(arr)}] = {{\n')
    for i in range(0, len(arr), per_line):
        f.write('  ' + ', '.join(fmt % v for v in arr[i:i + per_line]) + ',\n')
    f.write('};\n\n')


def main():
    meta = dict(l.split('=', 1) for l in (DATA / 'golden' / 'meta.txt').read_text().splitlines() if '=' in l)
    N = int(meta['N'])
    D = 2646
    w = np.fromfile(DATA / 'weights_all.bin', dtype='<i2')
    cls = np.fromfile(DATA / 'cls_token.bin', dtype='<f4')
    pos = np.fromfile(DATA / 'pos_embed.bin', dtype='<f4')
    cw = np.fromfile(DATA / 'classifier_w.bin', dtype='<f4')
    cb = np.fromfile(DATA / 'classifier_b.bin', dtype='<f4')
    patch = np.fromfile(DATA / 'golden' / 'patch_f32.bin', dtype='<f4')
    lf = np.fromfile(DATA / 'golden' / 'logits_fixed.bin', dtype='<f8')
    assert len(w) == 12 * 4 * 3014 and len(pos) == D * N and len(patch) == 270 * 49

    with open(OUT / 'tt_data.h', 'w', encoding='utf-8') as f:
        f.write('// 由 model/export_c_arrays.py 生成，勿手改\n#ifndef TT_DATA_H\n#define TT_DATA_H\n#include <stdint.h>\n')
        f.write(f'#define TT_DATA_N {N}\n#define TT_DATA_MODEL "{meta["model"]}"\n')
        f.write(f'#define TT_DATA_PIXEL "{meta["pixel"]}"\n#define TT_DATA_GT {int(meta["gt"])}\n')
        f.write(f'#define TT_DATA_REF_ARGMAX {int(meta["argmax_fixed"])}\n')
        f.write('extern const int16_t tt_weights[];      // [12][4][3014] Q1.14\n')
        f.write('extern const float tt_cls_token[];      // [2646]\n')
        f.write(f'extern const float tt_pos_embed[];      // [2646*{N}]\n')
        f.write('extern const float tt_classifier_w[];   // [9][2646]\nextern const float tt_classifier_b[];   // [9]\n')
        f.write('extern const float tt_patch[];          // [270*7*7] 预处理完成的黄金 patch\n')
        f.write('extern const double tt_ref_logits[];    // [9] PC 定点仿真的参考 logits\n#endif\n')
    with open(OUT / 'tt_data.c', 'w', encoding='utf-8') as f:
        f.write('// 由 model/export_c_arrays.py 生成，勿手改\n#include "tt_data.h"\n')
        f.write('#define AL __attribute__((aligned(32)))\n')
        # 权重会被 PL 直接读，放 32 字节对齐便于 cache 维护
        f.write(f'AL ')
        c_array(f, 'int16_t', 'tt_weights', w, '%d')
        c_array(f, 'float', 'tt_cls_token', cls, '%.9gf')
        c_array(f, 'float', 'tt_pos_embed', pos, '%.9gf')
        c_array(f, 'float', 'tt_classifier_w', cw, '%.9gf')
        c_array(f, 'float', 'tt_classifier_b', cb, '%.9gf')
        c_array(f, 'float', 'tt_patch', patch, '%.9gf')
        c_array(f, 'double', 'tt_ref_logits', lf, '%.17g')
    print('written', OUT / 'tt_data.c', (OUT / 'tt_data.c').stat().st_size // 1024, 'KB; N =', N)


if __name__ == '__main__':
    main()
