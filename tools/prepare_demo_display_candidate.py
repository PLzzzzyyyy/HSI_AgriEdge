"""Freeze a distinct local PC/DP display candidate; this is not a release audit."""
import json
import argparse
import shutil
from pathlib import Path

import gcs_release as release


def main():
    root = release.ROOT
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name',default='gcs_pc_dp_link_20261017')
    parser.add_argument('--hardware-xsa',type=Path)
    args=parser.parse_args()
    if not args.name or Path(args.name).name!=args.name or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789_' for c in args.name):
        raise ValueError('Use a new lowercase candidate directory name')
    target = root / 'build/host' / args.name
    if target.exists():
        raise SystemExit('Candidate already exists; preserve it and choose another directory')
    original = release.BUNDLE
    baseline = json.loads((original / 'manifest.json').read_text(encoding='utf-8'))
    sources = release.source_records()
    assets = release.runtime_assets()
    facts = dict(baseline['facts'])
    facts.update(source_set_sha256=release.canonical(sources),
                 asset_set_sha256=release.canonical(assets))
    xsa = args.hardware_xsa.resolve() if args.hardware_xsa else root / 'firmware/tt_gcs_r1_abi4_zu5ev.xsa'
    if args.hardware_xsa:facts['hardware_xsa_sha256']=release.sha(xsa)
    identity = release.canonical(facts)
    target.mkdir(parents=True)
    (target / 'app_src').mkdir()
    files = []
    for source in sources:
        rel = Path(source['path'])
        raw = (root / rel).read_bytes()
        if rel.name == 'roi_release.h':
            raw = release.render_header(raw.decode('utf-8'), facts, identity)
        dest = target / 'app_src' / rel.name
        dest.write_bytes(raw)
        files.append(dict(source=rel.as_posix(), destination='app_src/' + rel.name,
                          bytes=len(raw), sha256=release.sha(dest)))
    for asset in assets:
        rel = release.safe_relative(asset['path'])
        dest = target / 'host_assets' / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / rel, dest)
    (target / 'hardware').mkdir()
    if release.sha(xsa) != facts['hardware_xsa_sha256']:
        raise ValueError('Candidate hardware differs from frozen input')
    shutil.copy2(xsa, target / 'hardware' / xsa.name)
    manifest = dict(result='LOCAL_DEMO_CANDIDATE_NOT_RELEASE_AUDIT',
                    app_id=release.APP_ID, release_id=identity, facts=facts,
                    sources=sources, assets=assets, files=files,
                    based_on_release=baseline['release_id'],
                    scope='Physical key dispatcher and PC/DP feedback; stable inference core; local demonstration only')
    (target / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(bundle=str(target), release_id=identity), indent=2))


if __name__ == '__main__':
    main()
