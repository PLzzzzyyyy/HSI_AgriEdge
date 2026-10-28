'''Recover a completed default LongKou GCS training run without running a trainer.

Only missing baseline data, the unsaved PC Test100 evaluation, paired exports
and local candidate receipts are restored. No server import, network, board,
GUI, upload, activation, service restart or running catalog mutation is used.
Run this from an inactive checkout whose model sources match the runtime.
'''
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import time
from types import SimpleNamespace

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'model'), str(ROOT / 'gcs')]
SOURCES = tuple('model/' + n + '.py' for n in (
    'finetune_region', 'train_scene', 'preprocess', 'tt_model', 'scenes',
    'export_board_candidate', 'export_scene', 'engine_ref', 'fixed_point_sim', 'quant')) + (
    'gcs/board_models.py', 'gcs/engine.py')


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def child(root, *parts):
    path = root.joinpath(*parts).resolve()
    require(path.is_relative_to(root), 'Path escapes the intended root')
    return path


def write_once(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open('xb') as stream:
            stream.write(raw)
    except FileExistsError:
        require(path.read_bytes() == raw, f'Refuse to overwrite existing artifact: {path}')


def save_json(path, value):
    write_once(path, (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8'))


def scene_files(baseline):
    # Load only the checked path registry, never a server or trainer. Resolve
    # both worktrees: identical code does not imply identical raw input data.
    spec = importlib.util.spec_from_file_location('_recovery_scene_paths', baseline / 'model/scenes.py')
    scenes = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scenes)
    cube, gt = scenes.raw_paths('longkou')
    train, test = scenes.split_paths('longkou', 100)
    return dict(cube=cube, gt=gt, train=train, test=test)


def audit(runtime, baseline, tag):
    require(re.fullmatch(r'live\d{4}_\d{6}', tag) is not None, 'Invalid live run tag')
    loop = child(runtime, 'data/closed_loop/longkou')
    base_loop = child(baseline, 'data/closed_loop/longkou')
    out = child(loop, 'runs', tag)
    evidence = child(runtime, 'build/host/gcs_training', tag)
    command = read_json(evidence / 'command.json')
    n = command.get('annotate')
    require(type(n) is int and 1 <= n <= 90, 'Invalid annotation count')
    expected = ['finetune', '--scene', 'longkou', '--hold-class', '3', '--annotate', str(n),
                '--weights-version', tag, '--run-tag', tag]
    argv = command['argv']
    require(len(argv) >= 4 and argv[1] == '-u' and argv[3:] == expected and
            Path(argv[2]).resolve() == child(runtime, 'model/finetune_region.py') and
            Path(command['cwd']).resolve() == runtime and command['scene'] == 'longkou' and
            command['base_version'] == 'hold3', 'Unsupported original training command/recipe')
    info = read_json(base_loop / 'region.json')
    require(info == read_json(loop / 'region.json'), 'Runtime/baseline region identity differs')
    require((info['scene'], info['model'], info['seed'], info['hold_class'],
             info['official_train'], info['official_test']) ==
            ('longkou', 'unoverlapping', 0, 3, 'Train100.mat', 'Test100.mat'), 'Wrong registered recipe')
    region = info['region']; y, x, size = (region[k] for k in ('row0', 'col0', 'size'))
    require([y, x, size, size] == command['rect'] and size == 64 and y >= 0 and x >= 0,
            'Wrong registered region')
    old_ckpt = Path(info['old_ckpt']).resolve(strict=True)
    require(sha(old_ckpt) == info['old_ckpt_sha256'], 'Old checkpoint SHA256 mismatch')
    old_manifest = child(runtime, 'data/scenes/longkou/weights/hold3/board_model.json')
    old_meta = read_json(old_manifest)
    require(old_meta['scene'] == 'longkou' and old_meta['tag'] == 'hold3' and
            old_meta['checkpoint_sha256'] == info['old_ckpt_sha256'], 'Deployed hold3 checkpoint binding differs')
    protected = [evidence / 'command.json', evidence / 'exit.json', evidence / 'training.log',
                 base_loop / 'region.json', loop / 'region.json', old_ckpt, old_manifest]
    for name in SOURCES:
        a, b = child(baseline, name), child(runtime, name)
        require(a.read_text(encoding='utf-8') == b.read_text(encoding='utf-8'), f'Model source drift: {name}')
        protected.extend((a, b))
    arrays = {}
    for name, path in [('old', base_loop / 'pred_old_region.bin'), ('gt', base_loop / 'gt_region.bin'),
                       ('new', out / f'pred_new_region_ft{n}.bin')]:
        raw = path.read_bytes()
        require(len(raw) == size * size, f'Wrong {name} region byte count')
        array = np.frombuffer(raw, np.uint8).reshape(size, size)
        require(array.max() <= 9 and (name == 'gt' or array.min() >= 1), f'Invalid {name} region labels')
        arrays[name] = array; protected.append(path)
    old, gt, new = (arrays[k] for k in ('old', 'gt', 'new'))
    lab, held = gt > 0, gt == 3
    require(lab.any() and int(held.sum()) == region['hold_pixels'] and held.any(), 'GT region population differs')
    require(np.bincount(old.ravel(), minlength=10).tolist() == info['old_region_pred_hist'] and
            abs(float(np.mean(old[lab] == gt[lab])) - info['old_region_oa']) < 1e-12 and
            abs(float(np.mean(old[held] == 3)) - info['old_region_hold_recall']) < 1e-12,
            'Old prediction differs from registered baseline statistics')
    for name in ('pred_old_region.bin', 'gt_region.bin'):
        target = child(loop, name)
        require(not target.exists() or target.read_bytes() == (base_loop / name).read_bytes(),
                f'Refuse to overwrite conflicting runtime input: {target}')
    paths = {k: Path(v).resolve(strict=True) for k, v in scene_files(baseline).items()}
    runtime_paths = {k: Path(v).resolve(strict=True) for k, v in scene_files(runtime).items()}
    digests = {p: sha(p) for p in set(paths.values()) | set(runtime_paths.values())}
    require(all(digests[paths[k]] == digests[runtime_paths[k]] for k in paths), 'Runtime raw input binding differs')
    import preprocess
    raw_gt, train, test = (preprocess.load_mat(paths[k]) for k in ('gt', 'train', 'test'))
    require(raw_gt.shape == train.shape == test.shape == (550, 400) and
            np.array_equal(raw_gt[y:y + size, x:x + size], gt), 'GT original/crop binding differs')
    require(not np.any((train > 0) & (test > 0)) and
            all(int((train == c).sum()) == 100 for c in range(1, 10)) and
            np.array_equal(train[train > 0], raw_gt[train > 0]) and
            np.array_equal(test[test > 0], raw_gt[test > 0]), 'Official Train100/Test100 binding differs')
    pts = np.argwhere(train == 3)
    inside = (pts[:, 0] >= y) & (pts[:, 0] < y + size) & (pts[:, 1] >= x) & (pts[:, 1] < x + size)
    order = np.lexsort((np.linalg.norm(pts - [y + size / 2, x + size / 2], axis=1), ~inside))
    annotation_path = out / f'annotations_{n}.json'
    require(read_json(annotation_path) == dict(scene='longkou', hold_class=3, source='Train100.mat',
            inside_region=int(inside[order][:n].sum()), points=pts[order][:n].tolist()),
            'Saved annotation is not the registered Train100 selection')
    log = (evidence / 'training.log').read_text(encoding='utf-8')
    epochs = re.findall(r'^ep\s+(\d+) loss [\d.]+ val_oa [\d.]+ best ([\d.]+)@(\d+) (\d+)s$', log, re.M)
    failure = read_json(evidence / 'exit.json')
    require([int(e[0]) for e in epochs] == [5, 10, 15, 20, 25, 30] and failure['exit'] == 1 and
            'FileNotFoundError' in log and any(s in log for s in ('pred_old_region.bin', 'gt_region.bin')),
            'Training was not completed with the supported missing-input failure')
    ckpt = child(runtime, f'data/ckpt/longkou_unoverlapping_s0_hold3_ft{n}_{tag}.pth')
    protected.extend([ckpt, annotation_path, *paths.values(), *runtime_paths.values(), Path(__file__).resolve()])
    files = {str(p): dict(bytes=p.stat().st_size, sha256=digests[p] if p in digests else sha(p), mtime_ns=p.stat().st_mtime_ns)
             for p in dict.fromkeys(protected)}
    identity = {p: {k: v[k] for k in ('bytes', 'sha256')} for p, v in files.items()}
    fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    return dict(runtime=runtime, baseline=baseline, tag=tag, n=n, out=out, loop=loop, base_loop=base_loop,
                evidence=evidence, ckpt=ckpt, ckpt_sha256=sha(ckpt), info=info, paths=paths, files=files,
                fingerprint=fingerprint, failure=failure, best_val_reported=float(epochs[-1][1]),
                best_epoch=int(epochs[-1][2]), test_count=int((test > 0).sum()),
                region=dict(old_oa=info['old_region_oa'], new_oa=float(np.mean(new[lab] == gt[lab])),
                            old_hold_recall=info['old_region_hold_recall'], new_hold_recall=float(np.mean(new[held] == 3)),
                            changed_pixels=int(np.sum(new != old)), agree_old_new=float(np.mean(new == old))))


def unchanged(plan):
    for name, record in plan['files'].items():
        stat = Path(name).stat()
        require((stat.st_size, stat.st_mtime_ns) == (record['bytes'], record['mtime_ns']), f'Input changed during recovery: {name}')


def evaluate_test(plan):
    # No call to train(), cmd_finetune(), optimizer, backward(), validation
    # selection, old-model inference or already-saved new-region inference.
    import finetune_region as ft
    import torch
    args = SimpleNamespace(scene='longkou', hold_class=3, per_class=100)
    _, scene, _, test, _, _, ncls = ft.load_scene(args)
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    model = ft.tt_model.MODELS['unoverlapping'](ncls).to(device)
    model.load_state_dict(torch.load(plan['ckpt'], map_location=device, weights_only=True), strict=True)
    coords = np.argwhere(test > 0); labels = test[coords[:, 0], coords[:, 1]]
    started = time.monotonic()
    with torch.inference_mode():
        prediction = ft.predict(model, ft.Windows(scene.padded), coords, device)
    return dict(metrics=ft.metrics(prediction, labels, ncls), count=len(coords), device=device,
                seconds=time.monotonic() - started,
                scope='PC_TEST100_EVALUATION_FROM_SAVED_CHECKPOINT_NOT_BOARD_RESULT'), prediction.astype(np.uint8).tobytes()


def export_pair(plan):
    from export_board_candidate import export_candidate
    candidate = export_candidate('longkou', plan['ckpt'], plan['tag'], data_root=plan['runtime'] / 'data/scenes')
    # Exercise the existing catalog consumer only in this offline process.
    # The still-running production process is not imported or patched.
    import engine
    engine.DATA = plan['runtime'] / 'data/scenes'
    errors = engine.discover_board_exports()
    require(not any(e['tag'] == plan['tag'] for e in errors) and
            any(v['id'] == plan['tag'] and v['pkg'] == plan['tag'] for v in engine.VERSIONS['longkou']),
            'New local candidate was not discoverable')
    return candidate


def recover(runtime, baseline, tag, report, *, evaluate=evaluate_test, export=export_pair):
    started = time.monotonic()
    runtime, baseline, report = (Path(p).resolve() for p in (runtime, baseline, report))
    plan = audit(runtime, baseline, tag)
    fp = plan['fingerprint']; n = plan['n']
    result_path = plan['out'] / f'finetune_{n}.json'
    if result_path.exists():
        result = read_json(result_path)
        require(result.get('recovery', {}).get('fingerprint') == fp, 'Existing result fingerprint differs')
        # Completing a receipt write after an interrupted recovery is safe;
        # never silently perform another evaluation/export for a completed run.
        save_json(report / 'completion.json', result)
        save_json(plan['evidence'] / 'postprocess_recovery.json', result)
        return result
    for path in (report / 'input_audit.json', report / 'test_evaluation.json'):
        if path.exists(): require(read_json(path)['fingerprint'] == fp, 'Cached recovery fingerprint differs')
    receipt = dict(fingerprint=fp, files=plan['files'], scene='longkou', tag=tag,
                   region=plan['info']['region'], old_ckpt_sha256=plan['info']['old_ckpt_sha256'],
                   new_ckpt_sha256=plan['ckpt_sha256'], test_count=plan['test_count'],
                   baseline_binding='REGISTERED_REGION_STATS_AND_CHECKPOINT_SHA_WITH_EXACT_RAW_GT_CROP',
                   scope='OFFLINE_INPUT_PROVENANCE_NO_TRAINING_OR_BOARD_IO')
    save_json(report / 'input_audit.json', receipt)
    for name in ('pred_old_region.bin', 'gt_region.bin'):
        write_once(plan['loop'] / name, (plan['base_loop'] / name).read_bytes())
    cached = report / 'test_evaluation.json'
    if cached.exists():
        evaluated = read_json(cached)
        require(evaluated['prediction_sha256'] == sha(report / 'test_prediction.bin'), 'Cached Test100 prediction differs')
    else:
        print('Recovering only unsaved Test100 evaluation; trainer and saved ROI inference are not called.', flush=True)
        evaluated, prediction = evaluate(plan)
        require(evaluated['count'] == plan['test_count'] == len(prediction), 'Test100 prediction count differs')
        evaluated.update(fingerprint=fp, checkpoint_sha256=plan['ckpt_sha256'],
                         prediction_sha256=hashlib.sha256(prediction).hexdigest())
        unchanged(plan)
        write_once(report / 'test_prediction.bin', prediction)
        save_json(cached, evaluated)
    unchanged(plan)
    candidate = export(plan)
    require(candidate['provenance']['checkpoint_sha256'] == plan['ckpt_sha256'] and
            candidate['scene'] == 'longkou' and candidate['tag'] == tag, 'Export checkpoint/tag identity differs')
    unchanged(plan)
    result = dict(tag=plan['ckpt'].stem, new_ckpt=str(plan['ckpt']), new_ckpt_sha256=plan['ckpt_sha256'],
        annotate=n, train=plan['info']['old_train'] + n, val=plan['info']['old_val'] + 10,
        epochs=30, lr=2e-4, best_val=None, best_val_reported=plan['best_val_reported'],
        best_val_source='ORIGINAL_TRAINING_LOG_ROUNDED_4_DP_NOT_REEVALUATED', best_epoch=plan['best_epoch'],
        new_test=evaluated['metrics'], old_test=plan['info']['old_test'], region=plan['region'],
        weights=dict(version=tag, dir=str(plan['runtime'] / 'data/scenes/longkou/weights' / tag), board_candidate=candidate),
        seconds_train=None, seconds_total=None,
        recovery=dict(fingerprint=fp, training_reused=True, saved_region_prediction_reused=True,
                      original_failure=plan['failure'], original_log=str(plan['evidence'] / 'training.log'),
                      report=str(report), seconds=time.monotonic() - started,
                      completed_at=time.strftime('%Y-%m-%d %H:%M:%S'), running_service_catalog_updated=False,
                      board_uploaded=False, board_activated=False, board_evaluated=False,
                      scope='PC_POSTPROCESS_AND_LOCAL_CANDIDATE_ONLY_NOT_BOARD_CLOSED_LOOP_ACCEPTANCE'))
    # Original command/training.log/exit.json and checkpoint are never rewritten.
    save_json(plan['evidence'] / 'candidate.json', candidate)
    save_json(report / 'candidate.json', candidate)
    save_json(result_path, result)
    save_json(plan['evidence'] / 'postprocess_recovery.json', result)
    save_json(report / 'completion.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-root', type=Path, required=True)
    parser.add_argument('--run-tag', required=True)
    parser.add_argument('--report-dir', type=Path, required=True)
    args = parser.parse_args()
    result = recover(args.runtime_root, ROOT, args.run_tag, args.report_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
