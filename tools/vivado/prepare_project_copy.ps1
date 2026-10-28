# 把 build/vivado 下的 Vivado 工程复制一份、升级到 2026.1 并改成现有器件，
# 产物放在 build/host/vivado2026/<名字>/，原件不动。
#
# 用法（在仓库根或用绝对路径都行）：
#   pwsh -File tools\vivado\prepare_project_copy.ps1 -Name tt_m2_zu5ev
#   pwsh -File tools\vivado\prepare_project_copy.ps1 -Name tt_zu5ev -Force
#
# 为什么需要：仓库里的工程是 2020.2 建的，而且记录的是车规器件
# xazu5ev-sfvc784-1-i（本机器件库里没有）；实际板卡是 XCZU5EV-2SFVC784I，
# 对应 xczu5ev-sfvc784-2-i。复制 + 升级 + 指定器件后，2026.1 才能直接打开。

param(
    [Parameter(Mandatory = $true)][string]$Name,
    [string]$Part = 'xczu5ev-sfvc784-2-i',
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

$Repo = (Resolve-Path "$PSScriptRoot\..\..").Path
$Src = Join-Path $Repo "build\vivado\$Name"
$Dst = Join-Path $Repo "build\host\vivado2026\$Name"

if (-not (Test-Path (Join-Path $Src "$Name.xpr"))) {
    throw "找不到工程：$Src\$Name.xpr"
}
if ((Test-Path $Dst) -and (-not $Force)) {
    throw "目标已存在：$Dst（要重做请加 -Force）"
}
if (Test-Path $Dst) { Remove-Item $Dst -Recurse -Force }
New-Item -ItemType Directory -Force -Path (Split-Path $Dst) | Out-Null

function Find-Vivado {
    if ($env:TT_VIVADO_ROOT) {
        $p = Join-Path $env:TT_VIVADO_ROOT 'bin\vivado.bat'
        if (Test-Path $p) { return $p }
    }
    $amd = if ($env:TT_AMD_ROOT) { $env:TT_AMD_ROOT } else { 'D:\AMD' }
    if (Test-Path $amd) {
        foreach ($d in (Get-ChildItem $amd -Directory | Sort-Object Name -Descending)) {
            $p = Join-Path $d.FullName 'Vivado\bin\vivado.bat'
            if (Test-Path $p) { return $p }
        }
    }
    throw "找不到 Vivado（在 $amd 下按 <版本>\Vivado\bin\vivado.bat 查找；可设 TT_VIVADO_ROOT）"
}
$Vivado = Find-Vivado
Write-Host "Vivado: $Vivado"

# 许可证：切到 BASIC 层，否则器件库里没有 ZU5EV
$Lic = Join-Path $Repo 'build\host\lic\vivado_basic.lic'
if (-not (Test-Path $Lic)) {
    $py = if (Get-Command python -ErrorAction SilentlyContinue) { 'python' } else { 'D:\Anaconda\python.exe' }
    & $py (Join-Path $Repo 'tools\vivado\make_basic_license.py') | Out-Host
}
$env:XILINXD_LICENSE_FILE = $Lic

Write-Host "复制工程 -> $Dst"
Copy-Item $Src $Dst -Recurse -Force

$tcl = Join-Path $env:TEMP ("prepare_" + $Name + ".tcl")
@"
open_project -part $Part {$(($Dst + '\' + $Name + '.xpr') -replace '\\','/')}
puts "OPEN_OK part=[get_property PART [current_project]]"
close_project
exit
"@ | Set-Content -Path $tcl -Encoding ASCII

& $Vivado -mode batch -source $tcl -nojournal -nolog -notrace 2>&1 | Select-String -Pattern 'OPEN_OK|ERROR|WARNING.*part|upgraded' | ForEach-Object { $_.Line.Trim() }
if ($LASTEXITCODE -ne 0) { throw "Vivado 升级失败，退出码 $LASTEXITCODE（看上面输出）" }

Write-Host ""
Write-Host "完成：$Dst\$Name.xpr（已在 2026.1 升级，器件 $Part）"
Write-Host "打开方式：tools\vivado\launch_vivado.bat `"$Dst\$Name.xpr`""
