"""Restore original file paths and bytes into a NEW independent runtime directory."""
import argparse,hashlib,json,shutil
from pathlib import Path,PurePosixPath

ROOT=Path(__file__).resolve().parents[1]

def safe(root,value):
    relative=PurePosixPath(value)
    if relative.is_absolute() or '..' in relative.parts or '\\' in value or ':' in value:
        raise ValueError('Unsafe path '+value)
    path=root.joinpath(*relative.parts)
    if not path.resolve().is_relative_to(root.resolve()):raise ValueError('Path escape')
    return path

def digest(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    output=Path(args.output).resolve()
    if output.exists():raise RuntimeError('Output must not exist; existing directories are never overwritten')
    if output.is_relative_to(ROOT) or ROOT.is_relative_to(output):raise RuntimeError('Output must be separate from the submission tree')
    mapping=json.loads((ROOT/'build/delivery_metadata/layout_map.json').read_text('utf-8'))['files']
    manifest=json.loads((ROOT/'package_manifest.json').read_text('utf-8'))
    expected={row['path']:row['sha256'] for row in manifest['files']}
    verified=[];seen=set()
    for row in mapping:
        source=safe(ROOT,row['path']);destination=safe(output,row['original_path'])
        if row['original_path'].casefold() in seen:raise RuntimeError('Duplicate runtime path')
        seen.add(row['original_path'].casefold())
        if expected.get(row['path'])!=row['sha256'] or digest(source)!=row['sha256']:
            raise RuntimeError('Source verification failed '+row['path'])
        verified.append((source,destination,row['sha256']))
    output.mkdir(parents=True,exist_ok=False)
    for source,destination,sha in verified:
        destination.parent.mkdir(parents=True,exist_ok=True)
        with source.open('rb') as original,destination.open('xb') as target:shutil.copyfileobj(original,target)
        if digest(destination)!=sha:raise RuntimeError('Copy mismatch '+str(destination))
    print(json.dumps({'result':'PASS','scope':'ORIGINAL_LAYOUT_AND_BYTES_RESTORED_NO_PRODUCT_EXECUTION',
        'output':str(output),'files':len(verified),'next':'python verify_package.py'},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
