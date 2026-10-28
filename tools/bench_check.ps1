# ---------------------------------------------------------------------------
# 上板前自检：串口 / JTAG 下载器 / 网卡 / 要用的下板文件
#
# 用法：
#   pwsh -File tools\bench_check.ps1
#   pwsh -File tools\bench_check.ps1 -Detailed     # 连串口芯片、下载器型号一起列出来
#
# 全部就绪时退出码 0；缺东西时退出码 1，并给出该查什么。
# ---------------------------------------------------------------------------

param([switch]$Detailed)

$ErrorActionPreference = 'Continue'

$repo = (Resolve-Path "$PSScriptRoot\..").Path
$ok = $true

function Section($title) {
    Write-Host ''
    Write-Host "== $title ==" -ForegroundColor Cyan
}

function Good($msg) { Write-Host "  [OK]   $msg" -ForegroundColor Green }
function Bad($msg) { Write-Host "  [缺]   $msg" -ForegroundColor Yellow; $script:ok = $false }
function Info($msg) { Write-Host "         $msg" -ForegroundColor DarkGray }

# ---------------------------------------------------------------- 串口
Section '串口（板载 CP2102，PS UART）'
$ports = @()
try { $ports = [System.IO.Ports.SerialPort]::GetPortNames() } catch { }
$pnp = @(Get-CimInstance Win32_PnPEntity -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match '\(COM\d+\)' })
$cp210x = @($pnp | Where-Object { $_.Name -match 'CP210|Silicon' })
if ($cp210x.Count -gt 0) {
    foreach ($p in $cp210x) { Good ("{0}  <-  {1}" -f ([regex]::Match($p.Name, '\(COM\d+\)').Value.Trim('()')), $p.Name) }
    if ($cp210x.Count -gt 1) {
        Info '板子上有 PS/PL 两个 CP2102 串口，认准 PS UART 那个；搞不清就两个都记下，下载后哪个有输出就是它'
    }
} else {
    Bad '没找到 CP210x 串口：板子没上电 / USB 串口线没插 / 插的线只供电不传数据 / 驱动没装'
    if ($ports.Count -gt 0) { Info ('系统里现有的串口：' + ($ports -join ', ')) }
}

# ---------------------------------------------------------------- JTAG
Section 'JTAG 下载器（AXU5EV-E 是 10 针排针，需要外接下载器）'
$jtagPattern = 'Digilent|Xilinx|USB.*JTAG|JTAG.*USB|FTDI|HS1|HS2|Platform Cable'
$jtag = @(Get-CimInstance Win32_PnPEntity -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match $jtagPattern -and $_.Name -notmatch '\(COM\d+\)' })
if ($jtag.Count -gt 0) {
    foreach ($d in $jtag) { Good $d.Name }
} else {
    Bad '没找到 JTAG 下载器：下载器的 USB 没插 / 驱动没装（Vivado 安装时带 Digilent 驱动）'
    Info '板子本体没有 USB-JTAG 口，只有 10 针排针，必须用外接下载器（学长那根排线+盒子）'
}

# ---------------------------------------------------------------- 网卡
Section '网络（地面站 / C3 UDP 测试用）'
$ip = @()
try {
    $ip = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -like '192.168.1.*' })
} catch { }
if ($ip.Count -gt 0) {
    foreach ($a in $ip) { Good ("{0}  ({1})" -f $a.IPAddress, $a.InterfaceAlias) }
    if (-not ($ip | Where-Object { $_.IPAddress -eq '192.168.1.102' })) {
        Info '建议把有线网卡设成 192.168.1.102/24'
    }
} else {
    Bad '没有 192.168.1.x 的地址（只跑串口/下载可以不管；要连地面站或测 UDP 才需要）'
}

# ---------------------------------------------------------------- 文件
Section '下板文件（2026.1 重编版 + 学长那版）'
$need = @(
    @{ n = 'M1 bit (2026.1)';  p = 'build\board\chk_m1_20261016b\chk_plat\hw\sdt\tt_zu5ev.bit' },
    @{ n = 'M1 FSBL (2026.1)'; p = 'build\board\chk_m1_20261016b\chk_plat\zynqmp_fsbl\build\fsbl.elf' },
    @{ n = 'M1 ELF (2026.1)';  p = 'build\board\chk_m1_20261016b\tt_bench_zu5ev\build\tt_bench_zu5ev.elf' },
    @{ n = 'M1 ELF (2020.2)';  p = 'board\m1\tt_bench_zu5ev.elf' },
    @{ n = 'GCS ELF (2020.2)'; p = 'build\host\gcs_r1_abi4_vitis\gcs_r1_abi4_app\Debug\gcs_r1_abi4_app.elf' },
    @{ n = '下载脚本 dl_m1_2026.tcl'; p = 'build\host\dl_m1_2026.tcl' },
    @{ n = '下载脚本 dl_m1.tcl';      p = 'build\host\dl_m1.tcl' }
)
foreach ($f in $need) {
    $full = Join-Path $repo $f.p
    if (Test-Path $full) { Good $f.n }
    else { Bad ("{0}  ({1})" -f $f.n, $f.p) }
}

# ---------------------------------------------------------------- 结论
Section '结论'
if ($ok) {
    Write-Host '  台面就绪：串口 / 下载器 / 下板文件都在。下一步：' -ForegroundColor Green
} else {
    Write-Host '  还差点东西（上面标 [缺] 的），先补；只缺网络的可以先跳过。' -ForegroundColor Yellow
}
Write-Host '  1) 打开串口： pwsh -File tools\uart_term.ps1' -ForegroundColor DarkGray
Write-Host '  2) 下载 M1（2026.1 版）： D:\AMD\2026.1\Vitis\bin\xsdb.bat D:/HSI_AgriEdge/build/host/dl_m1_2026.tcl' -ForegroundColor DarkGray
Write-Host '  3) 下载 M1（学长那版）：   D:\AMD\2026.1\Vitis\bin\xsdb.bat D:/HSI_AgriEdge/build/host/dl_m1.tcl' -ForegroundColor DarkGray

exit $(if ($ok) { 0 } else { 1 })
