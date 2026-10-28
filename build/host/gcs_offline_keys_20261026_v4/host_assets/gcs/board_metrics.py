"""Statistics from real received CLASS words and pinned evaluation labels.

No model import, training reference, GPU, device I/O or inference fallback.
"""
import hashlib
import io
import csv
import json
from pathlib import Path
import zlib

import numpy as np
from scipy.io import loadmat
import board_models

ROOT = Path(__file__).resolve().parents[1]


def validate_labels(gt, train, test, ncls):
    if gt.shape != train.shape or gt.shape != test.shape or gt.ndim != 2:
        raise ValueError('Label shape mismatch')
    for a in (gt, train, test):
        if a.dtype.kind not in 'ui' or np.any(a < 0) or np.any(a > ncls):
            raise ValueError('Invalid label values')
    if np.any((train > 0) & (test > 0)):
        raise ValueError('Train/test overlap')
    if np.any(train[train > 0] != gt[train > 0]) or np.any(test[test > 0] != gt[test > 0]):
        raise ValueError('Split labels disagree with GT')
    if not np.array_equal((train > 0) | (test > 0), gt > 0):
        raise ValueError('Official split does not cover labeled GT')


def load_label_set(root=ROOT, manifest_path=None,scene=None):
    root = Path(root).resolve()
    path = Path(manifest_path) if manifest_path else root / ('gcs/eval_longkou_v2.json' if scene is None else f'gcs/eval_{board_models.scene_spec(scene)["scene"]}.json')
    raw_manifest = path.read_bytes()
    meta = json.loads(raw_manifest)
    if meta.get('schema')==2:
        spec=board_models.scene_spec(scene or meta['scene'])
        if (meta['scene'],meta['shape'],len(meta['classes']),meta.get('bands'),meta.get('label_base'))!=(spec['scene'],spec['shape'],spec['classes'],270,1):
            raise ValueError('Unsupported fixed label contract')
    elif (meta['scene'], meta['model'], meta['wcrc'], meta['shape']) != ('longkou', 'v2', '27231983', [550, 400]):
        raise ValueError('Unsupported evaluation contract')
    arrays = {}
    for name in ('gt', 'train', 'test'):
        record = meta['files'][name]
        file = (root / record['path']).resolve()
        if not file.is_relative_to(root):
            raise ValueError('Evaluation input outside project')
        raw = file.read_bytes()
        if (len(raw), hashlib.sha256(raw).hexdigest(), f'{zlib.crc32(raw):08x}') != (
                record['bytes'], record['sha256'], record['crc32']):
            raise ValueError('Evaluation file size/SHA256/CRC mismatch: ' + name)
        if name == 'gt':
            arrays[name] = np.frombuffer(raw, dtype=np.uint8).reshape(meta['shape'])
        else:
            values = [v for k, v in loadmat(io.BytesIO(raw)).items() if not k.startswith('__')]
            if len(values) != 1 or list(values[0].shape) != meta['shape']:
                raise ValueError('Ambiguous evaluation MAT array: ' + name)
            arrays[name] = values[0]
    validate_labels(arrays['gt'], arrays['train'], arrays['test'], len(meta['classes']))
    meta['manifest_sha256'] = hashlib.sha256(raw_manifest).hexdigest()
    return arrays, meta


def load_labels(root=ROOT, manifest_path=None,scene=None):
    arrays, meta = load_label_set(root, manifest_path,scene)
    return arrays['test'], meta


def evaluate(pred, seen, test, ncls):
    pred, seen, test = np.asarray(pred), np.asarray(seen), np.asarray(test)
    if pred.shape != test.shape or seen.shape != test.shape or pred.ndim != 2 or seen.dtype != bool:
        raise ValueError('Prediction/seen/label shape or type mismatch')
    if pred.dtype.kind not in 'ui' or test.dtype.kind not in 'ui' or ncls < 1:
        raise ValueError('Integer labels/predictions required')
    if np.any(test < 0) or np.any(test > ncls) or np.any(pred[seen] < 1) or np.any(pred[seen] > ncls):
        raise ValueError('Invalid received prediction or label')
    selected = seen & (test > 0)
    n, total = int(selected.sum()), int((test > 0).sum())
    cm = np.zeros((ncls, ncls), dtype=np.int64)
    np.add.at(cm, (test[selected].astype(np.int64) - 1, pred[selected].astype(np.int64) - 1), 1)
    support, predicted = cm.sum(1), cm.sum(0)
    recall = np.divide(cm.diagonal(), support, out=np.zeros(ncls), where=support > 0)
    precision = np.divide(cm.diagonal(), predicted, out=np.zeros(ncls), where=predicted > 0)
    f1=np.divide(2*cm.diagonal(),support+predicted,out=np.zeros(ncls),where=support+predicted>0)
    oa = float(cm.trace() / n) if n else None
    pe = float(np.dot(support, predicted) / n**2) if n else None
    return dict(n=n, test_total=total, received_pixels=int(seen.sum()),
                coverage=n / total if total else 0, complete_test_coverage=bool(total and n == total),
                OA=oa, AA=float(recall[support > 0].mean()) if n else None,
                Kappa=(oa - pe) / (1 - pe) if n and pe < 1 else None,
                kappa_note='undefined when empty or expected agreement is one' if not n or pe == 1 else None,
                per_class=[float(v) if support[i] else None for i, v in enumerate(recall)],
                precision=[float(v) if predicted[i] else None for i, v in enumerate(precision)],
                f1=[float(v) if support[i]+predicted[i] else None for i,v in enumerate(f1)],
                macro_F1=float(f1[support>0].mean()) if n else None,
                weighted_F1=float(np.dot(f1,support)/n) if n else None,
                correct_pixels=int(cm.trace()),evaluated_classes=int((support>0).sum()),
                predicted_counts=predicted.tolist(),support=support.tolist(), cm=cm.tolist(), matrix_axes='rows=true, columns=predicted')


def from_snapshot(snapshot, root=ROOT, manifest_path=None):
    modern=snapshot.get('model_lifecycle') is True
    if modern:board_models.task_identity(snapshot)
    test, manifest = load_labels(root, manifest_path,scene=snapshot['scene'] if modern else None)
    if not modern and (snapshot.get('scene'), snapshot.get('model'), snapshot.get('wcrc')) != ('longkou', 'v2', '27231983'):
        raise ValueError('Prediction model/scene differs from evaluation contract')
    if not (snapshot.get('ack') or snapshot.get('accepted_via_info')) or snapshot.get('error') or snapshot.get('integrity_error') or snapshot.get('status') not in ('running', 'paused', 'stopped', 'done'):
        raise ValueError('No acknowledged healthy board result to evaluate')
    words = np.zeros(test.shape, dtype='<u4')
    seen = np.zeros(test.shape, dtype=bool)
    roi = snapshot['roi']
    for cell in snapshot['cells']:
        y, x, word = cell['y'], cell['x'], int(cell['class_word'], 16)
        if (not (0 <= y < test.shape[0] and 0 <= x < test.shape[1]) or
                not (roi['y'] <= y < roi['y'] + roi['height'] and roi['x'] <= x < roi['x'] + roi['width']) or
                word < 0 or word > 0xffffffff or word & 0xff00 or (word & 255) >= len(manifest['classes']) or seen[y, x]):
            raise ValueError('Invalid/duplicate board coordinate or CLASS word')
        if cell['class_id'] != word & 255:
            raise ValueError('Derived label differs from raw CLASS')
        words[y, x], seen[y, x] = word, True
    if int(seen.sum()) != snapshot['received_pixels']:
        raise ValueError('Board received count differs from unique cells')
    if snapshot['status'] == 'done' and int(seen.sum()) != roi['width'] * roi['height']:
        raise ValueError('Incomplete completed board result')
    pred = ((words & 255) + 1).astype(np.uint8)  # raw CLASS0 is crop1, NOT no-data
    result = evaluate(pred, seen, test, len(manifest['classes']))
    task_test_total=int((test[roi['y']:roi['y']+roi['height'],roi['x']:roi['x']+roi['width']]>0).sum())
    result.update(task_test_total=task_test_total,task_test_coverage=result['n']/task_test_total if task_test_total else 0,
                  complete_task_test_coverage=bool(task_test_total and result['n']==task_test_total))
    result.update(source='board', computation='CPU statistics of board predictions; no PC model inference',
                  evaluation=manifest, task_status=snapshot['status'],
                  identity={k: snapshot[k] for k in ('boot_id', 'session', 'task', 'wcrc', 'scene', 'model')},
                  prediction_words_seen_sha256=hashlib.sha256(words.tobytes() + seen.astype(np.uint8).tobytes()).hexdigest(),
                  scope='FIXED_TEST100_ON_RECEIVED_BOARD_PREDICTIONS_NOT_NEW_INFERENCE')
    return result


def csv_text(report):
    out=io.StringIO(newline='');writer=csv.writer(out)
    for key in ('OA','AA','Kappa','macro_F1','weighted_F1','n','test_total','task_test_total','coverage','correct_pixels'):
        writer.writerow([key,'' if report.get(key) is None else report[key]])
    writer.writerow([])
    writer.writerow(['类别','真实测试像素','正确识别像素','分类结果像素','精确率','召回率','F1'])
    names=report.get('class_names') or report['evaluation']['classes']
    for i,name in enumerate(names):
        writer.writerow([name,report['support'][i],report['cm'][i][i],report['predicted_counts'][i],
                         *('' if values[i] is None else values[i] for values in (report['precision'],report['per_class'],report['f1']))])
    return out.getvalue()
