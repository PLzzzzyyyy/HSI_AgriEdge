"""Agronomy from immutable, received board CLASS words. No inference or I/O to devices."""
import base64
import copy
import csv
import hashlib
import html
import io
import json
import math
import os
from pathlib import Path
import re
import struct
import threading
from datetime import datetime, timezone
import uuid
import zipfile
import zlib

import numpy as np
import analysis
import board_metrics


class BoardResult:
    """Capture under the job lock; all later work uses this detached snapshot."""
    def __init__(self, snapshot, shape, classes):
        s = copy.deepcopy(snapshot)
        self.shape, self.classes = tuple(shape), list(classes)
        if s.get('model_lifecycle'):
            import board_models
            identity=board_models.task_identity(s)
            if list(self.shape)!=identity['shape'] or len(self.classes)!=identity['classes']:raise ValueError('Task/scene contract differs')
        if len(self.shape) != 2 or any(type(v) is not int or v <= 0 for v in self.shape) or not 1 <= len(classes) <= 255:
            raise ValueError('Invalid scene shape/classes')
        if not (s.get('ack') or s.get('accepted_via_info')) or s.get('error') or s.get('integrity_error'):
            raise ValueError('任务未确认或已有错误；保留原始结果，不生成成功统计')
        if s.get('status') not in ('running', 'paused', 'stopped', 'done') or s.get('cells_included') is False:
            raise ValueError('No complete received-cell snapshot')
        for key in ('boot_id', 'session', 'wcrc'):
            if not re.fullmatch(r'[0-9a-fA-F]{8}', str(s.get(key, ''))) or not int(s[key], 16):
                raise ValueError('Invalid board identity: '+key)
        if type(s.get('task')) is not int or not 0 < s['task'] < 65536:
            raise ValueError('Invalid board task identity')
        if not all(isinstance(s.get(k), str) and s[k] for k in ('scene', 'model')):
            raise ValueError('Missing scene/model identity')
        self.identity = {k: s[k] for k in ('boot_id', 'session', 'task', 'wcrc', 'scene', 'model')}
        roi = s['roi'];y, x, h, w = (roi[k] for k in ('y', 'x', 'height', 'width'))
        if (any(type(v) is not int for v in (x, y, w, h)) or not 0 <= y < self.shape[0] or
                not 0 <= x < self.shape[1] or not 0 < h <= self.shape[0]-y or not 0 < w <= self.shape[1]-x or
                type(s.get('total')) is not int or s['total'] != w*h):
            raise ValueError('Invalid task ROI/total')
        self.words = np.zeros(self.shape, dtype='<u4')
        self.seen = np.zeros(self.shape, dtype=bool)
        for cell in s['cells']:
            cy, cx, text = cell['y'], cell['x'], cell['class_word']
            if (type(cy) is not int or type(cx) is not int or not y <= cy < y+h or not x <= cx < x+w or
                    not isinstance(text, str) or not re.fullmatch('[0-9a-fA-F]{8}', text)):
                raise ValueError('Invalid received coordinate/CLASS')
            word = int(text, 16)
            if word & 0xff00 or (word & 255) >= len(classes) or self.seen[cy, cx]:
                raise ValueError('Reserved/invalid/duplicate CLASS word')
            expected = dict(class_id=word & 255, confidence_q16=word >> 16, confidence=(word >> 16)/65536)
            if cell.get('class_id') != expected['class_id'] or any(cell[k] != v for k, v in expected.items() if k in cell):
                raise ValueError('Derived class/confidence differs from raw word')
            self.words[cy, cx], self.seen[cy, cx] = word, True
        self.count = int(self.seen.sum())
        if type(s.get('received_pixels')) is not int or self.count != s['received_pixels']:
            raise ValueError('Received count differs from unique cells')
        if s['status'] == 'done' and self.count != s['total']:
            raise ValueError('Incomplete completed board task')
        self.pred = np.where(self.seen, (self.words & 255)+1, 0).astype('u1')
        self.conf = (self.words >> 16).astype(np.float64)/65536
        counts = np.bincount(self.pred[self.seen], minlength=len(classes)+1)[1:].tolist()
        if 'class_counts' in s and s['class_counts'] != counts:
            raise ValueError('Class histogram differs from received words')
        self.sha256 = hashlib.sha256(self.words.tobytes()+self.seen.astype('u1').tobytes()).hexdigest()
        self.snapshot = s
        for v in (self.words, self.seen, self.pred, self.conf):v.flags.writeable = False

    def summary(self):
        return dict(source='board', identity=self.identity.copy(), task_status=self.snapshot['status'],
                    received_pixels=self.count, total=self.snapshot['total'], coverage=self.count/self.snapshot['total'],
                    complete_task_coverage=self.count == self.snapshot['total'],
                    prediction_words_seen_sha256=self.sha256, roi=self.snapshot['roi'].copy())


def parameters(gsd, conf_thr=.6, min_px=6):
    if isinstance(gsd, bool) or not isinstance(gsd, (int, float)) or not math.isfinite(gsd) or gsd <= 0:
        raise ValueError('GSD must be finite and positive')
    if isinstance(conf_thr, bool) or not isinstance(conf_thr, (int, float)) or not math.isfinite(conf_thr) or not 0 <= conf_thr <= 1:
        raise ValueError('置信阈值必须为 0～1 的有限数')
    if type(min_px) is not int or not 1 <= min_px <= 500:
        raise ValueError('最小斑块必须为 1～500 个像素')


def analyze(result, gsd, conf_thr=.6, min_px=6):
    parameters(gsd, conf_thr, min_px)
    area = []
    for cls, name in enumerate(result.classes, 1):
        mask = result.seen & (result.pred == cls);n = int(mask.sum())
        area.append(dict(class_id=cls-1, name=name, pixels=n, area_m2=n*gsd*gsd,
                         share=n/result.count if result.count else None,
                         mean_conf=float(result.conf[mask].mean()) if n else None))
    return dict(**result.summary(), gsd_m=gsd, conf_thr=conf_thr, min_px=min_px, area=area,
                patches=analysis.patches(result.pred, result.conf, result.seen, gsd, conf_thr, min_px),
                sampling=analysis.sampling(result.conf, result.seen), patch_limit=60,
                scope='RECEIVED_CLASSIFICATION_ONLY_NOT_DISEASE_DIAGNOSIS',
                note='面积 = 已接收像素 × GSD²；未接收不计入类别，待核查不是病害诊断。')


def validate_parcels(parcels, shape):
    if not isinstance(parcels, list) or len(parcels) > 200:raise ValueError('地块数量上限为200')
    result, ids = [], set()
    for p in parcels:
        if not isinstance(p, dict):raise ValueError('Invalid parcel')
        pid, name, pts = p.get('id'), p.get('name'), p.get('pts')
        if not isinstance(pid, str) or not re.fullmatch('[a-zA-Z0-9_-]{1,64}', pid) or pid in ids:
            raise ValueError('地块编号无效或重复')
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80 or any(ord(c) < 32 for c in name):
            raise ValueError('地块名称需为1～80字，无控制字符')
        if not isinstance(pts, list) or not 3 <= len(pts) <= 128:raise ValueError('地块需要3～128个顶点')
        for q in pts:
            if (not isinstance(q, (list, tuple)) or len(q) != 2 or
                    any(type(v) not in (int, float) or not math.isfinite(v) for v in q) or
                    not 0 <= q[0] <= shape[1] or not 0 <= q[1] <= shape[0]):
                raise ValueError('地块顶点超出场景或非有限坐标')
        points = [list(q) for q in pts]
        n = len(points)
        cross = lambda a, b, c: (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
        def on(a, b, c):
            return abs(cross(a, b, c)) < 1e-9 and min(a[0], b[0]) <= c[0] <= max(a[0], b[0]) and min(a[1], b[1]) <= c[1] <= max(a[1], b[1])
        for i in range(n):
            u, v = points[i], points[(i+1) % n]
            if u == v:raise ValueError('地块存在重复相邻顶点')
            for j in range(i+1, n):
                if j == i+1 or (i == 0 and j == n-1):continue
                c, d = points[j], points[(j+1) % n]
                if (cross(u, v, c)*cross(u, v, d) < 0 and cross(c, d, u)*cross(c, d, v) < 0 or
                        on(u, v, c) or on(u, v, d) or on(c, d, u) or on(c, d, v)):
                    raise ValueError('地块不能自相交或自接触')
        if abs(sum(points[i][0]*points[(i+1) % n][1]-points[(i+1) % n][0]*points[i][1] for i in range(n))) < 1e-9:
            raise ValueError('地块面积为零')
        result.append(dict(id=pid, name=name.strip(), pts=points));ids.add(pid)
    return result


def polygon_mask(pts, shape):
    xs, ys = zip(*pts)
    x0, x1 = max(0, math.floor(min(xs))), min(shape[1], math.ceil(max(xs)))
    y0, y1 = max(0, math.floor(min(ys))), min(shape[0], math.ceil(max(ys)))
    yy, xx = np.mgrid[y0:y1, x0:x1];xx = xx+.5;yy = yy+.5
    inside = np.zeros(xx.shape, bool)
    for (xi, yi), (xj, yj) in zip(pts, pts[1:]+pts[:1]):
        if yi != yj:inside ^= ((yi > yy) != (yj > yy)) & (xx < (xj-xi)*(yy-yi)/(yj-yi)+xi)
    return (slice(y0, y1), slice(x0, x1)), inside


def parcel_rows(result, parcels, gsd, conf_thr=.6):
    parameters(gsd, conf_thr)
    rows = []
    for p in validate_parcels(parcels, result.shape):
        box, mask = polygon_mask(p['pts'], result.shape)
        received = mask & result.seen[box];n, done = int(mask.sum()), int(received.sum())
        counts = np.bincount(result.pred[box][received], minlength=len(result.classes)+1)[1:]
        main = int(counts.argmax()) if done else None
        rows.append(dict(id=p['id'], name=p['name'], pixels=n, area_m2=n*gsd*gsd,
                         received_pixels=done, received_area_m2=done*gsd*gsd, done=done/n if n else 0,
                         class_counts=counts.tolist(), main=result.classes[main] if done else None, main_c=main+1 if done else 0,
                         low_pixels=int((result.conf[box][received] < conf_thr).sum()),
                         main_share=float(counts[main]/done) if done else None,
                         mix=float(1-counts[main]/done) if done else None,
                         low=float((result.conf[box][received] < conf_thr).mean()) if done else None))
    return rows


class RevisionConflict(ValueError):
    pass


class ParcelStore:
    """Atomic, scene-scoped geometry with optimistic revision checks across tabs."""
    def __init__(self, root):
        self.root, self.lock = Path(root), threading.RLock()

    def load(self, scene, shape):
        if scene not in ('longkou', 'honghu', 'hanchuan'):raise ValueError('Unknown ledger scene')
        with self.lock:
            path = self.root/(scene+'.json')
            if not path.exists():return dict(scene=scene, shape=list(shape), revision=0, parcels=[], updated=None)
            doc = json.loads(path.read_text(encoding='utf-8'))
            if doc.get('scene') != scene or doc.get('shape') != list(shape) or type(doc.get('revision')) is not int or doc['revision'] < 1:
                raise ValueError('台账场景/形状/版本不匹配；保留文件，不自动覆盖')
            doc['parcels'] = validate_parcels(doc['parcels'], shape)
            return doc

    def save(self, scene, shape, parcels, revision):
        with self.lock:
            old = self.load(scene, shape)
            if type(revision) is not int or revision != old['revision']:
                raise RevisionConflict('台账已被另一页面更新，请重新加载后编辑；没有覆盖现有记录')
            doc = dict(scene=scene, shape=list(shape), revision=revision+1, parcels=validate_parcels(parcels, shape),
                       updated=datetime.now(timezone.utc).isoformat())
            self.root.mkdir(parents=True, exist_ok=True)
            path = self.root/(scene+'.json');tmp = self.root/(scene+'.'+uuid.uuid4().hex+'.tmp')
            with tmp.open('w', encoding='utf-8') as f:
                json.dump(doc, f, ensure_ascii=False, allow_nan=False);f.flush();os.fsync(f.fileno())
            os.replace(tmp, path)
            return doc


def compare(a, b, test=None, manifest=None, evaluation_error=None):
    if a.identity == b.identity:raise ValueError('请选择两次不同的板卡任务')
    if a.identity['scene'] != b.identity['scene'] or a.shape != b.shape or a.classes != b.classes:
        raise ValueError('只能对比同场景、同坐标系和同类别顺序的任务')
    both = a.seen & b.seen;n = int(both.sum());changed = int((a.pred[both] != b.pred[both]).sum())
    cm = np.zeros((len(a.classes), len(a.classes)), np.int64)
    np.add.at(cm, (a.pred[both]-1, b.pred[both]-1), 1)
    ma = board_metrics.evaluate(a.pred, both, test, len(a.classes)) if test is not None else None
    mb = board_metrics.evaluate(b.pred, both, test, len(a.classes)) if test is not None else None
    return dict(source='board', a=a.summary(), b=b.summary(), common=n, changed=changed,
                agree=1-changed/n if n else None, transition=cm.tolist(), transition_axes='rows=A, columns=B',
                common_seen_sha256=hashlib.sha256(both.astype('u1').tobytes()).hexdigest(),
                complete_task_coverage=bool(a.count == a.snapshot['total'] and b.count == b.snapshot['total']),
                same_roi=a.snapshot['roi'] == b.snapshot['roi'], labeled=ma['n'] if ma else 0,
                acc_a=ma['OA'] if ma else None, acc_b=mb['OA'] if mb else None, metrics_a=ma, metrics_b=mb,
                evaluation=dict(available=test is not None, manifest=manifest, error=evaluation_error),
                scope='COMMON_RECEIVED_PIXELS_ONLY_FIXED_TEST100_NO_TRAINING_REFERENCE')


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')


def csv_bytes(rows, fields):
    f = io.StringIO(newline='');writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore');writer.writeheader()
    for row in rows:
        safe = {k: ("'"+v if isinstance(v, str) and v.startswith(('=', '+', '-', '@', '\t', '\r')) else v) for k, v in row.items()}
        writer.writerow(safe)
    return b'\xef\xbb\xbf'+f.getvalue().encode('utf-8')


def class_png(result, palette):
    if len(palette) != len(result.classes)+1 or any(not re.fullmatch('#[0-9a-fA-F]{6}', c) for c in palette):
        raise ValueError('Palette/class contract mismatch')
    colors = np.array([[int(c[i:i+2], 16) for i in (1, 3, 5)] for c in palette], 'u1')
    rgb = colors[result.pred]
    yy, xx = np.indices(result.shape);grey = np.where((yy//8+xx//8) % 2, 45, 65).astype('u1')
    rgb[~result.seen] = np.repeat(grey[~result.seen, None], 3, axis=1)
    def chunk(kind, data):
        return struct.pack('>I', len(data))+kind+data+struct.pack('>I', zlib.crc32(kind+data))
    raw = b''.join(b'\0'+line.tobytes() for line in rgb)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR', struct.pack('>IIBBBBB', result.shape[1], result.shape[0], 8, 2, 0, 0, 0))+chunk(b'IDAT', zlib.compress(raw))+chunk(b'IEND', b'')


def report_bundle(result, data, ledger, gsd, palette, run, evaluation=None, comparison=None,phase_timing=None):
    """One consistent snapshot -> printable HTML + raw words/masks + JSON/CSV."""
    if data['prediction_words_seen_sha256'] != result.sha256:raise ValueError('Analysis/report snapshot mismatch')
    rows = parcel_rows(result, ledger['parcels'], gsd, data['conf_thr'])
    report = dict(schema='gcs-board-agri-v1', generated=datetime.now(timezone.utc).isoformat(),
                  run={k:run.get(k) for k in ('id', 'kind', 'scene', 'version', 'elapsed', 'status')},
                  analysis=data, parcels=rows, ledger=ledger, evaluation=evaluation, comparison=comparison,
                  performance=result.snapshot.get('performance'),phase_timing=phase_timing, source='board',
                  acceptance='BUSINESS_SNAPSHOT_NOT_BOARD_OR_RELEASE_ACCEPTANCE',
                  notes=['面积基于数据集GSD；重叠地块分别统计，不能相加当总面积。',
                         '未接收像素为棋盘格，不属于任何类；低置信和碎斑只作待核查。',
                         '计算计时含PS准备和引擎等待，不是纯PL；未测不回填。'])
    esc = lambda v: html.escape('—' if v is None else str(v))
    def table(items, columns):
        return '<table><thead><tr>'+''.join('<th>'+esc(label)+'</th>' for _, label in columns)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+esc(item.get(key))+'</td>' for key, _ in columns)+'</tr>' for item in items)+'</tbody></table>'
    png = class_png(result, palette)
    legend = ''.join(f'<span><i style="background:{palette[i+1]}"></i>{esc(name)}</span>' for i, name in enumerate(result.classes))
    coverage = '完整任务覆盖' if data['complete_task_coverage'] else '部分覆盖，非整景完整结论'
    perf = result.snapshot.get('performance') or {}
    ms = perf.get('ms_per_pixel');speed = perf.get('pixels_per_second')
    metrics = evaluation.get('result') if evaluation and evaluation.get('available') else None
    evaluation_html = table([metrics], [('n', '测试像素'), ('test_total', '固定测试总数'), ('OA', 'OA'), ('AA', 'AA'), ('Kappa', 'Kappa')]) if metrics else '<p>未测：'+esc((evaluation or {}).get('error', '无可用固定标签评测'))+'</p>'
    if metrics:evaluation_html += table([dict(name=name, recall=metrics['per_class'][i], support=metrics['support'][i]) for i, name in enumerate(result.classes)], [('name', '类别'), ('support', '已覆盖真值'), ('recall', '召回')])
    comparison_html = table([comparison], [('common', '共同已接收像素'), ('changed', '分类变化'), ('labeled', '共同测试像素'), ('acc_a', 'A OA'), ('acc_b', 'B OA')]) if comparison else '<p>未选择两次真实板任务</p>'
    page = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>板卡农情任务报告</title><style>body{font:15px system-ui,sans-serif;max-width:1100px;margin:30px auto;color:#172b3a;padding:0 16px}h1,h2{color:#087f75}table{border-collapse:collapse;width:100%;margin:12px 0;break-inside:auto}th,td{border:1px solid #cbd5e1;padding:7px;text-align:left}th{background:#e6f5f1}.legend{display:flex;flex-wrap:wrap;gap:12px}.legend i{display:inline-block;width:12px;height:12px;margin-right:5px}.map{display:block;max-width:100%;max-height:650px;image-rendering:pixelated}code{overflow-wrap:anywhere}li{margin:6px}thead{display:table-header-group}@media print{body{margin:0;font-size:10pt}h2{break-after:avoid}.map{max-height:175mm}}</style><body>'
    page += '<h1>板卡农情任务报告</h1><p>'+esc(report['generated'])+' · 任务 #'+esc(run.get('id'))+' · '+esc(result.identity['scene'])+' / '+esc(result.identity['model'])+'</p>'
    page += '<p>'+esc(result.snapshot['status'])+' · '+coverage+' · '+str(result.count)+' / '+str(result.snapshot['total'])+' 像素</p><p>像素/秒（计算）：'+esc(speed if speed is not None else '未测')+' · ms/像素：'+esc(ms if ms is not None else '未测')+'；功耗/温度：未测。</p>'
    page += '<h2>分类图</h2><img class="map" alt="未接收为棋盘格的板卡分类图" src="data:image/png;base64,'+base64.b64encode(png).decode()+'"><div class="legend">'+legend+'</div>'
    page += '<h2>类别面积</h2>'+table(data['area'], [('name', '类别'), ('pixels', '像素'), ('area_m2', '面积 m²'), ('share', '已接收占比'), ('mean_conf', '平均置信度')])
    page += '<h2>地块台账（版本 '+esc(ledger['revision'])+'）</h2>'+table(rows, [('name', '地块'), ('area_m2', '边界面积 m²'), ('received_pixels', '已识别像素'), ('done', '覆盖率'), ('main', '主类'), ('mix', '混杂比例'), ('low', '低置信比例')])
    page += '<h2>待核查与补采样</h2><p>置信阈值 '+esc(data['conf_thr'])+'；最小斑块 '+esc(data['min_px'])+' 像素；最多 '+esc(data['patch_limit'])+' 条。</p>'+table(data['patches'], [('kind', '类型'), ('row', '行'), ('col', '列'), ('area_px', '像素'), ('mean_conf', '均置信')])+table(data['sampling'], [('row', '行'), ('col', '列'), ('mean_conf', '窗均置信')])
    page += '<h2>固定Test100评测（不是训练参考成绩）</h2>'+evaluation_html+'<h2>真实任务对比</h2>'+comparison_html
    page += '<h2>任务分项耗时（私有App墙钟，非纯PL）</h2>'
    if phase_timing and phase_timing.get('available'):
        page += table(phase_timing['phases'], [('label','阶段'),('calls','调用数'),('us','累计微秒')])
        page += '<p>其他未埋点/暂停/日志时间：'+esc(phase_timing['other_us'])+' 微秒；等待服务子集：'+esc(phase_timing['wait_service']['us'])+' 微秒，已包含在上表相关阶段中，不再累加。</p>'
        internal=phase_timing.get('internal_timing') or {}
        if internal.get('available'):
            page += '<h3>step内部PS/driver细分（子集，不与App表相加）</h3>'+table(internal['phases'],[('label','部分'),('calls','调用数'),('us','累计微秒')])
            e=internal['engine']
            page += '<p>PL独立计数：'+esc(e['cycles'])+' 周期 / '+esc(e['hz'])+' Hz；'+esc(e['ms_per_pixel'])+' ms/像素（批均值）。含PL内AXI等待，不含PS；不可再与driver等待墙钟相加。</p>'
            page += '<p>driver等待服务子集：'+esc(internal['wait_service']['us'])+' 微秒；step未埋点余项：'+esc(internal['other_step_us'])+' 微秒。频率来自匹配XSA的PL0配置，非独立示波器测量。</p>'
        else:page += '<p>PS数值准备与纯PL内部尚未独立测量；分项不能替代硬件内部计时。</p>'
    else:page += '<p>未测或记录不完整：'+esc((phase_timing or {}).get('reason','无UART分项计时'))+'</p>'
    page += '<h2>口径与证据</h2><ul>'+''.join('<li>'+esc(note)+'</li>' for note in report['notes'])+'</ul><p>板任务身份：<code>'+esc(json.dumps(result.identity))+'</code></p><p>CLASS+seen SHA256：<code>'+result.sha256+'</code></p><p>本报告不是DP目视、完整生命周期或第一版实机验收证明。</p></body></html>'
    files = {'report.html':page.encode('utf-8'), 'report.json':json_bytes(report), 'board_result.json':json_bytes(result.snapshot),
             'phase_timing.json':json_bytes(phase_timing),
             'classification.png':png, 'words_le_u32.bin':result.words.tobytes(), 'seen_u8.bin':result.seen.astype('u1').tobytes(),
             'area.csv':csv_bytes(data['area'], ['class_id', 'name', 'pixels', 'area_m2', 'share', 'mean_conf']),
             'parcels.csv':csv_bytes(rows, ['id', 'name', 'pixels', 'area_m2', 'received_pixels', 'done', 'main', 'main_share', 'mix', 'low']),
             'patches.csv':csv_bytes(data['patches'], ['kind', 'row', 'col', 'area_px', 'area_m2', 'cls', 'mean_conf']),
             'sampling.csv':csv_bytes(data['sampling'], ['row', 'col', 'mean_conf'])}
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, raw in files.items():z.writestr(name, raw)
        z.writestr('sha256.json', json_bytes({name:hashlib.sha256(raw).hexdigest() for name, raw in files.items()}))
    return report, stream.getvalue()
