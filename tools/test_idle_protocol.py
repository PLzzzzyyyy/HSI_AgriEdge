"""S2a offline-only codec/boundary checks. Never imports sockets or runs lwIP."""
import argparse
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ["src/ps/net/idle_protocol.h", "src/ps/net/idle_protocol.cpp",
           "src/ps/net/idle_lwip.h", "src/ps/net/idle_lwip.cpp",
           "sim/host/test_idle_protocol.cpp", "tools/test_idle_protocol.py"]


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def encode_ping(task, seq, t_us, session):
    # struct enforces unsigned ranges, with no implicit masking/truncation.
    return struct.pack("<HBBHHII", 0x4548, 5, 1, task, seq, t_us, session)


def decode(data):
    if len(data) < 12:
        raise ValueError("short header")
    magic, kind, ver, task, seq, t_us = struct.unpack_from("<HBBHHI", data)
    if magic != 0x4548 or ver != 1 or kind not in (5, 0x84, 0x82):
        raise ValueError("unsupported idle header")
    expected = {5: 16, 0x84: 24, 0x82: 92}[kind]
    if len(data) != expected:
        raise ValueError("exact size required")
    result = dict(kind=kind, task=task, seq=seq, t_us=t_us)
    if kind == 5:
        result["session"], = struct.unpack_from("<I", data, 12)
    elif kind == 0x84:
        ping_seq, pad, t1, t2 = struct.unpack_from("<HHII", data, 12)
        if pad:
            raise ValueError("PONG pad")
        result.update(ping_seq=ping_seq, t1=t1, t2=t2)
    else:
        done, total, ms, temp, power, state, flags, pad = struct.unpack_from("<IIfffBBH", data, 12)
        tail = struct.unpack_from("<IIIHBB8IHHI", data, 36)
        if pad or tail[5] or tail[15] or tail[4] & ~3:
            raise ValueError("STATUS reserved fields")
        # This is an idle-subset decoder, not the future gcs/general v1 codec.
        if any((task, done, total, state, flags, tail[2], tail[3], tail[9], tail[13])):
            raise ValueError("not an idle status")
        if not all(math.isnan(v) for v in (ms, temp, power)):
            raise ValueError("S2a metrics must be explicitly unavailable")
        result.update(done=done, total=total, metrics=None, tail=tail)
    return result


def independent_checks(text):
    fields = dict(line.split("=", 1) for line in text.splitlines())
    assert fields["result"] == "PASS"
    ping = encode_ping(65535, 65534, 0x89abcdef, 0x10203040)
    assert bytes.fromhex(fields["ping"]) == ping
    pong = (struct.pack("<HBBHHI", 0x4548, 0x84, 1, 0, 0, 0x130) +
            struct.pack("<HHII", 65534, 0, 0x89abcdef, 0x123))
    assert bytes.fromhex(fields["pong"]) == pong
    # All fields encoded independently from the documented offsets, not C++ structs.
    status = (struct.pack("<HBBHHI", 0x4548, 0x82, 1, 0, 1, 0x140) +
              struct.pack("<5IBBH", 0, 0, 0x7fc00000, 0x7fc00000, 0x7fc00000, 0, 0, 0) +
              struct.pack("<IIIHBB8IHHI", 0x12345678, 0x10203040, 0, 0, 1, 0,
                          1, 24, 0, 0, 1, 0, 0, 0, 0, 0, 0))
    assert bytes.fromhex(fields["status"]) == status
    assert decode(ping)["session"] == 0x10203040
    assert decode(pong)["t2"] == 0x123
    assert decode(status)["metrics"] is None
    rejected = 0
    invalid = []
    for packet in (ping, pong, status):
        invalid.extend(packet[:n] for n in range(len(packet)))
        invalid.append(packet + b"\0")
        for offset, value in ((0, 0), (2, 0xff), (3, 0), (3, 2)):
            b = bytearray(packet); b[offset] = value; invalid.append(bytes(b))
    for offset in (14,):
        b = bytearray(pong); b[offset] = 1; invalid.append(bytes(b))
    for offset in (34, 51, 86, 50, 32, 33, 12, 44, 48, 64, 80, 20):
        b = bytearray(status)
        if offset == 50:
            b[offset] = 4
        elif offset == 20:
            b[20:24] = bytes(4)
        else:
            b[offset] = 1
        invalid.append(bytes(b))
    for packet in invalid:
        try:
            decode(packet)
        except ValueError:
            rejected += 1
        else:
            raise AssertionError(f"accepted bad packet: {packet.hex()}")
    for i, limit in enumerate((65535, 65535, 0xffffffff, 0xffffffff)):
        for value in (-1, limit + 1):
            args = [0, 0, 0, 0]; args[i] = value
            try:
                encode_ping(*args)
            except struct.error:
                rejected += 1
            else:
                raise AssertionError("unsigned overflow accepted")
    return dict(cpp_checks=int(fields["checks"]), cpp_rejected=int(fields["rejected_datagrams"]),
                independent_vectors=3, python_rejected=rejected)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--verify", type=Path, help="verify a receipt without compiling/running")
    ap.add_argument("--cxx", default="D:/mingw64/bin/g++.exe")
    ap.add_argument("--a53-cxx", default="D:/xilinx/Vitis/2020.2/gnu/aarch64/nt/aarch64-none/bin/aarch64-none-elf-g++.exe")
    ap.add_argument("--bsp-include", type=Path, default=ROOT / "vitis/s1b_m3a_plat/psu_cortexa53_0/standalone_domain/bsp/psu_cortexa53_0/include")
    args = ap.parse_args()
    if args.verify:
        receipt = json.loads((args.verify / "result.json").read_text(encoding="utf-8"))
        for entry in receipt["inputs"]:
            p = Path(entry["path"])
            if not p.is_absolute():
                p = ROOT / p
            assert sha(p) == entry["sha256"], p
        for name, digest in receipt["artifacts"].items():
            assert sha(args.verify / name) == digest, name
        print("receipt hashes verified; no tests, network or board execution")
        return
    out = (args.out or ROOT / "build/host" / datetime.now().strftime("s2a_%Y%m%d_%H%M%S")).resolve()
    out.mkdir(parents=True, exist_ok=False)
    inputs = [ROOT / p for p in SOURCES]
    # Read only actual BSP headers; never invoke its Makefile or touch user outputs.
    inputs += [args.bsp_include / p for p in ("lwipopts.h", "lwip/udp.h", "lwip/pbuf.h", "lwip/ip_addr.h", "xtime_l.h", "xparameters.h")]
    receipt = dict(scope="S2a pure bytes/boundaries + A53 syntax only; NOT network/board/App build",
                   started=datetime.now().astimezone().isoformat(), result="RUNNING", commands=[],
                   inputs=[dict(path=p.relative_to(ROOT).as_posix() if p.is_relative_to(ROOT) else str(p), sha256=sha(p)) for p in inputs])
    def run(name, cmd):
        cp = subprocess.run(cmd, cwd=ROOT, text=True, encoding="utf-8", errors="replace", stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (out / name).write_text(cp.stdout, encoding="utf-8")
        receipt["commands"].append(dict(argv=cmd, returncode=cp.returncode, log=name))
        if cp.returncode:
            raise RuntimeError(f"{name} failed: {cp.stdout}")
        return cp.stdout
    try:
        run("native_version.txt", [args.cxx, "--version"])
        run("a53_version.txt", [args.a53_cxx, "--version"])
        exe = out / "test_idle_protocol.exe"
        flags = ["-std=c++11", "-Wall", "-Wextra", "-Werror", "-pedantic"]
        run("compile.txt", [args.cxx, *flags, "-O2", "-Isrc/ps/net", "sim/host/test_idle_protocol.cpp", "src/ps/net/idle_protocol.cpp", "-o", str(exe)])
        text = run("codec.txt", [str(exe)])
        receipt["checks"] = independent_checks(text)
        run("a53_syntax.txt", [args.a53_cxx, *flags, "-mcpu=cortex-a53", "-fsyntax-only", "-Isrc/ps/net", "-isystem", str(args.bsp_include), "src/ps/net/idle_protocol.cpp", "src/ps/net/idle_lwip.cpp"])
        receipt["result"] = "PASS"
    except Exception as e:
        receipt["result"] = "FAIL"
        receipt["error"] = str(e)
        raise
    finally:
        receipt["finished"] = datetime.now().astimezone().isoformat()
        receipt["artifacts"] = {p.name: sha(p) for p in out.iterdir() if p.is_file()}
        (out / "result.json").write_text(json.dumps(receipt, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
        print(json.dumps(receipt, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
