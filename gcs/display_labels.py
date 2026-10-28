"""Checked Chinese display names; never changes model or dataset class IDs."""
import json
from pathlib import Path

TABLE=json.loads((Path(__file__).with_name('class_labels_zh.json')).read_text(encoding='utf-8'))

def names(scene, original, palette):
    rows=TABLE['scenes'].get(scene)
    if not rows or TABLE['class_base']!=0 or len(rows)!=len(original) or len(palette)!=len(rows)+1:
        raise ValueError('Chinese display class contract mismatch')
    for i,row in enumerate(rows):
        if row['id']!=i or row['name_en']!=original[i] or row['color'].lower()!=palette[i+1].lower():
            raise ValueError('Chinese display class order/color mismatch')
        if not isinstance(row['name_zh'],str) or not any('\u4e00'<=c<='\u9fff' for c in row['name_zh']):
            raise ValueError('Chinese display name missing')
    return [row['name_zh'] for row in rows]
