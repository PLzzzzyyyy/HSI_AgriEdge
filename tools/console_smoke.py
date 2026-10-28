# -*- coding: utf-8 -*-
"""客户端自测：通过原版控制台的 WebSocket 下发一个 5x3 任务，任务完成后做单点探查。

只用于验证「原版控制台（8765）在本地演示模式下能否真正驱动板卡」，不写任何证据文件。

    D:\\Anaconda\\python.exe tools\\console_smoke.py
    ... --rect 0 0 3 5 --scene longkou --version v2
"""
import argparse
import asyncio
import json
import time
import urllib.request

import websockets

BASE = "http://127.0.0.1:8765"


def post(path, body):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


async def run(args):
    url = "ws://127.0.0.1:8765/ws"
    async with websockets.connect(url, max_size=2 ** 26) as ws:
        hello = json.loads(await ws.recv())
        src = hello.get("source") or {}
        print("hello: boot=%s authorized=%s capabilities=%s"
              % (src.get("boot_id"), src.get("authorized"), src.get("capabilities")))
        if not src.get("authorized"):
            print("!! 板卡未授权，先在控制台点「连接板卡」")
            return 1
        cmd = dict(cmd="start", kind="region", scene=args.scene, version=args.version,
                   rect=[args.rect[0], args.rect[1], args.rect[2], args.rect[3]], pace_rows=0)
        print("start:", cmd)
        await ws.send(json.dumps(cmd))
        rid = None
        deadline = time.time() + args.timeout
        last_status = None
        while time.time() < deadline:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=5)
            except asyncio.TimeoutError:
                continue
            if isinstance(msg, bytes):
                continue
            ev = json.loads(msg)
            t = ev.get("type")
            if t in ("run_start", "run_end") or t == "run":
                r = ev["run"]
                rid = r["id"]
                mark = (r["id"], r["status"], r.get("done"), r.get("total"))
                if mark != last_status:
                    print("run %s status=%s done=%s/%s rows=%s"
                          % (r["id"], r["status"], r.get("done"), r.get("total"), r.get("row")))
                    last_status = mark
                if r["status"] in ("done", "error", "stopped", "cancelled") and t != "run_start":
                    if r["status"] != "done":
                        print("run ended:", json.dumps(ev, ensure_ascii=False)[:400])
                    break
            elif t == "command_error":
                print("command_error:", json.dumps(ev, ensure_ascii=False)[:400])
                return 1
        if rid is None:
            print("没有拿到 run id")
            return 1
        try:
            res = post("/api/run/%d/board/probe" % rid, dict(row=args.rect[0] + 1, col=args.rect[1] + 1))
        except Exception as exc:                     # noqa: BLE001
            print("probe HTTP 失败:", exc)
            return 1
        print("probe 结果:", json.dumps(res, ensure_ascii=False)[:600])
        return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", default="longkou")
    ap.add_argument("--version", default="v2")
    ap.add_argument("--rect", type=int, nargs=4, default=[0, 0, 3, 5], metavar=("R0", "C0", "H", "W"))
    ap.add_argument("--timeout", type=float, default=120)
    args = ap.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
