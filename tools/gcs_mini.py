# -*- coding: utf-8 -*-
"""小地面站：在 PC 上跑整幅（或一块 ROI）分类，实时画分类图 + 类别统计。

板卡单独上电只会「等待任务」；选模型和下发任务本来由地面站做，这里按
docs/protocol.md 实现同样的最小闭环，并把结果实时画出来：

    D:\\Anaconda\\python.exe tools\\gcs_mini.py                 # 打开窗口
    D:\\Anaconda\\python.exe tools\\gcs_mini.py --selftest      # 不弹窗，跑一遍 5x3 自检

窗口里：选场景 → 选区域（整幅 / 5x3 / 64x64 / 128x128 / 256x256）→ 点「开始」。
左边是分类图（按类别上色，逐行实时刷新），右边是进度与类别统计。
板卡还没选模型时工具会先发 WACT 自动选中（LongKou v2，wcrc=27231983）。

速度参考：实测 4.4 ms/像素（int16 引擎）——整幅 LongKou 400x550 约 16 分钟，
64x64 约 18 秒。不想等就先用小块演示，再挂整幅让它慢慢跑。
"""

import argparse
import csv
import json
import math
import queue
import socket
import struct
import sys
import threading
import time
import zlib
from pathlib import Path

HDR = struct.Struct("<HBBHHI")
MAGIC = 0x4548
PING, START, STOP, INFO, WACT, PROBE = 0x05, 0x01, 0x02, 0x07, 0x13, 0x09
ROW, STATUS, ACK, PONG, INFO_R, LOGITS = 0x81, 0x82, 0x83, 0x84, 0x86, 0x85

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WCRC = 0x27231983  # LongKou v2（SD 上登记的权重包）
STATE_ZH = {0: "空闲", 1: "运行中", 2: "暂停", 3: "已完成"}
REGIONS = ["整幅", "5x3", "64x64", "128x128", "256x256"]


# ---------- 场景/类别词表 ----------

def hexcolor(text):
    text = text.lstrip("#")
    return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))


def build_scenes():
    """从仓库里的 palette.json / longkou_v2_classes.json 取类别名与配色。

    板卡输出是 0 基类别（0..classes-1）；palette.json 是遥感数据集 1 基约定
    （0 号是 unlabeled），所以取色和取英文名都要 +1。
    """
    zh = {}
    try:
        doc = json.loads((ROOT / "gcs/web/longkou_v2_classes.json").read_text(encoding="utf-8"))
        zh = {int(c["id"]): c["name_zh"] for c in doc["classes"]}
    except Exception:
        zh = {}
    scenes = {}
    table = [("longkou", "LongKou 龙口"), ("honghu", "HongHu 洪湖"), ("hanchuan", "HanChuan 汉川")]
    for idx, (key, label) in enumerate(table):
        try:
            pal = json.loads((ROOT / ("gcs/scenes/%s/palette.json" % key)).read_text(encoding="utf-8"))
        except Exception:
            pal = dict(height=600, width=600, classes=["?"] * 10, colors=["#000000"] * 10)
        names_en = pal["classes"][1:]
        colors = pal["colors"][1:]
        scenes[key] = dict(
            idx=idx, key=key, label=label, w=int(pal["width"]), h=int(pal["height"]),
            classes=len(names_en), en=names_en,
            # 中文名目前只有 LongKou v2 有词表（gcs/web/longkou_v2_classes.json），
            # 另外两景没有中文词表就照实显示英文，不要拿龙口的词表顶上去。
            zh=[(zh.get(i) or names_en[i]) if key == "longkou" else names_en[i]
                for i in range(len(names_en))],
            rgb=[hexcolor(c) for c in colors])
    return scenes


# ---------- 协议解析 ----------

def decode_status(d):
    done, total, ms, _temp, _power, state, _flags, _pad = struct.unpack_from("<IIfffBBH", d, 12)
    boot, session, wcrc, front, link = struct.unpack_from("<IIIHB", d, 36)
    (tx_pkts, tx_bytes, tx_fail, tx_retx, rx_pkts, rx_bad, rx_gap, rx_dup) = struct.unpack_from("<8I", d, 52)
    return dict(kind="status", task=struct.unpack_from("<H", d, 4)[0], done=done, total=total, ms=ms,
                state=state, boot=boot, session=session, wcrc=wcrc, front=front, link=link,
                tx_pkts=tx_pkts, tx_fail=tx_fail, tx_retx=tx_retx,
                rx_pkts=rx_pkts, rx_bad=rx_bad, rx_gap=rx_gap, rx_dup=rx_dup)


def decode_info(d):
    out = dict(kind="info", boot=struct.unpack_from("<I", d, 12)[0], proto=d[16], abi=d[17],
               n=d[19], session=struct.unpack_from("<I", d, 20)[0],
               task=struct.unpack_from("<H", d, 24)[0], wcrc=struct.unpack_from("<I", d, 36)[0],
               models=[])
    for i in range(d[19]):
        base = 44 + 28 * i
        if base + 28 > len(d):
            break
        out["models"].append(dict(scene=d[base], kind=d[base + 1],
                                  bytes=struct.unpack_from("<I", d, base + 4)[0],
                                  crc=struct.unpack_from("<I", d, base + 8)[0],
                                  tag=d[base + 12:base + 28].rstrip(b"\x00").decode("ascii", "replace")))
    return out


class Link(threading.Thread):
    """协议线程：PING 心跳、选模型、下发任务、收 ROW/STATUS，事件塞进 outq。"""

    def __init__(self, host, port, session, outq):
        super().__init__(daemon=True)
        self.addr = (host, port)
        self.session = session
        self.outq = outq
        self.seq = 0
        self.task = 0
        self.stop_evt = threading.Event()
        self.cmdq = queue.Queue()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("", 0))
        self.sock.settimeout(0.02)
        self.mode = "idle"          # idle | wait_model | run | done
        self.spec = None
        self.wact_at = 0.0
        self.wact_tries = 0
        self.last_wcrc = None
        self.next_ping = 0.0
        self.next_info = 0.0
        self.registry = []          # INFO_R 登记的模型条目（含每景权重包 CRC）
        self.probe_wait = None      # 已发出、等 LOGITS 的探查时刻（无响应判定用）

    def send(self, kind, body=b"", task=None):
        t = (time.perf_counter_ns() // 1000) & 0xFFFFFFFF
        self.sock.sendto(HDR.pack(MAGIC, kind, 1, self.task if task is None else task, self.seq, t) + body,
                         self.addr)
        self.seq = (self.seq + 1) & 0xFFFF

    def emit(self, event):
        self.outq.put(event)

    def start_task(self, spec):
        self.cmdq.put(("start", spec))

    def stop_task(self):
        self.cmdq.put(("stop", None))

    def probe(self, row, col, scene_idx, task=None, crc=None):
        """单点探查（PROBE 0x09）：板卡在当前这次调用结束后插算一个像素，回 LOGITS。"""
        self.cmdq.put(("probe", dict(row=int(row), col=int(col), scene=int(scene_idx),
                                     task=task, crc=crc)))

    def scene_crc(self, scene_idx):
        """该场景权重包的 CRC（来自 INFO 登记表）；优先 v2 版，否则任一已登记权重包。"""
        cands = [e for e in self.registry if e["scene"] == scene_idx and e["kind"] == 1 and e["crc"]]
        if not cands:
            return None
        for e in cands:
            if e["tag"] == "v2":
                return e["crc"]
        for e in cands:
            if "v2" in e["tag"]:
                return e["crc"]
        return cands[0]["crc"]

    def run(self):
        while not self.stop_evt.is_set():
            try:
                self._pump_rx()
                self._handle_cmd()
                now = time.monotonic()
                if now >= self.next_ping:
                    self.send(PING, struct.pack("<I", self.session))
                    self.next_ping = now + 0.25
                if now >= self.next_info:
                    self.send(INFO)
                    self.next_info = now + 3.0
                self._advance()
                if self.probe_wait and now - self.probe_wait > 8.0:
                    self.probe_wait = None
                    self.emit(dict(kind="probe_failed", text="板卡 8 秒未回探查结果（任务/权重/网络请检查）"))
            except Exception as exc:      # 线程里不抛给界面
                self.emit(dict(kind="error", text="协议线程异常：%s" % exc))
                time.sleep(0.2)
            time.sleep(0.01)

    def _pump_rx(self):
        for _ in range(64):
            try:
                data, _peer = self.sock.recvfrom(4096)
            except socket.timeout:
                return
            except OSError:
                return
            if len(data) < 12 or struct.unpack_from("<H", data, 0)[0] != MAGIC or data[3] != 1:
                continue
            kind = data[2]
            if kind == STATUS and len(data) >= 92:
                d = decode_status(data)
                self.last_wcrc = d["wcrc"]
                self.emit(d)
            elif kind == ROW and len(data) >= 20:
                row, col, n, flags = struct.unpack_from("<4H", data, 12)
                self.emit(dict(kind="row", task=struct.unpack_from("<H", data, 4)[0],
                               row=row, col=col, n=n, flags=flags,
                               words=struct.unpack_from("<%dI" % n, data, 20)))
            elif kind == ACK and len(data) >= 20:
                typ, code, acked, value = struct.unpack_from("<BBHI", data, 12)
                if typ == START and code != 0:
                    self.mode = "idle"
                if typ == PROBE:
                    self.probe_wait = None
                    if code != 0:
                        self.emit(dict(kind="probe_failed", text="板卡拒绝探查 code=%d" % code))
                self.emit(dict(kind="ack", typ=typ, code=code, seq=acked, value=value,
                               task=struct.unpack_from("<H", data, 4)[0]))
            elif kind == INFO_R:
                info = decode_info(data)
                self.registry = info["models"]
                self.emit(info)
            elif kind == LOGITS and len(data) >= 28:
                self.probe_wait = None
                seq, scene, ncls, row, col, wcrc, word = struct.unpack_from("<HBBHHII", data, 12)
                logits = struct.unpack_from("<%di" % min(ncls, 64), data, 28) if ncls <= 64 else ()
                self.emit(dict(kind="logits", seq=seq, scene=scene, ncls=ncls, row=row, col=col,
                               wcrc=wcrc, word=word, logits=logits,
                               task=struct.unpack_from("<H", data, 4)[0]))
            elif kind == PONG:
                self.emit(dict(kind="pong"))

    def _handle_cmd(self):
        try:
            cmd, spec = self.cmdq.get_nowait()
        except queue.Empty:
            return
        if cmd == "start":
            spec = dict(spec)
            if not spec.get("wcrc"):
                spec["wcrc"] = self.scene_crc(spec["scene_idx"]) or (DEFAULT_WCRC if spec["scene_idx"] == 0 else None)
            if not spec.get("wcrc"):
                self.emit(dict(kind="error", text="还没读到板卡权重表（INFO），请确认板卡在线后重试"))
                return
            self.spec = spec
            self.mode = "wait_model"
            self.wact_tries = 0
            self.wact_at = 0.0
            self.emit(dict(kind="log", text="开始：%s %dx%d 起点(%d,%d)"
                           % (spec["label"], spec["w"], spec["h"], spec["x"], spec["y"])))
        elif cmd == "stop" and self.mode == "run" and self.task:
            self.send(STOP, b"", task=self.task)
            self.emit(dict(kind="log", text="已请求停止（当前行算完生效）"))
        elif cmd == "probe":
            task = spec.get("task") or self.task
            if not task:
                self.emit(dict(kind="probe_failed", text="还没有任务：先点一次「开始」跑个任务，再单点探查"))
                return
            crc = spec.get("crc") or self.scene_crc(spec["scene"]) or (DEFAULT_WCRC if spec["scene"] == 0 else None)
            if not crc:
                self.emit(dict(kind="probe_failed", text="还没读到该场景权重表（INFO），请稍后重试"))
                return
            body = struct.pack("<BBHHHI", spec["scene"], 0, spec["row"], spec["col"], 0, crc)
            self.send(PROBE, body, task=task)
            self.probe_wait = time.monotonic()
            self.emit(dict(kind="log", text="单点探查 (行=%d, 列=%d)" % (spec["row"], spec["col"])))

    def _advance(self):
        if self.mode != "wait_model":
            return
        if self.last_wcrc == self.spec["wcrc"]:
            self._send_start()
            return
        now = time.monotonic()
        if now - self.wact_at > 2.5 and self.wact_tries < 8:
            self.send(WACT, struct.pack("<BBHI", self.spec["scene_idx"], 0, 0, self.spec["wcrc"]))
            self.wact_at = now
            self.wact_tries += 1
            if self.wact_tries == 1:
                self.emit(dict(kind="log", text="板卡还没选中该权重包，发 WACT（装入约 1~3 s）"))

    def _send_start(self):
        spec = self.spec
        self.task = spec["task"]
        body = struct.pack("<BBBBHHHHII", spec["mode"], spec["scene_idx"], 0, 0,
                           spec["y"], spec["x"], spec["h"], spec["w"], spec["wcrc"], self.session)
        self.send(START, body, task=self.task)
        self.mode = "run"
        self.emit(dict(kind="started", task=self.task))


# ---------- PNG ----------

def write_png(path, width, height, rgb):
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
    stride = width * 3
    raw = b"".join(b"\x00" + bytes(rgb[y * stride:(y + 1) * stride]) for y in range(height))
    Path(path).write_bytes(b"\x89PNG\r\n\x1a\n"
                           + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                           + chunk(b"IDAT", zlib.compress(raw, 6))
                           + chunk(b"IEND", b""))


# ---------- 界面 ----------

def make_app(args, selftest=False):
    import tkinter as tk
    from tkinter import ttk

    scenes = build_scenes()
    outq = queue.Queue()
    link = Link(args.board, args.port, int(args.session, 16), outq)

    root = tk.Tk()
    root.title("农情分析 · 板卡小地面站")
    if selftest:
        root.withdraw()
    root.geometry("1080x720")

    st = dict(spec=None, rgb=None, grid=None, counts=None, seen_rows=set(), used_tasks=set(),
              boot=0, session=int(args.session, 16), wcrc=0, task=0, status_state=0,
              ms=None, done=0, total=0, pimg=None, saved_dir=None, errors=[], saved=False)
    ctl = dict()

    top = ttk.Frame(root, padding=6)
    top.pack(side="top", fill="x")
    ttk.Label(top, text="场景").pack(side="left")
    scene_var = tk.StringVar(value=scenes[args.scene]["label"])
    scene_box = ttk.Combobox(top, textvariable=scene_var, width=16, state="readonly",
                             values=[s["label"] for s in scenes.values()])
    scene_box.pack(side="left", padx=4)
    ttk.Label(top, text="区域").pack(side="left", padx=(12, 0))
    region_var = tk.StringVar(value="整幅")
    region_box = ttk.Combobox(top, textvariable=region_var, width=10, state="readonly", values=REGIONS)
    region_box.pack(side="left", padx=4)
    btn_start = ttk.Button(top, text="开始")
    btn_start.pack(side="left", padx=(12, 2))
    btn_stop = ttk.Button(top, text="停止")
    btn_stop.pack(side="left", padx=2)
    btn_save = ttk.Button(top, text="保存结果")
    btn_save.pack(side="left", padx=2)
    head = tk.StringVar(value="未连接（板卡上电、本机设 192.168.1.102/24）")
    ttk.Label(top, textvariable=head).pack(side="left", padx=12)

    body = ttk.Frame(root)
    body.pack(side="top", fill="both", expand=True)
    left = ttk.Frame(body)
    left.pack(side="left", fill="both", expand=True)
    canvas = tk.Canvas(left, background="#101010", highlightthickness=0)
    hbar = ttk.Scrollbar(left, orient="horizontal", command=canvas.xview)
    vbar = ttk.Scrollbar(left, orient="vertical", command=canvas.yview)
    canvas.configure(xscrollcommand=hbar.set, yscrollcommand=vbar.set)
    canvas.grid(row=0, column=0, sticky="nsew")
    vbar.grid(row=0, column=1, sticky="ns")
    hbar.grid(row=1, column=0, sticky="ew")
    left.rowconfigure(0, weight=1)
    left.columnconfigure(0, weight=1)

    right = ttk.Frame(body, padding=8, width=360)
    right.pack(side="right", fill="y")
    right.pack_propagate(False)
    prog_txt = tk.StringVar(value="进度 0 / 0")
    ttk.Label(right, textvariable=prog_txt).pack(anchor="w")
    prog = ttk.Progressbar(right, maximum=100.0)
    prog.pack(fill="x", pady=(2, 6))
    ident_txt = tk.StringVar(value="")
    ttk.Label(right, textvariable=ident_txt, justify="left", font=("Consolas", 9)).pack(anchor="w")
    ttk.Separator(right).pack(fill="x", pady=4)
    ttk.Label(right, text="类别统计（板端预测，非地面真值）").pack(anchor="w")
    tree = ttk.Treeview(right, columns=("name", "px", "pct"), show="headings", height=13)
    for col, txt, wd, anchor in (("name", "类别", 168, "w"), ("px", "像素", 78, "e"), ("pct", "占比", 62, "e")):
        tree.heading(col, text=txt)
        tree.column(col, width=wd, anchor=anchor)
    tree.pack(fill="both", expand=True, pady=4)
    log_txt = tk.Text(right, height=8, width=44, state="disabled", font=("Consolas", 8))
    log_txt.pack(fill="x", pady=(4, 0))

    def log(msg):
        log_txt.configure(state="normal")
        log_txt.insert("end", "%s %s\n" % (time.strftime("%H:%M:%S"), msg))
        log_txt.see("end")
        log_txt.configure(state="disabled")

    def scene_of(label):
        for s in scenes.values():
            if s["label"] == label:
                return s
        return scenes["longkou"]

    def new_spec():
        sc = scene_of(label=scene_var.get())
        region = region_var.get()
        if region == "整幅":
            mode, w, h = 0, sc["w"], sc["h"]
        else:
            head, _, tail = region.partition("x")
            w = min(int(head), sc["w"])
            h = min(int(tail or head), sc["h"])
            mode = 1
        task = int(time.time() * 1000) % 32767 + 1
        while task in st["used_tasks"]:
            task = task % 32767 + 1
        st["used_tasks"].add(task)
        return dict(scene_idx=sc["idx"], label=sc["label"], key=sc["key"], mode=mode,
                    x=0, y=0, w=w, h=h, wcrc=None, classes=sc["classes"], task=task)

    def reset_canvas(spec, sc):
        st.update(rgb=bytearray(spec["w"] * spec["h"] * 3),
                  grid=bytearray(b"\xff") * (spec["w"] * spec["h"]),   # 0xff = 未上色
                  counts=[0] * sc["classes"], seen_rows=set(), saved=False, saved_dir=None)
        st["pimg"] = tk.PhotoImage(width=spec["w"], height=spec["h"])
        canvas.delete("all")
        canvas.create_image(0, 0, anchor="nw", image=st["pimg"])
        canvas.configure(scrollregion=(0, 0, spec["w"], spec["h"]),
                         width=min(spec["w"] + 4, 690), height=min(spec["h"] + 4, 660))

    def start():
        sc = scene_of(label=scene_var.get())
        spec = new_spec()
        st["spec"] = spec
        reset_canvas(spec, sc)
        btn_start.state(["disabled"])
        prog.configure(maximum=float(spec["w"] * spec["h"]), value=0)
        prog_txt.set("进度 0 / %d 像素" % (spec["w"] * spec["h"]))
        log("下发 task=%d %s %dx%d" % (spec["task"], spec["label"], spec["w"], spec["h"]))
        link.start_task(spec)

    def stop():
        link.stop_task()

    def save(quiet=False):
        spec = st["spec"]
        if not spec or st["rgb"] is None:
            if not quiet:
                log("还没有结果可保存")
            return None
        sc = scene_of(spec["label"])
        d = ROOT / "build/host" / time.strftime("gcs_mini_%Y%m%d_%H%M%S")
        d.mkdir(parents=True, exist_ok=True)
        write_png(d / "class_map.png", spec["w"], spec["h"], st["rgb"])
        total = sum(st["counts"]) or 1
        with (d / "class_stats.csv").open("w", newline="", encoding="utf-8-sig") as fh:
            wr = csv.writer(fh)
            wr.writerow(["class_id", "name_zh", "name_en", "pixels", "ratio"])
            for i, n in enumerate(st["counts"]):
                if n:
                    wr.writerow([i, sc["zh"][i], sc["en"][i], n, "%.6f" % (n / total)])
        info = dict(scene=sc["key"], scene_label=sc["label"], region=region_var.get(),
                    x=0, y=0, w=spec["w"], h=spec["h"], wcrc="%08x" % spec["wcrc"],
                    task=spec["task"], boot_id="%08x" % st["boot"],
                    session="%08x" % st["session"], done=st["done"], total=st["total"],
                    ms_per_px=st["ms"],
                    classes=[dict(id=i, name_zh=sc["zh"][i], name_en=sc["en"][i], pixels=n)
                             for i, n in enumerate(st["counts"])],
                    note="模型预测类别，非地面真值；温度/功率未测")
        (d / "summary.json").write_text(json.dumps(info, indent=2, ensure_ascii=False) + "\n",
                                        encoding="utf-8")
        st["saved"], st["saved_dir"] = True, str(d)
        if not quiet:
            log("已保存 %s" % d)
        return d

    def paint(row, col, words):
        """按像素上色并统计。一行可能分几个 ROW 包（宽 400 会拆成 348+52），
        所以计数必须按像素去重，不能按行去重。"""
        spec = st["spec"]
        sc = scene_of(spec["label"])
        w = spec["w"]
        cells = []
        for i, word in enumerate(words):
            cls = word & 0xFF
            if cls >= sc["classes"]:
                cls = 0
            x = col + i
            idx = row * w + x
            if x >= w or idx >= len(st["grid"]):
                break
            if st["grid"][idx] == 0xFF:
                st["counts"][cls] += 1
            st["grid"][idx] = cls
            r, g, b = sc["rgb"][cls]
            st["rgb"][idx * 3:idx * 3 + 3] = bytes((r, g, b))
            cells.append("#%02x%02x%02x" % (r, g, b))
        st["seen_rows"].add(row)
        if cells:
            st["pimg"].put("{" + " ".join(cells) + "}", to=(col, row))

    def refresh_stats():
        spec = st["spec"]
        if not spec or st["counts"] is None:
            return
        sc = scene_of(spec["label"])
        total = sum(st["counts"]) or 1
        tree.delete(*tree.get_children())
        for i in sorted(range(len(st["counts"])), key=lambda k: -st["counts"][k]):
            if st["counts"][i]:
                tree.insert("", "end", values=(sc["zh"][i], st["counts"][i],
                                               "%.2f%%" % (100.0 * st["counts"][i] / total)))

    def refresh_ident():
        spec = st["spec"]
        ident = "状态 %s   任务 %d\nboot %08x  会话 %08x\n模型 wcrc %08x\n" % (
            STATE_ZH.get(st["status_state"], "?"), st["task"], st["boot"], st["session"], st["wcrc"])
        if spec:
            ident += "区域 %s %dx%d\n" % (spec["label"], spec["w"], spec["h"])
        if st["ms"] is not None:
            eta = max(st["total"] - st["done"], 0) * st["ms"] / 1000.0
            ident += "速度 %.2f ms/像素   剩余约 %s\n" % (st["ms"], time.strftime("%M:%S", time.gmtime(eta)))
        ident_txt.set(ident)

    def pump():
        dirty = False
        while True:
            try:
                ev = outq.get_nowait()
            except queue.Empty:
                break
            k = ev["kind"]
            if k == "status":
                prev = st["status_state"]
                st.update(boot=ev["boot"], wcrc=ev["wcrc"], status_state=ev["state"],
                          ms=ev["ms"] if math.isfinite(ev["ms"]) else None,
                          done=ev["done"], total=ev["total"])
                if ev["session"]:
                    st["session"] = ev["session"]
                if st["spec"] and ev["task"] == st["spec"]["task"]:
                    st["task"] = ev["task"]
                    if ev["total"]:
                        prog.configure(maximum=float(ev["total"]))
                    prog.configure(value=float(ev["done"]))
                    prog_txt.set("进度 %d / %d 像素（%d 行）" % (ev["done"], ev["total"], ev["front"]))
                    if ev["state"] == 3 and prev != 3:
                        log("完成 done=%d/%d" % (ev["done"], ev["total"]))
                        refresh_stats()
                        save()
                        btn_start.state(["!disabled"])
                    dirty = True
                elif ev["task"] and ev["task"] != st["task"]:
                    st["task"] = ev["task"]
                head.set("已连接 %s:%d · boot %08x · 模型 %08x"
                         % (args.board, args.port, st["boot"], st["wcrc"]))
                refresh_ident()
            elif k == "row":
                if st["spec"] and ev["task"] == st["spec"]["task"] and st["pimg"] is not None:
                    paint(ev["row"], ev["col"], ev["words"])
                    dirty = True
            elif k == "ack":
                names = {START: "START", STOP: "STOP", WACT: "WACT", PING: "PING", PROBE: "PROBE"}
                log("ACK %s code=%d value=%s"
                    % (names.get(ev["typ"], hex(ev["typ"])), ev["code"], ev["value"]))
                if ev["code"] != 0:
                    log("板卡拒绝：5=没有该权重 8=参数非法 9=任务号不符/还在跑")
                    btn_start.state(["!disabled"])
            elif k == "info":
                st["boot"] = ev["boot"]
                tags = ["%s" % m["tag"] for m in ev["models"] if m["kind"] == 1][:3]
                head.set("已连接 · boot %08x · SD 上登记 %d 个权重包 %s"
                         % (ev["boot"], ev["n"], " ".join(tags)))
            elif k == "error":
                st["errors"].append(ev["text"])
                log(ev["text"])
            elif k == "log":
                log(ev["text"])
        if dirty:
            refresh_stats()
        root.after(80, pump)

    btn_start.configure(command=start)
    btn_stop.configure(command=stop)
    btn_save.configure(command=save)
    ctl.update(start=start, stop=stop, save=save, set_region=region_var.set,
               set_scene=lambda label: scene_var.set(label), region_var=region_var)

    link.start()
    root.after(80, pump)
    return dict(root=root, st=st, link=link, ctl=ctl, scenes=scenes, log=log)


def main(argv=None):
    ap = argparse.ArgumentParser(description="板卡小地面站（实时分类图 + 类别统计）")
    ap.add_argument("--board", default="192.168.1.10")
    ap.add_argument("--port", type=int, default=5010)
    ap.add_argument("--session", default="5a5a0001", help="会话号；板卡已被别的会话锁住就改这里")
    ap.add_argument("--scene", default="longkou", choices=("longkou", "honghu", "hanchuan"))
    ap.add_argument("--selftest", action="store_true", help="不弹窗，跑一遍小块并保存结果")
    ap.add_argument("--selftest-region", default="64x64")
    ap.add_argument("--selftest-timeout", type=float, default=180.0)
    args = ap.parse_args(argv)

    app = make_app(args, selftest=args.selftest)
    if not args.selftest:
        app["root"].mainloop()
        app["link"].stop_evt.set()
        return 0

    app["ctl"]["set_region"]("整幅" if args.selftest_region.lower() in ("full", "all", "整幅")
                             else args.selftest_region)
    app["ctl"]["start"]()
    deadline = time.time() + args.selftest_timeout
    while time.time() < deadline and not app["st"]["saved"]:
        app["root"].update()
        time.sleep(0.05)
    app["link"].stop_evt.set()
    st = app["st"]
    ok = st["saved"] and not st["errors"]
    print("selftest:", "PASS" if ok else "FAIL",
          "done=%d/%d rows=%d errors=%s" % (st["done"], st["total"], len(st["seen_rows"]), st["errors"]))
    if st["saved_dir"]:
        print("saved:", st["saved_dir"])
    app["root"].destroy()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
