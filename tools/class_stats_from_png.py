# -*- coding: utf-8 -*-
"""独立复核一张已保存的分类图：从 PNG 重新数类别，不依赖界面里的计数器。

用途：界面统计和图上颜色不一致时，以图为准——图是 ROW 包逐像素画出来的，
这里逐像素解码回去重数一遍，两边应当完全相等。

    D:\\Anaconda\\python.exe tools\\class_stats_from_png.py build\\host\\gcs_mini_xxx\\class_map.png
    ...  --scene longkou --write        # 顺便把 class_stats.csv / summary.json 更正成图上数字

PNG 是本仓库 gcs_mini.py 自己写的（每行 filter=0，RGB 8 bit，无隔行），
所以解码器只支持这一种格式；遇到别的 PNG 会直接报错，不猜。
"""

import argparse
import collections
import csv
import json
import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def decode_png(path):
    blob = Path(path).read_bytes()
    if blob[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("不是 PNG")
    pos, idat, width, height = 8, b"", None, None
    while pos < len(blob):
        length = struct.unpack(">I", blob[pos:pos + 4])[0]
        tag = blob[pos + 4:pos + 8]
        data = blob[pos + 8:pos + 8 + length]
        if tag == b"IHDR":
            width, height, depth, ctype, comp, filt, inter = struct.unpack(">IIBBBBB", data)
            if (depth, ctype, comp, filt, inter) != (8, 2, 0, 0, 0):
                raise ValueError("只支持 8 bit RGB、filter 0、非隔行（gcs_mini.py 的输出）")
        elif tag == b"IDAT":
            idat += data
        pos += 12 + length
    raw = zlib.decompress(idat)
    stride = width * 3
    rows = []
    for y in range(height):
        base = y * (stride + 1)
        if raw[base] != 0:
            raise ValueError("第 %d 行不是 filter 0，不是本工具写出的图" % y)
        rows.append(raw[base + 1:base + 1 + stride])
    return width, height, rows


def build_scenes():
    zh = {}
    try:
        doc = json.loads((ROOT / "gcs/web/longkou_v2_classes.json").read_text(encoding="utf-8"))
        zh = {int(c["id"]): c["name_zh"] for c in doc["classes"]}
    except Exception:
        pass
    table = [("longkou", "LongKou 龙口"), ("honghu", "HongHu 洪湖"), ("hanchuan", "HanChuan 汉川")]
    out = {}
    for key, label in table:
        pal = json.loads((ROOT / ("gcs/scenes/%s/palette.json" % key)).read_text(encoding="utf-8"))
        names_en = pal["classes"][1:]
        colors = [c.lstrip("#").lower() for c in pal["colors"][1:]]
        out[key] = dict(key=key, label=label, classes=len(names_en), en=names_en,
                        zh=[zh.get(i) or names_en[i] for i in range(len(names_en))],
                        colors=colors, w=int(pal["width"]), h=int(pal["height"]))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="从分类图 PNG 重新数类别")
    ap.add_argument("png")
    ap.add_argument("--scene", default="longkou", choices=("longkou", "honghu", "hanchuan"))
    ap.add_argument("--write", action="store_true", help="把同目录的 class_stats.csv / summary.json 更正为图上数字")
    args = ap.parse_args(argv)

    scenes = build_scenes()
    sc = scenes[args.scene]
    width, height, rows = decode_png(args.png)
    if (width, height) != (sc["w"], sc["h"]):
        print("注意：图是 %dx%d，场景整幅是 %dx%d（可能是 ROI 块）"
              % (width, height, sc["w"], sc["h"]))
    lut = {hexcolor: i for i, hexcolor in enumerate(sc["colors"])}
    counts = collections.Counter()
    unknown = 0
    for row in rows:
        for x in range(width):
            key = row[x * 3:x * 3 + 3].hex()
            cls = lut.get(key)
            if cls is None:
                unknown += 1
            else:
                counts[cls] += 1
    total = width * height
    print("图 %dx%d = %d 像素；未上色/未知颜色 %d" % (width, height, total, unknown))
    print("%-4s %-14s %-22s %8s %8s" % ("id", "中文名", "英文名", "像素", "占比"))
    for i in sorted(counts, key=lambda k: -counts[k]):
        print("%-4d %-14s %-22s %8d %7.2f%%"
              % (i, sc["zh"][i], sc["en"][i], counts[i], 100.0 * counts[i] / total))
    if unknown:
        print("!! 有 %d 个像素的颜色不在该场景调色板里，不是本工具写出的分类图" % unknown)
        return 1

    png = Path(args.png)
    if args.write:
        stats = png.parent / "class_stats.csv"
        with stats.open("w", newline="", encoding="utf-8-sig") as fh:
            wr = csv.writer(fh)
            wr.writerow(["class_id", "name_zh", "name_en", "pixels", "ratio"])
            for i in sorted(counts, key=lambda k: -counts[k]):
                wr.writerow([i, sc["zh"][i], sc["en"][i], counts[i], "%.6f" % (counts[i] / total)])
        summary_path = png.parent / "summary.json"
        summary = {}
        if summary_path.exists():
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary.update(
            w=width, h=height, done=total, total=total,
            classes=[dict(id=i, name_zh=sc["zh"][i], name_en=sc["en"][i], pixels=counts[i])
                     for i in sorted(counts, key=lambda k: -counts[k])],
            stats_source="recomputed from class_map.png (tools/class_stats_from_png.py)")
        summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print("已更正：", stats, "/", summary_path)
    return 0


def hexcolor(text):
    return text


if __name__ == "__main__":
    sys.exit(main())
