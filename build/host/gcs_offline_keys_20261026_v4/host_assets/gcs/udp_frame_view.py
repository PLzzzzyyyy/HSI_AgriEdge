"""
4.0b PC 端：接收板子发来的 UDP 帧并实时显示。

用法：
    D:\\pytorch\\python.exe tools\\udp_frame_view.py

板子那边：编译宏加 CAM_STREAM_ONLY，Build -> Run（第一次勾 Program FPGA）。

前置条件（这两条不满足就一个包都收不到，而且不会有任何报错）：
  1. PC 网卡设成 192.168.1.102 / 255.255.255.0
     板子把包发到这个写死的地址，见 src/ps/reference/net_udp.cpp 的 PC_IP_*。
     板上没跑 DHCP，所以两边都得是静态 IP。
  2. Windows 防火墙允许本程序的 UDP 入站（第一次运行会弹窗，选"允许"）

包格式见 src/ps/reference/net_udp.h：
    u16 magic(0x5A5A) | u16 frame_id | u16 pkt_id | u16 pkt_total | payload(<=1440)
全部小端。一帧 640*480*3 = 921600 字节 = 640 包。

⚠ PAYLOAD 必须与板上 net_udp.h 的 NET_PAYLOAD 一致 —— PC 端按
  pkt_id * PAYLOAD 算写入偏移，两边不一致会拼出错位的花屏（不是丢包）。
  2026-08-30 从 1024 改成 1440，旧固件配新脚本、或反过来，都会花屏。

键盘：q 退出，s 存当前帧到 results/。
"""

import argparse
import os
import socket
import struct
import sys
import time

import cv2
import numpy as np

HDR = struct.Struct("<HHHH")
HDR_BYTES = 8
MAGIC = 0x5A5A
PAYLOAD = 1440          # 必须与 net_udp.h 的 NET_PAYLOAD 一致（不一致=花屏，不是丢包）

# ---- 4.1 检测框包（与帧包共用一个 socket，靠 magic 区分）----
# 头: u16 magic | u16 frame_id | u16 n_box | u16 reserved
# 每框 12 字节: s16 left,top,right,bottom | u16 score_milli | u8 cls | u8 pad
MAGIC_BOX = 0x5B5B
BOX = struct.Struct("<hhhhHBB")

# 类名只在 PC 端保存，线上只走索引（省带宽、省板上代码）。
# 顺序必须与 pose6d_fpga 的 vitis/app/src/detect.cpp 的 voc_class_name 完全一致。
VOC_CLASSES = [
    "aeroplane", "bicycle", "bird", "boat", "bottle",
    "bus", "car", "cat", "chair", "cow",
    "diningtable", "dog", "horse", "motorbike", "person",
    "pottedplant", "sheep", "sofa", "train", "tvmonitor",
]


def class_color(cls):
    """按类别给一个稳定的颜色（BGR）。用 HSV 均匀取色，与教程 predict.py 同思路。"""
    import colorsys
    r, g, b = colorsys.hsv_to_rgb((cls % 20) / 20.0, 1.0, 1.0)
    return (int(b * 255), int(g * 255), int(r * 255))


def draw_boxes(img, boxes):
    """在原始分辨率的图上画框。boxes = [(left,top,right,bottom,score_milli,cls)]"""
    for left, top, right, bottom, score, cls in boxes:
        color = class_color(cls)
        cv2.rectangle(img, (left, top), (right, bottom), color, 2)
        name = VOC_CLASSES[cls] if 0 <= cls < len(VOC_CLASSES) else f"cls{cls}"
        label = f"{name} {score / 1000:.3f}"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
        ly = max(top - 4, th + 4)
        cv2.rectangle(img, (left, ly - th - 4), (left + tw + 4, ly + 2), color, -1)
        cv2.putText(img, label, (left + 2, ly - 2), cv2.FONT_HERSHEY_SIMPLEX,
                    0.45, (0, 0, 0), 1, cv2.LINE_AA)
    return img


DEF_W, DEF_H, BPP = 640, 480, 3

# ⚠ 别用 5001：本机 NI 的 nidmsrv 服务常驻占着它，bind 会报 WinError 10048。
#   例程 43 用的就是 5001，照抄会撞。6001 也被占（实测）。
#   50001 在私有端口范围，最不容易再撞。
#   改这里的话，src/ps/reference/net_udp.cpp 的 UDP_PORT 必须跟着改。
DEF_PORT = 50001


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=DEF_PORT)
    ap.add_argument("--width", type=int, default=DEF_W)
    ap.add_argument("--height", type=int, default=DEF_H)
    ap.add_argument("--swap-rb", action="store_true",
                    help="交换 R/B 通道。板上内存实测是 BGR，正好是 cv2 要的顺序，"
                         "默认不交换；如果画面里蓝红反了就加这个开关")
    ap.add_argument("--scale", type=float, default=1.0, help="显示缩放倍数")
    args = ap.parse_args()

    w, h = args.width, args.height
    frame_bytes = w * h * BPP
    n_pkt_expect = (frame_bytes + PAYLOAD - 1) // PAYLOAD

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # 900 包 x 1032 字节 = 928 KB 会一次性涌进来。
    # 默认收缓冲（Windows 上通常 64KB）装不下，Python 还没来得及取就被内核丢了,
    # 表现是"每帧总缺几十个包"，很像板子发漏了 —— 其实是这里。
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 << 20)
    try:
        sock.bind(("0.0.0.0", args.port))
    except OSError as e:
        print(f"bind UDP {args.port} 失败: {e}")
        print("  端口被别的程序占了。查是谁：")
        print(f"    Get-NetUDPEndpoint -LocalPort {args.port} | "
              "%{ Get-Process -Id $_.OwningProcess }")
        print("  换端口的话 src/ps/reference/net_udp.cpp 的 UDP_PORT 要跟着改，"
              "两边必须一致。")
        sys.exit(1)
    sock.settimeout(2.0)

    rcvbuf = sock.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF)
    print(f"listening on UDP {args.port}")
    print(f"  SO_RCVBUF = {rcvbuf / 1024:.0f} KB")
    print(f"  expecting {w}x{h}x{BPP} = {frame_bytes} bytes = {n_pkt_expect} packets/frame")
    print("  waiting for the board... (q to quit, s to save)")

    buf = bytearray(frame_bytes)
    seen = None
    cur_id = None
    cur_total = 0

    n_frames = 0            # 完整收到的帧
    n_partial = 0           # 缺包的帧
    n_lost_pkts = 0         # 累计缺的包数
    last_img = None
    cur_boxes = []          # 4.1：最近一次收到的检测框
    box_fid = None           # 那组框属于哪一帧
    n_boxpkt = 0
    t_fps = time.time()
    fps_frames = 0
    fps = 0.0
    win = "pose6d 4.0b  camera -> UDP -> PC"

    def finish(complete):
        """当前帧收尾：拼成图、更新统计。complete 表示是否收满。"""
        nonlocal n_frames, n_partial, n_lost_pkts, last_img, fps_frames
        missing = int(cur_total - seen.sum()) if seen is not None else 0
        if complete:
            n_frames += 1
        else:
            n_partial += 1
            n_lost_pkts += missing

        img = np.frombuffer(bytes(buf), dtype=np.uint8).reshape(h, w, BPP)
        if args.swap_rb:
            img = img[:, :, ::-1]
        last_img = img.copy()
        fps_frames += 1
        return missing

    try:
        while True:
            try:
                pkt = sock.recv(2048)
            except socket.timeout:
                print("no data for 2s -- board running? cable in? IP = 192.168.1.102?")
                continue

            if len(pkt) < HDR_BYTES:
                continue
            magic, fid, f2, f3 = HDR.unpack_from(pkt, 0)

            redraw = False

            if magic == MAGIC_BOX:
                # ---- 4.1 检测框包 ----
                # 头的第 3 个字段在框包里是 n_box（帧包里是 pkt_id）
                n_box = f2
                avail = (len(pkt) - HDR_BYTES) // BOX.size
                cur_boxes = [BOX.unpack_from(pkt, HDR_BYTES + i * BOX.size)[:6]
                             for i in range(min(n_box, avail))]
                box_fid = fid
                n_boxpkt += 1
                # ⚠ 只更新数据，**不触发重画**。
                # 4.1 里画面是每帧都发的、比框快得多（INFER_EVERY=4 时约 6fps），
                # 框最多等一帧画面就显示出来（<200ms），肉眼看不出。
                # 早先这里设了 redraw=True，结果每帧 imshow 两次 ——
                # 多出来的几毫秒里 PC 端不收包，正是 4.0b 没有、4.1 冒出来的
                # 那 0.15% 丢包。
                continue

            elif magic == MAGIC:
                # ---- 帧包 ----
                pid, ptot = f2, f3

                # 新的一帧开始 -> 先把上一帧交出去（哪怕缺包，也显示出来看看）
                if cur_id is None or fid != cur_id:
                    if cur_id is not None and seen is not None:
                        finish(bool(seen.all()))
                        redraw = True
                    cur_id = fid
                    cur_total = ptot
                    seen = np.zeros(ptot, dtype=bool)

                if pid < cur_total:
                    off = pid * PAYLOAD      # 前面的包都是满的，这样算偏移总是对的
                    payload = pkt[HDR_BYTES:]
                    if off < frame_bytes:
                        end = min(off + len(payload), frame_bytes)
                        buf[off:end] = payload[:end - off]
                        seen[pid] = True

                    if seen.all():
                        finish(True)
                        redraw = True
                        cur_id = None        # 等下一帧的第一个包
            else:
                continue                      # 杂包

            # ---- 显示。只在攒够一帧、或框刚到时做 ----
            # ⚠ 别放到每个包后面：一帧 900 个包，imshow 一次几毫秒，
            #   那样一帧要两秒多，看着像"网络很慢"，其实是这里画得太勤。
            if not redraw or last_img is None:
                continue

            now = time.time()
            if now - t_fps >= 0.5:
                fps = fps_frames / (now - t_fps)
                t_fps = now
                fps_frames = 0

            # 先在原始分辨率上画框（框坐标是相对 640x480 的），再缩放
            shown = last_img.copy()
            if cur_boxes:
                draw_boxes(shown, cur_boxes)
            if args.scale != 1.0:
                shown = cv2.resize(shown, None, fx=args.scale, fy=args.scale,
                                   interpolation=cv2.INTER_NEAREST)
            total = n_frames + n_partial
            loss = (100.0 * n_lost_pkts / (total * n_pkt_expect)) if total else 0.0
            # 分两行，别挤成一行 —— 640 宽的画面上一行放不下这么多字段
            lines = [f"{fps:4.1f} fps   {len(cur_boxes)} boxes",
                     f"{n_frames} ok / {n_partial} partial   loss {loss:.2f}%"]
            for k, line in enumerate(lines):
                y = 22 + k * 20
                cv2.putText(shown, line, (8, y), cv2.FONT_HERSHEY_SIMPLEX,
                            0.5, (0, 0, 0), 3, cv2.LINE_AA)
                cv2.putText(shown, line, (8, y), cv2.FONT_HERSHEY_SIMPLEX,
                            0.5, (0, 255, 0), 1, cv2.LINE_AA)
            cv2.imshow(win, shown)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            if key == ord("s"):
                os.makedirs("results", exist_ok=True)
                path = os.path.join("results", f"stream_{int(time.time())}.png")
                cv2.imwrite(path, last_img)
                print(f"saved {path}")

    except KeyboardInterrupt:
        pass
    finally:
        sock.close()
        cv2.destroyAllWindows()
        total = n_frames + n_partial
        print()
        print(f"frames: {n_frames} complete, {n_partial} partial")
        if total:
            print(f"packet loss: {n_lost_pkts} / {total * n_pkt_expect} "
                  f"({100.0 * n_lost_pkts / (total * n_pkt_expect):.3f}%)")
        print("if loss is high: raise pbuf_pool_size / memp_n_pbuf in the BSP")


if __name__ == "__main__":
    main()
