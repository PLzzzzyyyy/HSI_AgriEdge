# -*- coding: utf-8 -*-
<#
.SYNOPSIS
  把「能跑的运行包 + 能改的源码」打包给队友（不需要 Vivado/Vitis 图形界面就能启动）。

.DESCRIPTION
  默认产出约 36 MB：firmware（4 个固件）、tools（启动器与客户端）、src（PS 应用/DP 界面源码）、
  gcs（地面站网页源码与三景词表）、model（训练/导出脚本）、docs（协议等）、board（README 与清单）、
  manual（使用手册）、START_DEMO.bat 与 README_运行说明.md。

  构建树 build\（27 GB）、场景数据 data\、2020.2 工程 vitis\、证据 report\ 默认不带，
  需要时用 -WithVitisProjects / -WithData 显式打开。

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File tools\make_team_package.ps1 -Zip

.EXAMPLE
  ... -File tools\make_team_package.ps1 -OutDir E:\share -Name HSI_team_r2 -Zip
#>
param(
    [string]$OutDir = "D:\FPGAgame\_team_package",
    [string]$Name = "",
    [switch]$Zip,
    [switch]$WithVitisProjects,
    [switch]$WithData,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
if (-not $Name) { $Name = "HSI_AgriEdge_team_" + (Get-Date -Format "yyyyMMdd") }
$pkg = Join-Path $OutDir $Name

function Say($msg) { Write-Host $msg }
function SizeOf($path) {
    if (-not (Test-Path $path)) { return 0 }
    return (Get-ChildItem $path -Recurse -File -ErrorAction SilentlyContinue |
            Measure-Object -Property Length -Sum).Sum
}
function CopyTree($src, $dst, [string[]]$excludeDirs = @('__pycache__', '.git')) {
    if (-not (Test-Path $src)) { Say "  [跳过] $src 不存在"; return }
    $srcFull = (Resolve-Path $src).Path
    Get-ChildItem $srcFull -Recurse -File -ErrorAction SilentlyContinue | ForEach-Object {
        $rel = $_.FullName.Substring($srcFull.Length).TrimStart('\')
        $parts = $rel -split '\\'
        foreach ($ex in $excludeDirs) { if ($parts -contains $ex) { return } }
        $target = Join-Path $dst $rel
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
        Copy-Item $_.FullName $target -Force
    }
}
function CopyFlatByExt($src, $dst, [string[]]$exts) {
    if (-not (Test-Path $src)) { return }
    $srcFull = (Resolve-Path $src).Path
    Get-ChildItem $srcFull -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $exts -contains $_.Extension } | ForEach-Object {
            $rel = $_.FullName.Substring($srcFull.Length).TrimStart('\')
            $target = Join-Path $dst $rel
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
            Copy-Item $_.FullName $target -Force
        }
}

Say "== 打包到 $pkg =="
if (Test-Path $pkg) {
    if ($Force) { Remove-Item $pkg -Recurse -Force }
    else { throw "目标已存在：$pkg（加 -Force 覆盖）" }
}
New-Item -ItemType Directory -Force -Path $pkg | Out-Null

# ---------- 1. firmware（扁平放，启动器优先读这里）----------
Say "[1/9] firmware"
$fw = Join-Path $pkg 'firmware'
New-Item -ItemType Directory -Force -Path $fw | Out-Null
$files = @(
    @{ src = "firmware\gcs_r1_abi4_app_linked.elf";                                          dst = "gcs_r1_abi4_app_linked.elf" },
    @{ src = "firmware\gcs_r1_abi4_app_dpfix.elf";                                           dst = "gcs_r1_abi4_app_dpfix.elf" },
    @{ src = "build\vivado\tt_gcs_r1_abi4_zu5ev.bit";                                        dst = "tt_gcs_r1_abi4_zu5ev.bit" },
    @{ src = "build\vivado\tt_gcs_r1_abi4_zu5ev.xsa";                                        dst = "tt_gcs_r1_abi4_zu5ev.xsa" },
    @{ src = "build\board\abi4_ws_20261017\gcs_r1_abi4_app\build\gcs_r1_abi4_app.elf";      dst = "gcs_r1_abi4_app.elf" },
    @{ src = "build\host\gcs_r1_abi4_vitis\gcs_r1_abi4_app\Debug\gcs_r1_abi4_app.elf";       dst = "gcs_r1_abi4_app_2020.2.elf" },
    @{ src = "build\host\gcs_r1_abi4_vitis\gcs_r1_abi4_plat\zynqmp_fsbl\fsbl_a53.elf";       dst = "fsbl_a53.elf" }
)
foreach ($f in $files) {
    $p = Join-Path $repo $f.src
    if (-not (Test-Path $p)) { throw "缺少固件：$p（先在仓库里确认路径）" }
    Copy-Item $p (Join-Path $fw $f.dst) -Force
    Say ("      {0,-28} {1,10:N0} B" -f $f.dst, (Get-Item $p).Length)
}
$sums = Get-ChildItem $fw -File | ForEach-Object {
    "{0}  {1}" -f (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower(), $_.Name
}
Set-Content -Path (Join-Path $fw 'SHA256SUMS.txt') -Value ($sums -join "`r`n") -Encoding ASCII

# ---------- 1b. 本地演示身份：PC/DP 联动候选 manifest 与发布校验引用文件 ----------
# START_DEMO.bat 检测到 manifest 后自动设置 GCS_LOCAL_DEMO_BUNDLE；原版控制台连接时
# 用它核对“板卡跑的就是这套固件”。引用文件是 manifest 资产清单的一部分，缺一即拒连。
Say "[1b/9] 本地演示身份（PC/DP 联动候选 manifest 与引用文件）"
$bundleDst = Join-Path $pkg 'build\host\gcs_pc_dp_link_20261017'
New-Item -ItemType Directory -Force -Path $bundleDst | Out-Null
Copy-Item (Join-Path $repo 'build\host\gcs_pc_dp_link_20261017\manifest.json') (Join-Path $bundleDst 'manifest.json') -Force
$refs = @(
    'vitis\s2c_roi_app\src\lscript.ld',
    'vitis\s1b_m3a_plat\psu_cortexa53_0\standalone_domain\bsp\system.mss',
    'vitis\s1b_m3a_plat\psu_cortexa53_0\standalone_domain\bsp\psu_cortexa53_0\libsrc\lwip211_v1_3\src\contrib\ports\xilinx\netif\xemacpsif_physpeed.c',
    'build\hls\run_gcs_round1.tcl',
    'build\vivado\build_gcs_round1.tcl',
    'build\vivado\finalize_gcs_ip.tcl',
    'build\vivado\psu_cfg_factory.tcl',
    'build\vivado\zu5ev_pins.xdc'
)
foreach ($rel in $refs) {
    $p = Join-Path $repo $rel
    if (-not (Test-Path $p)) { throw "缺少发布校验引用文件：$p" }
    $target = Join-Path $pkg $rel
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
    Copy-Item $p $target -Force
    Say ("      {0}" -f $rel)
}

# ---------- 2. 启动器与说明 ----------
Say "[2/9] START_DEMO.bat / README"
Copy-Item (Join-Path $repo 'tools\launcher\START_DEMO.bat') (Join-Path $pkg 'START_DEMO.bat') -Force
Copy-Item (Join-Path $repo 'docs\team_package.md') (Join-Path $pkg 'README_运行说明.md') -Force

# ---------- 3. tools ----------
Say "[3/9] tools"
CopyTree (Join-Path $repo 'tools') (Join-Path $pkg 'tools') -excludeDirs @('__pycache__')

# ---------- 4. src ----------
Say "[4/9] src"
CopyTree (Join-Path $repo 'src') (Join-Path $pkg 'src') -excludeDirs @('__pycache__')

# ---------- 5. gcs ----------
Say "[5/9] gcs"
CopyTree (Join-Path $repo 'gcs') (Join-Path $pkg 'gcs') -excludeDirs @('__pycache__', 'node_modules')

# ---------- 6. model ----------
Say "[6/9] model"
CopyTree (Join-Path $repo 'model') (Join-Path $pkg 'model') -excludeDirs @('__pycache__')

# ---------- 7. docs（去掉 vendor 大件）----------
Say "[7/9] docs（不含 vendor）"
$dstDocs = Join-Path $pkg 'docs'
New-Item -ItemType Directory -Force -Path $dstDocs | Out-Null
Get-ChildItem (Join-Path $repo 'docs') -File -ErrorAction SilentlyContinue |
    ForEach-Object { Copy-Item $_.FullName $dstDocs -Force }
Get-ChildItem (Join-Path $repo 'docs') -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -ne 'vendor' } |
    ForEach-Object { CopyTree $_.FullName (Join-Path $dstDocs $_.Name) }

# ---------- 8. board（只要文本）----------
Say "[8/9] board（只要 README/清单/脚本模板）"
$dstBoard = Join-Path $pkg 'board'
Get-ChildItem (Join-Path $repo 'board') -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Extension -in @('.md', '.txt', '.json') -or $_.Name -eq 'gcs_round1.bif.in' } |
    ForEach-Object {
        $rel = $_.FullName.Substring((Join-Path $repo 'board').Length).TrimStart('\')
        $target = Join-Path $dstBoard $rel
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
        Copy-Item $_.FullName $target -Force
    }

# ---------- 9. 手册 ----------
Say "[9/9] manual"
$dstManual = Join-Path $pkg 'manual'
New-Item -ItemType Directory -Force -Path $dstManual | Out-Null
Get-ChildItem 'D:\FPGAgame' -File -Filter 'HSI_AgriEdge_使用手册_v2.3.*' -ErrorAction SilentlyContinue |
    ForEach-Object { Copy-Item $_.FullName $dstManual -Force; Say ("      " + $_.Name) }

# ---------- 可选：大件 ----------
if ($WithVitisProjects) {
    Say "[+] vitis 工程与 2026.1 工作区（约 1.6 GB）"
    CopyTree (Join-Path $repo 'vitis') (Join-Path $pkg 'vitis')
    CopyFlatByExt (Join-Path $repo 'build\board') (Join-Path $pkg 'build_2026_workspaces') @('.elf', '.bit', '.xsa', '.json')
}
if ($WithData) {
    Say "[+] data\ 场景数据（约 4.7 GB）"
    CopyTree (Join-Path $repo 'data') (Join-Path $pkg 'data') -excludeDirs @()
}

# ---------- 汇总 ----------
Say ""
Say "== 各目录体积 =="
$total = 0
Get-ChildItem $pkg | ForEach-Object {
    if ($_.PSIsContainer) { $s = SizeOf $_.FullName } else { $s = $_.Length }
    $total += $s
    Say ("  {0,-24} {1,10:N1} MB" -f $_.Name, ($s / 1MB))
}
Say ("  {0,-24} {1,10:N1} MB" -f '合计', ($total / 1MB))

if ($Zip) {
    $zipPath = Join-Path $OutDir ($Name + '.zip')
    if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
    Say ""
    Say "== 压缩 =="
    Compress-Archive -Path (Join-Path $pkg '*') -DestinationPath $zipPath -CompressionLevel Optimal
    Say ("  {0}  {1:N1} MB" -f $zipPath, ((Get-Item $zipPath).Length / 1MB))
}

Say ""
Say "完成：$pkg"
Say "队友拿到后：接好线（DC12V / JTAG / 网线 / DP，SW1=0000，PC 设 192.168.1.102/24），双击 START_DEMO.bat。"
