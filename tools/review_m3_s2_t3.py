"""Reconcile finished G2 evidence. Never launch synthesis or grant RTL/board PASS."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from audit_m3_s2_synth import audit
from run_m3_s2_synth import ROOT, continuation_blockers, scheduler_report, scheduler_summary


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def memory_rows(text):
    section = text.split('* Memory:', 1)[1].split('* FIFO:', 1)[0]
    rows = []
    keys = ('bram18', 'ff', 'lut', 'uram', 'words', 'bits', 'banks', 'storage_bits')
    for line in section.splitlines():
        c = [v.strip() for v in line.strip().strip('|').split('|')]
        if len(c) == 10 and c[0] != 'Total' and all(v.isdigit() for v in c[2:]):
            row = dict(name=c[0], module=c[1], **dict(zip(keys, map(int, c[2:]))))
            assert row['words'] * row['bits'] * row['banks'] == row['storage_bits']
            rows.append(row)
    assert rows, 'No recognized memory rows; do not infer zero banks'
    return rows


MEMORY_GROUPS = ('mem_ob', 'mem_xb', 'mem_wm12', 'mem_wm3', 'mem_head',
                 'projection_t1', 'projection_t2')


def group_memories(memories, required=MEMORY_GROUPS):
    """Keep ownership explicit; missing/duplicated worker storage is not PASS."""
    groups = {}
    for group in required:
        members = [r for r in memories if re.match(r'^(?:w_)?' + group + '_', r['name'])]
        assert members, 'No recognized banks for ' + group
        owners = sorted({r.get('owner', 'legacy') for r in members})
        assert len(owners) == 1, group + ' has multiple owners: ' + repr(owners)
        groups[group] = dict(instances=len(members), owners=owners,
            **{k: sum(r[k] for r in members) for k in ('banks', 'bram18', 'uram', 'storage_bits')},
            shapes=dict(Counter('%sx%sx%s' % (r['words'], r['bits'], r['banks']) for r in members)),
            rows=members)
    return groups


def memory_inventory(report_dir):
    rows = []
    for report in sorted(report_dir.glob('*_csynth.rpt')):
        text = report.read_text(encoding='utf-8')
        if '* Memory:' not in text:
            continue
        section = text.split('* Memory:', 1)[1].split('* FIFO:', 1)[0].strip()
        if section in ('N/A', ''):
            continue  # no local allocation here; required groups checked below
        for row in memory_rows(text):
            rows.append(dict(row, owner=report.name.replace('_csynth.rpt', '')))
    return rows


def named_loop_report(report_dir, label):
    owners = []
    for report in report_dir.glob('*_csynth.xml'):
        c = ET.parse(report).find('.//SummaryOfLoopLatency')
        for loop in [] if c is None else c.iter():
            if loop.tag == label or loop.tag.endswith('_' + label):
                owners.append((report, dict(name=loop.tag,
                    pipeline_ii=loop.findtext('PipelineII'), pipeline_depth=loop.findtext('PipelineDepth'),
                    iteration_latency=loop.findtext('IterationLatency'),
                    iteration_min=loop.findtext('IterationLatency/range/min'),
                    iteration_max=loop.findtext('IterationLatency/range/max'))))
    assert len(owners) == 1, label + ' owner not uniquely identified'
    return owners[0]


def schedule_evidence(path):
    lines = path.read_text(encoding='utf-8').splitlines()
    needles = ('mem_ob_V_0_0', 'mem_ob_0_0', 'jobs_active_1',
               'jobs_i_V_0_flag_4_i', 'br_ln164', 'returned_value',
               'slots_mean_0_load', 'w_projection_tag2_V',
               '"%w_active_load =', '"%w_active_write_ln237 =',
               'w_projection_tok3_V_loc_4_i', 'project_loop', 'srem', 'Divider')
    return dict(path=path.relative_to(ROOT).as_posix(), sha256=sha(path),
        bytes=path.stat().st_size, total_lines=len(lines),
        srem_lines=sum('srem' in line for line in lines),
        divider_lines=sum('Divider' in line for line in lines),
        excerpts=[dict(line=i, text=line) for i, line in enumerate(lines, 1)
                  if any(k in line for k in needles)])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tag', required=True)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    run = ROOT / 'build/host' / ('m3_s2_synth_' + args.tag)
    assert json.loads((run / 'running.json').read_text()).get('finished')
    results = json.loads((run / 'results.json').read_text())
    assert len(results) == 1, 'Review each isolated P1/P2 run separately'
    args.out.mkdir(parents=True, exist_ok=False)
    reviews = []
    for row in results:
        assert row['synthesis_completed'], 'No final synthesis report to review'
        build = ROOT / 'build/hls/optimization_build' / row['name']
        log = ROOT / row['log']
        assert sha(log) == row['log_sha256']
        for name, digest in row['snapshot'].items():
            assert sha(build / 'snapshot' / name) == digest, name
        text = log.read_text(encoding='utf-8', errors='replace')
        top = build / 'sol/syn/report/s2_engine_csynth.xml'
        sched, tree = scheduler_report(top)
        assert sched is not None
        blockers = continuation_blockers(ET.parse(top), text, tree)
        assert blockers == row['continuation_blockers']
        assert scheduler_summary(tree) == row['scheduler']
        report = sched.with_suffix('.rpt')
        memories = memory_inventory(top.parent)
        groups = group_memories(memories)
        project = None
        worker_source = build / 'snapshot/src/hls/m3_s2/s2_worker.h'
        if worker_source.exists():
            project_xml, project = named_loop_report(top.parent, 'project_loop')
            assert project_xml != sched, 'PROJECT not independently outlined'
            project['report'] = project_xml.relative_to(ROOT).as_posix()
            project['sha256'] = sha(project_xml)
            # Geometry/port/compute sharing still require actual RTL review.
            assert groups['mem_ob']['owners'] != groups['mem_head']['owners']
        warnings = [dict(line=i, text=line) for i, line in enumerate(text.splitlines(), 1)
            if 'WARNING:' in line and any(k in line for k in ('schedule_loop', 'project_loop', 'mem_ob', 'jobs_', 'returned.value'))]
        diagnostic = build / 'sol/.autopilot/db' / (sched.name.replace('_csynth.xml', '') + '.verbose.sched.rpt')
        schedule = schedule_evidence(diagnostic)
        worker_schedules = {}
        if project:
            owners = {owner for g in groups.values() for owner in g['owners']}
            owners.add(project_xml.name.replace('_csynth.xml', ''))
            owners.update(p.name.replace('_csynth.xml', '') for p in top.parent.glob('*read_ob*_csynth.xml'))
            for owner in sorted(owners):
                path = build / 'sol/.autopilot/db' / (owner + '.verbose.sched.rpt')
                assert path.exists(), 'Missing worker/RAM-owner schedule: ' + owner
                worker_schedules[owner] = schedule_evidence(path)
        rtl_dir = build / 'sol/syn/verilog'
        modules = sorted({r['module'] for g in groups.values() for r in g['rows']})
        rtl = {}
        for module in modules:
            matches = [p for p in rtl_dir.glob('*.v')
                if p.name == module + '.v' or p.name.endswith('_' + module + '.v')]
            assert len(matches) == 1, 'Missing or ambiguous RAM RTL: ' + module
            p = matches[0]
            dest = args.out / 'ram_rtl' / p.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(p.read_bytes())
            rtl[module] = dict(path=p.relative_to(ROOT).as_posix(), sha256=sha(p))
        reviews.append(dict(name=row['name'], synthesis_completed=True,
            g2_status='FAIL' if blockers else 'MANUAL_REVIEW_REQUIRED',
            scope='HLS screen only; never RTL/200MHz/system/board PASS',
            blockers=blockers, scheduler=row['scheduler'], resources=row['hls_resources'],
            clock_ns=row['hls_clock_ns'], memory_groups=groups, memory_inventory=memories,
            project=project, warnings=warnings,
            schedule_evidence=schedule, worker_schedules=worker_schedules,
            expression_audit=audit(report), ram_rtl=rtl,
            inputs={p.relative_to(ROOT).as_posix(): sha(p) for p in
                [log, *sorted(top.parent.glob('*_csynth.xml')), *sorted(top.parent.glob('*_csynth.rpt'))]}))
    result = dict(schema=2, run=args.tag, reviews=reviews, reviewer_sha256=sha(Path(__file__)),
        notes=['Counts are HLS memory instances, not post-route primitives.',
               'Inline compute sharing and absence of all hidden copies require manual review.',
               'Transient warnings do not replace the final schedule_loop II.'])
    (args.out / 'review.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps([dict(name=r['name'], g2_status=r['g2_status'], blockers=r['blockers'],
                          scheduler=r['scheduler']) for r in reviews], indent=2))


if __name__ == '__main__':
    main()
