# -*- coding: utf-8 -*-
"""等一个 HTTP 地址就绪（默认只判 200），用于启动器里等控制台起来。

    D:\\Anaconda\\python.exe tools\\wait_http.py --url http://127.0.0.1:8765/ --timeout 40
退出码：0 就绪；1 超时。
"""
import argparse
import sys
import time
import urllib.request


def main(argv=None):
    ap = argparse.ArgumentParser(description="等 HTTP 服务就绪")
    ap.add_argument("--url", required=True)
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(args.url, timeout=2) as resp:
                if 200 <= resp.status < 400:
                    if not args.quiet:
                        print("就绪：%s（%d）" % (args.url, resp.status))
                    return 0
        except Exception:                        # noqa: BLE001
            pass
        time.sleep(0.5)
    if not args.quiet:
        print("超时：%s 在 %.0f 秒内没有响应" % (args.url, args.timeout))
    return 1


if __name__ == "__main__":
    sys.exit(main())
