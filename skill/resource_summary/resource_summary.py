"""资源与时序汇总：从 Vivado / Vitis HLS 报告抽 LUT / FF / BRAM / URAM / DSP、时序与 HLS latency，出 Markdown 表与 CSV。

用法见同目录 README.md。只用 Python 标准库。报告按文件内容识别（看 Command 行与标题），不看文件名：
  Vivado report_utilization（整板 / OOC；UltraScale+ 与 7 系列；综合、布局、布线）
  Vivado report_timing_summary
  Vitis HLS <top>_csynth.rpt（详细报告）；csynth.rpt 若是 2020.2 的汇总表，改读同目录 <top>_csynth.rpt
  Vitis HLS export_design -flow syn / impl 的 <top>_export.rpt：与同阶段 Vivado 报告交叉核对，缺 Vivado 报告时当数据源
BRAM 口径：Vivado 的 Block RAM Tile 是 36 Kb 块（RAMB18 记 0.5），HLS 的 BRAM_18K 与 export.rpt 的 BRAM 是 18 Kb 块。
表里 BRAM36 列按 36 Kb 块，比值按 18 Kb 块算。
"""
import argparse
import csv
import os
import re
import sys

STAGE_NAME = {'hls': 'HLS 估计', 'synth': 'Vivado 综合', 'impl': 'Vivado 实现', 'unknown': 'Vivado（阶段未知）'}
STAGE_ORDER = {'hls': 0, 'synth': 1, 'impl': 2, 'unknown': 3}
RES = ('lut', 'ff', 'bram18', 'uram', 'dsp')
RES_NAME = {'lut': 'LUT', 'ff': 'FF', 'bram18': 'BRAM18', 'uram': 'URAM', 'dsp': 'DSP'}
SKIP_DIRS = {'sim', 'csim', 'ip', 'hdl', 'drivers', 'doc', 'db', 'debug', 'misc'}


class ParseError(Exception):
    pass


def read(path, limit=None):
    with open(path, encoding='utf-8', errors='replace') as f:
        return f.read(limit) if limit else f.read()


def num(s):
    if s is None:
        return None
    m = re.match(r'^\s*([-+]?\d+(?:\.\d+)?)', s.replace(',', ''))
    return float(m.group(1)) if m else None


def cells(line):
    return [c.strip() for c in line.strip().strip('|').split('|')]


def kind_of(head):
    m = re.search(r'^\|\s*Command\s*:\s*(\S+)(.*)$', head, re.M)
    if m:
        if m.group(1) == 'report_utilization':
            return 'util_hier' if '-hierarchical' in m.group(2) else 'util'
        if m.group(1) == 'report_timing_summary':
            return 'timing'
        return None
    if re.search(r"^== (?:Vitis|Vivado) HLS Report for '", head, re.M):
        return 'hls'
    if re.search(r"^== Synthesis Summary Report of '", head, re.M):
        return 'hls_summary'
    if re.search(r'^Implementation tool:', head, re.M) and 'Resource usage ===' in head:
        return 'export'
    return None


def new_rec(label, stage):
    return dict(label=label, stage=stage, detail='', tool=None, device=None, avail={}, rpt_pct={},
                lut=None, lut_logic=None, lut_mem=None, ff=None, bram18=None, uram=None, dsp=None,
                clk_target=None, clk_value=None, clk_kind=None, wns=None, tns=None, whs=None, ths=None, met=None,
                lat_min=None, lat_max=None, ii_min=None, ii_max=None, files=[], notes=[], util_file=None, timing_file=None)


# ---------------- Vivado report_utilization ----------------
UTIL_ROWS = {
    'lut': ('CLB LUTs', 'Slice LUTs'),
    'lut_logic': ('LUT as Logic',),
    'lut_mem': ('LUT as Memory',),
    'ff': ('CLB Registers', 'Slice Registers'),
    'bram36': ('Block RAM Tile',),
    'uram': ('URAM',),
    'dsp': ('DSPs',),
}


def site_rows(text):
    """所有以 Site Type 为表头的表 → {行名: {列名: 值}}；同名行取第一次出现（第 1 节优先于第 2 节）。按表头取列，兼容多一列 Prohibited 的新版本。"""
    rows, cols = {}, None
    for line in text.splitlines():
        if line.startswith('+'):
            continue
        if not line.startswith('|'):
            cols = None
            continue
        c = cells(line)
        if c[0] == 'Site Type':
            cols = c
        elif cols and len(c) == len(cols):
            rows.setdefault(c[0].rstrip('*').strip(), dict(zip(cols, c)))
    return rows


def header_field(text, name):
    m = re.search(r'^\|\s*' + re.escape(name) + r'\s*:\s*(.*?)\s*$', text, re.M)
    return m.group(1) if m else None


def parse_util(text):
    rows = site_rows(text)
    out = dict(avail={}, rpt_pct={}, notes=[])
    for key, names in UTIL_ROWS.items():
        out[key] = None
        for n in names:
            if n in rows:
                r = rows[n]
                out[key] = num(r.get('Used'))
                out['avail'][key] = num(r.get('Available'))
                out['rpt_pct'][key] = num(r.get('Util%'))
                break
    if out['lut'] is None and out['ff'] is None and out['dsp'] is None:
        raise ParseError('不认识的利用率报告：找不到 CLB/Slice LUTs、Registers、DSPs 行')
    seven = 'Slice LUTs' in rows
    for key, what in (('lut', 'CLB/Slice LUTs 行'), ('ff', 'CLB/Slice Registers 行'), ('bram36', 'Block RAM Tile 行'), ('dsp', 'DSPs 行'), ('uram', 'URAM 行')):
        if out[key] is None and not (key == 'uram' and seven):
            out['notes'].append(f'缺少 {what}，记 n/a')
    if out['bram36'] is not None:
        out['bram18'] = out['bram36'] * 2
        if out['avail'].get('bram36'):
            out['avail']['bram18'] = out['avail']['bram36'] * 2
    else:
        out['bram18'] = None
    state = (header_field(text, 'Design State') or '').lower()
    out['state'] = state
    out['stage'] = 'synth' if state.startswith('synth') else ('impl' if ('placed' in state or 'routed' in state) else None)
    out['detail'] = '布线' if 'routed' in state else ('布局后利用率' if 'placed' in state else '')
    m = re.search(r'^\d+\. Black Boxes\s*\n-+\s*\n(.*?)(?=^\d+\. |\Z)', text, re.S | re.M)
    bb = len(re.findall(r'^\|\s*(?!Ref Name)\S[^|]*\|\s*\d+\s*\|', m.group(1), re.M)) if m else 0
    if bb:
        out['detail'] = '，'.join(x for x in (out['detail'], f'含 {bb} 个黑盒') if x)
        out['notes'].append(f'网表里有 {bb} 个黑盒（多为单独 OOC 综合的 IP），本报告不含它们的资源；整体资源看实现阶段报告')
    out['tool'] = header_field(text, 'Tool Version')
    out['device'] = header_field(text, 'Device')
    for key in ('lut', 'ff', 'bram36', 'uram', 'dsp'):
        u, a, p = out.get(key), out['avail'].get(key), out['rpt_pct'].get(key)
        if u is not None and a and p is not None and abs(u / a * 100 - p) > 0.011:
            out['notes'].append(f'{key} 占用率与报告的 Util% 不符（{u}/{a} vs {p}%），可能是列没对齐')
    return out


# ---------------- Vivado report_timing_summary ----------------
def parse_timing(text):
    lines = text.splitlines()
    out = dict(notes=[])
    vals = None
    for i, ln in enumerate(lines):
        if re.match(r'^\s*WNS\(ns\)\s+TNS\(ns\)', ln):
            for ln2 in lines[i + 1:i + 6]:
                if re.match(r'^\s*[-+]?(\d|inf)', ln2):
                    vals = ln2.split()
                    break
            break
    if not vals:
        raise ParseError('找不到 Design Timing Summary 的 WNS 行（报告被截断或不是 report_timing_summary）')
    out['wns'], out['tns'], out['whs'], out['ths'] = num(vals[0]), num(vals[1]), num(vals[4]) if len(vals) > 4 else None, num(vals[5]) if len(vals) > 5 else None
    periods = {}
    for i, ln in enumerate(lines):
        if re.match(r'^Clock\s+Waveform\(ns\)\s+Period\(ns\)', ln):
            for ln2 in lines[i + 2:]:
                m = re.match(r'^\s*(\S+)\s+\{[^}]*\}\s+([\d.]+)', ln2)
                if not m:
                    break
                periods[m.group(1)] = float(m.group(2))
            break
    worst = None
    for i, ln in enumerate(lines):
        if re.match(r'^Clock\s+WNS\(ns\)\s+TNS\(ns\)', ln):
            for ln2 in lines[i + 2:]:
                if not ln2.strip():
                    break
                m = re.match(r'^\s*(\S+)\s+([-+]?\d+\.\d+)\s', ln2)
                if m and (worst is None or float(m.group(2)) < worst[1]):
                    worst = (m.group(1), float(m.group(2)))
            break
    if worst and worst[0] in periods:
        out['clk_target'] = periods[worst[0]]
        out['clk_value'] = round(periods[worst[0]] - worst[1], 3)
        out['clock'] = worst[0]
    elif len(periods) == 1:
        out['clk_target'] = next(iter(periods.values()))
        out['clk_value'] = round(out['clk_target'] - out['wns'], 3) if out['wns'] is not None else None
        out['clock'] = next(iter(periods))
    else:
        out['notes'].append('找不到 WNS 所在时钟的周期，达成周期记 n/a')
    if 'All user specified timing constraints are met' in text:
        out['met'] = True
    elif 'Timing constraints are not met' in text:
        out['met'] = False
    else:
        out['met'] = None
    out['tool'] = header_field(text, 'Tool Version')
    out['device'] = header_field(text, 'Device')
    return out


# ---------------- Vitis / Vivado HLS csynth ----------------
HLS_COLS = {'BRAM_18K': 'bram18', 'DSP': 'dsp', 'DSP48E': 'dsp', 'DSP48': 'dsp', 'FF': 'ff', 'LUT': 'lut', 'URAM': 'uram'}


def section(text, start, ends):
    i = text.find(start)
    if i < 0:
        return ''
    j = min([k for k in (text.find(e, i + len(start)) for e in ends) if k > 0] or [len(text)])
    return text[i:j]


def parse_hls(text):
    """<top>_csynth.rpt（Vitis HLS 2020.2 / Vivado HLS 的详细报告）。"""
    out = dict(notes=[], avail={}, rpt_pct={})
    m = re.search(r"^== (?:Vitis|Vivado) HLS Report for '([^']+)'", text, re.M)
    out['top'] = m.group(1)
    for key, pat in (('tool', r'^\*\s*Version:\s*(.+?)\s*$'), ('project', r'^\*\s*Project:\s*(\S+)'), ('device', r'^\*\s*Target device:\s*(\S+)')):
        m = re.search(pat, text, re.M)
        out[key] = m.group(1) if m else None
    tm = section(text, '+ Timing:', ('+ Latency:', '\n=='))
    m = re.search(r'^\s*\|\s*[\w.]+\s*\|\s*([\d.]+)\s*(?:ns)?\s*\|\s*([\d.]+)\s*(?:ns)?\s*\|\s*([\d.]+)\s*(?:ns)?\s*\|', tm, re.M)
    if m:
        out['clk_target'], out['clk_value'] = float(m.group(1)), float(m.group(2))
    else:
        out['clk_target'] = out['clk_value'] = None
        out['notes'].append('缺少 Timing 节')
    lat = section(text, '+ Latency:', ('+ Detail:', '\n=='))
    out['lat_min'] = out['lat_max'] = out['ii_min'] = out['ii_max'] = None
    for ln in lat.splitlines():
        if ln.strip().startswith('|'):
            c = cells(ln)
            if len(c) >= 6 and re.match(r'^(\d+|\?|-)$', c[0]):
                out['lat_min'], out['lat_max'], out['ii_min'], out['ii_max'] = num(c[0]), num(c[1]), num(c[4]), num(c[5])
                break
    ut = section(text, '== Utilization Estimates', ('+ Detail:', '\n== Interface'))
    cols, rows = None, {}
    for ln in ut.splitlines():
        if not ln.startswith('|'):
            continue
        c = cells(ln)
        if c[0] == 'Name':
            cols = c
        elif cols and len(c) == len(cols):
            rows[c[0]] = dict(zip(cols, c))
    if 'Total' not in rows:
        raise ParseError('HLS 报告缺少 Utilization Estimates 的 Total 行')
    for col, key in HLS_COLS.items():
        if col in rows['Total']:
            out[key] = num(rows['Total'][col])
            if 'Available' in rows:
                out['avail'][key] = num(rows['Available'][col])
            if 'Utilization (%)' in rows:
                out['rpt_pct'][key] = num(rows['Utilization (%)'][col])
    for key in RES:
        out.setdefault(key, None)
    return out


def parse_hls_summary(text, path):
    """2020.2 的 csynth.rpt 汇总表：同目录有 <top>_csynth.rpt 就读它；没有就只取汇总表顶层行（无时钟估计）。"""
    top = re.search(r"Synthesis Summary Report of '([^']+)'", text).group(1)
    detail = os.path.join(os.path.dirname(path), top + '_csynth.rpt')
    if os.path.isfile(detail):
        out = parse_hls(read(detail))
        out['path'] = detail
        return out
    out = dict(notes=['同目录没有 ' + top + '_csynth.rpt，只用汇总表顶层行（无时钟估计与器件总量）'], avail={}, rpt_pct={}, top=top,
               clk_target=None, clk_value=None, lat_min=None, lat_max=None, ii_min=None, ii_max=None)
    for key, pat in (('tool', r'^\s*\*\s*Version:\s*(.+?)\s*$'), ('project', r'^\s*\*\s*Project:\s*(\S+)'), ('device', r'^\s*\*\s*Target device:\s*(\S+)')):
        m = re.search(pat, text, re.M)
        out[key] = m.group(1) if m else None
    cols = None
    for ln in text.splitlines():
        s = ln.strip()
        if not s.startswith('|'):
            continue
        c = cells(s)
        if '& Loops' in c[0]:
            cols = c
        elif cols and s.startswith('|+ ') and len(c) == len(cols):
            for i, name in enumerate(cols):
                key = {'BRAM': 'bram18', 'DSP': 'dsp', 'FF': 'ff', 'LUT': 'lut', 'URAM': 'uram'}.get(name)
                if key:
                    out[key] = num(c[i])
                    m = re.search(r'\(([\d.]+)%\)', c[i])
                    out['rpt_pct'][key] = float(m.group(1)) if m else None
                elif name == '(cycles)':
                    out['lat_min'] = out['lat_max'] = num(c[i])
                elif name == 'Interval':
                    out['ii_min'] = out['ii_max'] = num(c[i])
            break
    if cols is None or all(out.get(k) is None for k in RES):
        raise ParseError('csynth.rpt 汇总表里找不到顶层行')
    for key in RES:
        out.setdefault(key, None)
    return out


# ---------------- HLS export_design 报告 ----------------
def parse_export(text):
    out = dict(notes=[], blocks={})
    for key, pat in (('project', r'^Project:\s*(\S+)'), ('device', r'^Device target:\s*(\S+)'), ('tool', r'^Implementation tool:\s*(.+?)\s*$')):
        m = re.search(pat, text, re.M)
        out[key] = m.group(1) if m else None
    for m in re.finditer(r'#=== Post-(Synthesis|Implementation) Resource usage ===\s*\n(.*?)(?=\n#===|\Z)', text, re.S):
        kv = {k.upper(): float(v) for k, v in re.findall(r'^(\w+):\s*([\d.]+)', m.group(2), re.M)}
        out['blocks']['synth' if m.group(1) == 'Synthesis' else 'impl'] = dict(
            lut=kv.get('LUT'), ff=kv.get('FF'), dsp=kv.get('DSP'), bram18=kv.get('BRAM'), uram=kv.get('URAM'))
    out['cp_required'] = num((re.search(r'^CP required:\s*(\S+)', text, re.M) or [None, None])[1])
    out['cp'] = {st: num((re.search(r'^CP achieved post-' + word + r':\s*(\S+)', text, re.M) or [None, None])[1])
                 for st, word in (('synth', 'synthesis'), ('impl', 'implementation'))}
    out['met'] = True if re.search(r'^Timing met', text, re.M) else (False if re.search(r'^Timing not met', text, re.M) else None)
    if not out['blocks']:
        raise ParseError('export.rpt 里找不到 Resource usage 块')
    return out


# ---------------- 发现、命名与合并 ----------------
def discover(root):
    """目录下找报告：*.runs 只进 synth_N / impl_N（跳过 IP 的 OOC 子运行）；HLS 导出工程的 project.runs 跳过（黑盒 wrapper），
    用 impl/verilog/report；HLS 的 syn/report 只取 csynth.rpt（再由它找顶层 <top>_csynth.rpt）。"""
    out = []
    for dp, dns, fns in os.walk(root):
        base = os.path.basename(dp)
        if base.endswith('.runs'):
            dns[:] = [d for d in dns if re.match(r'^(synth|impl)_\d+$', d)]
        elif base in ('verilog', 'vhdl') and 'report' in dns:
            dns[:] = [d for d in dns if not d.endswith('.runs') and not d.startswith('.')]
        else:
            dns[:] = [d for d in dns if not d.startswith('.') and d not in SKIP_DIRS]
        rpts = sorted(f for f in fns if f.endswith('.rpt'))
        if base == 'report' and 'csynth.rpt' in rpts:
            out.append(os.path.join(dp, 'csynth.rpt'))
            continue
        out += [os.path.join(dp, f) for f in rpts]
    return out


def auto_label(path, kind, parsed):
    if kind in ('hls', 'hls_summary', 'export') and parsed.get('project'):
        return parsed['project']
    parts = os.path.normpath(os.path.abspath(path)).split(os.sep)
    for i in range(len(parts) - 1, 1, -1):
        if parts[i] == 'impl' and i + 1 < len(parts) and parts[i + 1] in ('verilog', 'vhdl', 'report'):
            return parts[i - 2]
    for p in reversed(parts):
        if p.endswith('.runs'):
            return p[:-5]
    stem = os.path.splitext(os.path.basename(path))[0]
    return re.sub(r'_(utilization|util|timing)(_.*)?$', '', stem) or stem


def stage_from_name(fn):
    stem = os.path.splitext(fn)[0]
    if re.search(r'(^|_)synth(_|$)', stem):
        return 'synth'
    if re.search(r'(^|_)(routed|placed|impl|opted|postroute)(_|$)', stem):
        return 'impl'
    return None


def collect(inputs, labels):
    """返回 (records, 核对与提示, 错误数)。records 按 (label, stage) 合并利用率 + 时序。"""
    recs, msgs, errors, pend_timing, exports = {}, [], 0, [], []

    def rec(label, stage):
        return recs.setdefault((label, stage), new_rec(label, stage))

    for i, p in enumerate(inputs):
        forced = labels[i] if i < len(labels) else None
        if not os.path.exists(p):
            print(f'错误：路径不存在：{p}', file=sys.stderr)
            errors += 1
            continue
        files = discover(p) if os.path.isdir(p) else [p]
        used, errors0 = 0, errors
        for f in files:
            try:
                kind = kind_of(read(f, 16384))
                if kind is None:
                    if not os.path.isdir(p):
                        raise ParseError('不认识的报告格式（不是 report_utilization / report_timing_summary / csynth / export 报告）')
                    continue
                if kind == 'util_hier':
                    msgs.append(f'跳过分层利用率报告（不支持）：{f}')
                    continue
                text = read(f)
                if kind == 'util':
                    d = parse_util(text)
                    stage = d['stage'] or stage_from_name(os.path.basename(f)) or 'unknown'
                    r = rec(forced or auto_label(f, kind, d), stage)
                    if r['util_file'] and not ('布线' in d['detail'] and '布线' not in r['detail']):
                        msgs.append(f'{r["label"]} {STAGE_NAME[stage]}：已有 {r["util_file"]}，忽略 {f}')
                        continue
                    for k in ('lut', 'lut_logic', 'lut_mem', 'ff', 'bram18', 'uram', 'dsp'):
                        r[k] = d[k]
                    r['avail'].update({k: v for k, v in d['avail'].items() if k != 'bram36'})
                    r.update(detail=d['detail'], tool=d['tool'] or r['tool'], device=d['device'] or r['device'], util_file=f)
                    r['notes'] += [f'{os.path.basename(f)}：{n}' for n in d['notes']]
                elif kind == 'timing':
                    d = parse_timing(text)
                    d['file'] = f
                    d['label'] = forced or auto_label(f, kind, d)
                    d['stage'] = stage_from_name(os.path.basename(f))
                    pend_timing.append(d)
                elif kind in ('hls', 'hls_summary'):
                    d = parse_hls(text) if kind == 'hls' else parse_hls_summary(text, f)
                    r = rec(forced or auto_label(f, kind, d), 'hls')
                    for k in ('lut', 'ff', 'bram18', 'uram', 'dsp', 'clk_target', 'clk_value', 'lat_min', 'lat_max', 'ii_min', 'ii_max'):
                        r[k] = d.get(k)
                    r['avail'].update(d['avail'])
                    r.update(clk_kind='估计', tool=d['tool'], device=d['device'], util_file=d.get('path', f))
                    r['notes'] += [f'{os.path.basename(f)}：{n}' for n in d['notes']]
                elif kind == 'export':
                    d = parse_export(text)
                    d['file'] = f
                    d['label'] = forced or auto_label(f, kind, d)
                    exports.append(d)
                used += 1
            except ParseError as e:
                print(f'错误：{f}：{e}', file=sys.stderr)
                errors += 1
        if used == 0 and errors == errors0:
            print(f'错误：{p} 里没有可识别的报告', file=sys.stderr)
            errors += 1

    for d in pend_timing:
        stage = d['stage']
        if stage is None:
            cand = [s for (lb, s) in recs if lb == d['label'] and s != 'hls']
            stage = cand[0] if len(cand) == 1 else 'unknown'
        r = rec(d['label'], stage)
        if r['timing_file']:
            better = 'routed' in os.path.basename(d['file']) and 'routed' not in os.path.basename(r['timing_file'])
            if not better:
                msgs.append(f'{r["label"]} {STAGE_NAME[stage]}：已有 {r["timing_file"]}，忽略 {d["file"]}')
                continue
        for k in ('wns', 'tns', 'whs', 'ths', 'met', 'clk_target', 'clk_value'):
            r[k] = d.get(k)
        r.update(clk_kind='达成', timing_file=d['file'], tool=r['tool'] or d['tool'], device=r['device'] or d['device'])
        r['notes'] += [f'{os.path.basename(d["file"])}：{n}' for n in d['notes']]

    for d in exports:
        for stage, b in d['blocks'].items():
            r = recs.get((d['label'], stage))
            if r is None or r['util_file'] is None:
                r = rec(d['label'], stage)
                r.update({k: b[k] for k in ('lut', 'ff', 'dsp', 'bram18', 'uram')})
                r.update(util_file=d['file'], tool=d['tool'], device=d['device'])
                r['notes'].append('资源来自 export.rpt（BRAM 为 18 Kb 块数）')
            else:
                bad = [f'{RES_NAME[k]} export {b[k]:g} vs 报告 {r[k]:g}' for k in RES
                       if b.get(k) is not None and r.get(k) is not None and abs(b[k] - r[k]) > 1e-6]
                msgs.append(f'{d["label"]} {STAGE_NAME[stage]}：export.rpt 与利用率报告' + ('不一致：' + '；'.join(bad) if bad else '一致'))
        for stage, cp in d['cp'].items():
            if cp is None:
                continue
            r = recs.get((d['label'], stage))
            if r is not None and r['timing_file']:
                ok = r['clk_value'] is not None and abs(r['clk_value'] - cp) < 0.0015
                msgs.append(f'{d["label"]} {STAGE_NAME[stage]}：export.rpt 达成周期 {cp:.3f} ns，时序报告 周期 − WNS = '
                            + (f'{r["clk_value"]:.3f} ns，' if r['clk_value'] is not None else 'n/a，') + ('一致' if ok else '不一致'))
            elif r is not None:
                r.update(clk_target=d['cp_required'], clk_value=cp, clk_kind='达成', met=d['met'])
                r['notes'].append('时序来自 export.rpt（CP achieved）')
            else:
                r = rec(d['label'], stage)
                r.update(clk_target=d['cp_required'], clk_value=cp, clk_kind='达成', met=d['met'], util_file=d['file'])
    for r in recs.values():
        r['files'] = [f for f in (r['util_file'], r['timing_file']) if f]
    return recs, msgs, errors


# ---------------- 输出 ----------------
def fnum(v, nd=0):
    if v is None:
        return '—'
    if nd:
        return f'{v:,.{nd}f}'
    return f'{int(v):,}' if float(v).is_integer() else f'{v:,.2f}'.rstrip('0').rstrip('.')


def pct(r, k):
    u, a = r.get(k), r['avail'].get(k)
    return u / a * 100 if u is not None and a else None


def cell(r, k):
    u = r.get(k)
    s = fnum(u / 2 if k == 'bram18' and u is not None else u)
    p = pct(r, k)
    return s + (f' ({p:.1f}%)' if p is not None else '')


def fsign(v):
    return '—' if v is None else f'{v:+.3f}'


def rng(a, b):
    if a is None and b is None:
        return '—'
    return fnum(a) if a == b or b is None else f'{fnum(a)}～{fnum(b)}'


def stage_text(r):
    return STAGE_NAME[r['stage']] + (f'（{r["detail"]}）' if r['detail'] else '')


def render_md(recs, msgs):
    rs = sorted(recs.values(), key=lambda r: (r['label'], STAGE_ORDER[r['stage']]))
    L = ['## 资源与时序汇总', '',
         '数字来自工具报告（HLS 估计 / Vivado 综合 / Vivado 实现），不是板上测量。BRAM36 = 36 Kb 块（HLS 的 BRAM_18K ÷ 2）。', '',
         '| 设计 | 来源 | LUT | 其中 LUTRAM+SRL | FF | BRAM36 | URAM | DSP | 时钟 ns（目标 / 估计或达成） | WNS / WHS ns | Latency / II（拍） |',
         '|---|---|---|---|---|---|---|---|---|---|---|']
    for r in rs:
        clk = '—' if r['clk_target'] is None and r['clk_value'] is None else \
            f'{fnum(r["clk_target"], 3)} / {fnum(r["clk_value"], 3)}（{r["clk_kind"] or ""}）'
        lat = '—' if r['stage'] != 'hls' else f'{rng(r["lat_min"], r["lat_max"])} / {rng(r["ii_min"], r["ii_max"])}'
        L.append(f'| {r["label"]} | {stage_text(r)} | {cell(r, "lut")} | {fnum(r["lut_mem"])} | {cell(r, "ff")} | {cell(r, "bram18")} | '
                 f'{cell(r, "uram")} | {cell(r, "dsp")} | {clk} | {fsign(r["wns"])} / {fsign(r["whs"])} | {lat} |')
    cmp_rows = []
    for label in sorted({r['label'] for r in rs}):
        h = recs.get((label, 'hls'))
        vs = [recs[(label, s)] for s in ('synth', 'impl') if (label, s) in recs]
        if not h or not vs:
            continue
        for k in RES:
            row = [label if k == 'lut' else '', RES_NAME[k], fnum(h.get(k))]
            for s in ('synth', 'impl'):
                v = recs.get((label, s))
                if v is None:
                    row += ['—', '—']
                    continue
                ratio = v[k] / h[k] if v.get(k) is not None and h.get(k) else None
                row += [fnum(v.get(k)), '—' if ratio is None else f'{ratio:.2f}']
            cmp_rows.append('| ' + ' | '.join(row) + ' |')
    if cmp_rows:
        L += ['', '## HLS 估计 vs Vivado（比值 = Vivado / HLS；BRAM 按 18 Kb 块）', '',
              '| 设计 | 资源 | HLS 估计 | Vivado 综合 | 综合 / HLS | Vivado 实现 | 实现 / HLS |', '|---|---|---|---|---|---|---|'] + cmp_rows
    notes = msgs + [f'{r["label"]} {stage_text(r)}：{n}' for r in rs for n in r['notes']]
    if notes:
        L += ['', '## 核对与提示', ''] + [f'- {n}' for n in notes]
    L += ['', '## 来源文件', ''] + [f'- {r["label"]} {stage_text(r)}：' + '；'.join(r['files']) for r in rs]
    return '\n'.join(L) + '\n'


CSV_COLS = ['label', 'stage', 'detail', 'tool', 'device', 'lut', 'lut_pct', 'lut_logic', 'lut_mem', 'ff', 'ff_pct',
            'bram36', 'bram18', 'bram_pct', 'uram', 'uram_pct', 'dsp', 'dsp_pct', 'clk_target_ns', 'clk_ns', 'clk_kind',
            'wns_ns', 'tns_ns', 'whs_ns', 'ths_ns', 'timing_met', 'lat_min', 'lat_max', 'ii_min', 'ii_max', 'files', 'notes']


def write_csv(recs, path):
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(CSV_COLS)
        for r in sorted(recs.values(), key=lambda r: (r['label'], STAGE_ORDER[r['stage']])):
            def p(k):
                v = pct(r, k)
                return '' if v is None else f'{v:.2f}'
            b = r['bram18']
            row = [r['label'], r['stage'], r['detail'], r['tool'] or '', r['device'] or '',
                   r['lut'], p('lut'), r['lut_logic'], r['lut_mem'], r['ff'], p('ff'),
                   None if b is None else b / 2, b, p('bram18'), r['uram'], p('uram'), r['dsp'], p('dsp'),
                   r['clk_target'], r['clk_value'], r['clk_kind'], r['wns'], r['tns'], r['whs'], r['ths'], r['met'],
                   r['lat_min'], r['lat_max'], r['ii_min'], r['ii_max'], ' ; '.join(r['files']), ' ; '.join(r['notes'])]
            w.writerow(['' if v is None else (int(v) if isinstance(v, float) and v.is_integer() else v) for v in row])


def main(argv=None):
    ap = argparse.ArgumentParser(description='从 Vivado / Vitis HLS 报告出资源与时序汇总表（Markdown / CSV）')
    ap.add_argument('inputs', nargs='+', help='报告文件或目录（目录下自动发现）')
    ap.add_argument('--label', action='append', default=[], help='按顺序给每个输入指定设计名；同名的输入并成同一个设计（HLS 与 Vivado 对照）')
    ap.add_argument('--md', help='Markdown 输出文件；不给则打印到标准输出')
    ap.add_argument('--csv', help='CSV 输出文件（UTF-8 带 BOM，Excel 可直接打开）')
    a = ap.parse_args(argv)
    recs, msgs, errors = collect(a.inputs, a.label)
    if not recs:
        print('错误：没有解析出任何结果', file=sys.stderr)
        return 1
    md = render_md(recs, msgs)
    if a.md:
        with open(a.md, 'w', encoding='utf-8') as f:
            f.write(md)
    else:
        sys.stdout.reconfigure(errors='replace')
        sys.stdout.write(md)
    if a.csv:
        write_csv(recs, a.csv)
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
