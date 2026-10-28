#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
给 Vitis HLS cosim 生成的 AXI master 行为模型打补丁：越界访问不再 $finish。

为什么需要：
  std_conv 的 load_input 在特征图左上角做 P=1 的 padding 时，会读到
  `in1 + base_addr2`，而 base_addr2 = (fm_row-P)*fm_size + (fm_col-P) = -(fm_size+1)。
  真实硬件上 in1 指向 DDR，往前读几十个元素完全无害 —— 读到的值随后被
  load_input 里的边界判断整片丢弃。
  但 cosim 的 AESL_axi_master_*.v 里有一句硬性检查：

      if (FIFO_AR_req_ADDR_tmp/data_byte_size > FM1_mem_depth) begin
          $display ("... Read request address %d exceed AXI master FM1 array depth: %d", ...);
          $finish;                                   <- 整个仿真在 2425ns 停掉
      end

  于是这个设计根本没法跑到出结果。

这样改是安全的，不是糊弄 —— 负地址与被丢弃的元素一一对应：
  地址 = base_addr2 + rr*fm_size + cc = -27 + 26*rr + cc   (fsize=26, stride=2)
  保留条件 = (rr>=P && rr<fm_size+P && cc>=P && cc<fm_size+P) = (rr>=1 && cc>=1)
    rr=0     -> 地址 -27..-1 全负，而整行 rr=0 都被丢弃           ✓
    rr=1     -> 只有 cc=0 时地址 -1，而 cc=0 正好被丢弃            ✓
    rr>=2    -> 地址 >= 25，全部合法                              ✓
  去掉 $finish 后，越界读按 Verilog 语义返回 X，正好落在被丢弃的位置。

⚠ 千万不要改成"把地址钳到 0"：
  这些读是【整行一次 burst】（load_input 的 cc 循环被推断成 burst）。
  钳位起始地址会把 rr=1 那一整行的数据整体挪位，得到静悄悄的错误结果 ——
  比直接 $finish 糟糕得多。只能让越界的那几拍返回 X。

用法（在 cosim 生成完之后、跑 xsim 之前）：
  python tools/patch_cosim_axi_master.py hls/conv_prj_cosim/sol_cosim/sim/verilog

  然后手工跑：
    cd <sim/verilog> && run_xsim.bat
    cd <sim/wrapc_pc> && cosim.pc.exe

  ⚠ 每次 cosim_design 都会重新生成这些文件，补丁会被冲掉，要重打。
    所以别用 `cosim_design`（它生成完直接就跑），用 `cosim_design -setup`
    只生成不跑，打完补丁再手工跑。
"""
import os
import re
import sys

MARK = "// [patched by patch_cosim_axi_master.py] $finish removed: "


def patch_file(path):
    with open(path, "rb") as f:
        text = f.read().decode("utf-8", errors="replace")

    if MARK in text:
        return None  # 已经打过

    lines = text.split("\n")
    out = []
    hits = 0
    i = 0
    while i < len(lines):
        out.append(lines[i])
        if "exceed AXI master" in lines[i]:
            # 紧随其后的那句 $finish; 才是要拿掉的，别误伤别处的 $finish
            j = i + 1
            while j < len(lines) and lines[j].strip() == "":
                out.append(lines[j])
                j += 1
            if j < len(lines) and re.match(r"^\s*\$finish\s*;\s*$", lines[j]):
                indent = re.match(r"^(\s*)", lines[j]).group(1)
                out.append(indent + MARK + "越界读返回 X，随后被 load_input 的边界判断丢弃")
                hits += 1
                i = j + 1
                continue
            i = j
            continue
        i += 1

    if hits == 0:
        return 0

    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out))
    return hits


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    simdir = sys.argv[1]
    if not os.path.isdir(simdir):
        print("目录不存在：%s" % simdir)
        return 1

    names = sorted(n for n in os.listdir(simdir)
                   if n.startswith("AESL_axi_master_") and n.endswith(".v"))
    if not names:
        print("✗ %s 下没有 AESL_axi_master_*.v —— cosim 文件还没生成？"
              "先跑 cosim_design -setup" % simdir)
        return 1

    total = 0
    for n in names:
        r = patch_file(os.path.join(simdir, n))
        if r is None:
            print("  - %-28s 已打过补丁，跳过" % n)
        elif r == 0:
            print("  ⚠ %-28s 没找到越界检查，格式可能变了" % n)
        else:
            print("  ✓ %-28s 去掉 %d 处 $finish" % (n, r))
            total += r

    print("\n共去掉 %d 处 $finish。现在可以跑 run_xsim.bat 了。" % total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
