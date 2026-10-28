"""地面站 ↔ 板卡 UDP 协议 草案 v0（E2 定稿后搬到 docs/protocol.md，板上 src/ps/net/ 按此实现）。

全部小端。每个包 12 字节公共头：
    u16 magic 0x4548 ('HE') | u8 type | u8 ver(=0) | u16 task | u16 seq | u32 reserved
地面站 → 板卡（板卡端口 BOARD_PORT）：
    0x01 START   u8 mode | u8 scene | u8 weights | u8 pad | u16 row0 | u16 col0 | u16 rows | u16 cols
                 mode 0 整景 / 1 区域 / 2 单点 / 3 评测；整景时 rect 忽略；scene、weights 是板上 SD 目录的序号
    0x02 STOP    （无载荷）
    0x03 PAUSE / 0x04 RESUME
    0x10 WCHUNK  u8 scene | u8 slot | u16 pad | u32 offset | u32 total | u32 crc32(整包) | 载荷 ≤ 1400 B
                 权重包 = weights_all | cls_token | pos_embed | classifier_w | classifier_b 顺序拼接
板卡 → 地面站（地面站端口 GCS_PORT）：
    0x81 ROW     u16 row | u16 col0 | u16 n | u16 pad | n × u32（与 tt_engine_regs.h CLASS 输出同字：
                 [7:0] 类别号 0 起，[31:16] 置信度 Q0.16）；一行超过 PAYLOAD 时按列切成多包
    0x82 STATUS  u32 done | u32 total | f32 ms_per_px(PL 计时) | f32 temp_c | f32 power_w | u8 state | u8 flags | u16 pad
                 state 0 空闲 / 1 运行 / 2 暂停 / 3 完成；flags bit0 = 模拟板（gcs/fake_board.py）
    0x83 ACK     u8 acked_type | u8 code(0 成功) | u16 pad | u32 value（WCHUNK 为已收字节）
"""
import struct
import zlib

MAGIC = 0x4548
BOARD_PORT, GCS_PORT = 5010, 5011
PAYLOAD = 1400
HDR = struct.Struct('<HBBHHI')

START, STOP, PAUSE, RESUME, WCHUNK = 0x01, 0x02, 0x03, 0x04, 0x10
ROW, STATUS, ACK = 0x81, 0x82, 0x83

START_B = struct.Struct('<BBBBHHHH')
WCHUNK_B = struct.Struct('<BBHIII')
ROW_B = struct.Struct('<HHHH')
STATUS_B = struct.Struct('<IIfffBBH')
ACK_B = struct.Struct('<BBHI')
ROW_MAX = (PAYLOAD - ROW_B.size) // 4

MODES = {'scan': 0, 'region': 1, 'probe': 2, 'eval': 3}


def pack(t, task, seq, body=b''):
    return HDR.pack(MAGIC, t, 0, task & 0xFFFF, seq & 0xFFFF, 0) + body


def unpack(data):
    if len(data) < HDR.size:
        return None
    magic, t, ver, task, seq, _ = HDR.unpack_from(data)
    if magic != MAGIC:
        return None
    return t, task, seq, data[HDR.size:]


def encode_class(labels0, conf):
    """labels 0 起、conf 0～1 → CLASS 字。"""
    import numpy as np
    q = np.minimum(np.round(np.asarray(conf, np.float64) * 65536), 65535).astype(np.uint32)
    return (np.asarray(labels0, np.uint32) & 0xFF) | (q << 16)


def decode_class(words):
    import numpy as np
    w = np.frombuffer(words, dtype='<u4')
    return (w & 0xFF).astype(np.uint8), (w >> 16).astype(np.float32) / 65536.0


def weight_chunks(pkg, scene, slot):
    crc = zlib.crc32(pkg) & 0xFFFFFFFF
    for off in range(0, len(pkg), PAYLOAD - WCHUNK_B.size):
        part = pkg[off:off + PAYLOAD - WCHUNK_B.size]
        yield off, WCHUNK_B.pack(scene, slot, 0, off, len(pkg), crc) + part
