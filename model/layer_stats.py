"""逐层参数量与乘加数（MAC）统计，作为讲解文档和 PL/PS 分工决策的依据。

参数量：直接从 checkpoint 的 state_dict 数出来（不是公式）。
乘加数：按 docs/TT_EXPLAINED.md 1.3 节的公式解析计算（一个投影 = 模1 + 模2 + 模3）。
两者各自与整体核对：参数总数 vs sum(p.numel())，MAC 总数 vs 审计脚本的闭式公式。
不计入：normalize / softmax / 残差加法 / 量化反量化 等逐元素操作（单独列一列，不算 MAC）。

用法：D:\\pytorch\\python.exe model\\layer_stats.py [--model unoverlapping|overlapping]
输出：屏幕表格 + model/data/layer_stats_<model>.md
"""
import argparse
import os
import sys

import tt_model

sys.stdout.reconfigure(encoding='utf-8', errors='replace')   # Windows 控制台默认 GBK，打印 ² 会崩

# N=6 的 PL 周期数来自 RTL cosim（docs 2.3.7），其他 N 没有实测，不填
COSIM_CYCLES = {6: {'qkv': 155335, 'mlp': 62435}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--model', default='unoverlapping', choices=list(tt_model.MODELS))
    args = ap.parse_args()
    m = tt_model.load(args.model)
    W, J, SEQ, L, C = m.WIN, m.DIM, m.SEQ, m.LAYERS, m.CLASSES
    N, D = SEQ + 1, W * W * J
    state = {k: v.numel() for k, v in m.state_dict().items()}

    mode_macs = (D * W, D * W, D * J)          # 模 1 / 模 2 / 模 3，一个 token 一个投影
    proj_macs = sum(mode_macs)                  # 179928
    pl_layer = 4 * N * proj_macs                # Q K V MLP × N 个 token
    attn_layer = 2 * D * N * N                  # QᵀK + AV
    elem_layer = 2 * 3 * D * N + 2 * D * N + 2 * D * N + 4 * D * N   # normalize×2(三趟) 残差×2 quant×2 dequant×4

    rows = []   # (名称, 参数量, PL MAC, PS MAC, 逐元素操作, 备注)
    rows.append(('embed（cls + pos）', state['encoder.cls_token'] + state['encoder.pos_embed'], 0, 0, D * N,
                 f'cls {D} + pos {D * N}；只有加法'))
    for i in range(L):
        prefix = f'encoder.encoders.{i}.'
        p = sum(n for k, n in state.items() if k.startswith(prefix))
        rows.append((f'TEL {i}', p, pl_layer, attn_layer, elem_layer,
                     f'4 投影 × {N} token × {proj_macs}；注意力 2×{D}×{N}²'))
    cls_p = state['classifier.0.weight'] + state['classifier.0.bias']
    rows.append(('分类头', cls_p, 0, D * C, C, f'{C}×{D} 权重 + {C} 偏置'))

    tot_p = sum(r[1] for r in rows)
    tot_pl, tot_ps, tot_e = (sum(r[i] for r in rows) for i in (2, 3, 4))
    tot_mac = tot_pl + tot_ps

    # 核对
    assert tot_p == sum(v for v in state.values()), (tot_p, sum(state.values()))
    audit = L * (4 * sum(mode_macs) * N + 2 * D * N * N) + D * C     # 与上游 analysis/audit_model.py::counts 同式
    assert tot_mac == audit, (tot_mac, audit)

    lines = [f'# 逐层参数量与乘加数 —— {args.model}（N={N}，D={D}，{L} 层）', '',
             '参数量从 checkpoint 数出，MAC 按 1.3 节公式；逐元素操作（归一化、残差、量化）不算 MAC。', '',
             '| 层 | 参数量 | PL 乘加（模积） | PS 乘加（注意力/分类头） | 逐元素操作 | 占总乘加 | 说明 |',
             '|---|---:|---:|---:|---:|---:|---|']
    for name, p, pl, ps, e, note in rows:
        lines.append(f'| {name} | {p:,} | {pl:,} | {ps:,} | {e:,} | {(pl + ps) / tot_mac:.2%} | {note} |')
    lines.append(f'| **合计** | **{tot_p:,}** | **{tot_pl:,}** | **{tot_ps:,}** | **{tot_e:,}** | 100% | |')
    lines += ['',
              f'- 一个投影一个 token：模 1 {mode_macs[0]:,} + 模 2 {mode_macs[1]:,} + 模 3 {mode_macs[2]:,} = {proj_macs:,}，模 3 占 {mode_macs[2] / proj_macs:.1%}',
              f'- PL（模积）占 {tot_pl / tot_mac:.2%}，PS（注意力 + 分类头）占 {tot_ps / tot_mac:.2%}；注意力单层 {attn_layer:,} 占 {attn_layer / tot_mac:.2%}，{L} 层合计 {L * attn_layer / tot_mac:.2%}',
              f'- 参数 int16 共 {tot_p * 2 / 1024:.0f} KB；一层激活 {D * N} 个元素，int16 {D * N * 2 / 1024:.2f} KB']
    if N in COSIM_CYCLES:
        c = COSIM_CYCLES[N]
        lines.append(f'- N={N} 的 PL 拍数（cosim）：QKV {c["qkv"]:,} + MLP {c["mlp"]:,} = {c["qkv"] + c["mlp"]:,} 拍/层，'
                     f'{L} 层 {L * (c["qkv"] + c["mlp"]):,} 拍 = {L * (c["qkv"] + c["mlp"]) / 1e5:.1f} ms @100 MHz')
    text = '\n'.join(lines) + '\n'
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', f'layer_stats_{args.model}.md')
    with open(out, 'w', encoding='utf-8') as f:
        f.write(text)
    print(text)
    print('written', out)


if __name__ == '__main__':
    main()
