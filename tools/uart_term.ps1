# ---------------------------------------------------------------------------
# 极简串口终端：115200 8N1，自动记日志，单键发送（板卡菜单是单字符输入）
#
# 用法：
#   pwsh -File tools\uart_term.ps1                 # 自动找 CP210x 串口
#   pwsh -File tools\uart_term.ps1 -Port COM7      # 指定串口
#   pwsh -File tools\uart_term.ps1 -Baud 115200
#
# 快捷键：Esc 退出（日志已保存）。直接敲字符就会发给板卡，回车发 CR。
# 日志默认写到 logs\uart\uart_<时间>.log，出问题时把这个文件贴出来就行。
# ---------------------------------------------------------------------------

param(
    [string]$Port,
    [int]$Baud = 115200,
    [string]$LogDir
)

$ErrorActionPreference = 'Stop'

$repo = (Resolve-Path "$PSScriptRoot\..").Path
if (-not $LogDir) { $LogDir = Join-Path $repo 'logs\uart' }
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Get-CandidatePorts {
    Get-CimInstance Win32_PnPEntity -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '\(COM\d+\)' } |
        ForEach-Object {
            $m = [regex]::Match($_.Name, '\((COM\d+)\)')
            [pscustomobject]@{ Port = $m.Groups[1].Value; Name = $_.Name }
        }
}

if (-not $Port) {
    $cands = @(Get-CandidatePorts)
    $cp = $cands | Where-Object { $_.Name -match 'CP210|Silicon|CH340|USB.*UART' }
    if ($cp) {
        $Port = @($cp)[0].Port
    } else {
        Write-Host '没有找到 CP210x / USB 串口。当前系统的串口：' -ForegroundColor Yellow
        if ($cands.Count) { $cands | Format-Table Port, Name -AutoSize | Out-Host }
        else { Write-Host '  （一个串口都没有：板子的 USB 串口线接了吗？CP210x 驱动装了吗？）' }
        Write-Host ''
        Write-Host '接好线后重跑本脚本；也可以直接指定：pwsh -File tools\uart_term.ps1 -Port COMx'
        exit 1
    }
}

$logPath = Join-Path $LogDir ("uart_" + (Get-Date -Format 'yyyyMMdd_HHmmss') + ".log")
$sp = [System.IO.Ports.SerialPort]::new($Port, $Baud,
        [System.IO.Ports.Parity]::None, 8, [System.IO.Ports.StopBits]::One)
$sp.Encoding = [System.Text.Encoding]::ASCII
$sp.ReadTimeout = 200
$sp.NewLine = "`r`n"
$sp.Open()

$log = [System.IO.StreamWriter]::new($logPath, $false, [System.Text.Encoding]::UTF8)
$log.WriteLine("# uart_term  port=$Port baud=$Baud  start=$(Get-Date -Format o)")
$log.Flush()

Write-Host ("已连接 {0} @ {1}" -f $Port, $Baud) -ForegroundColor Green
Write-Host ("日志：{0}" -f $logPath) -ForegroundColor DarkGray
Write-Host "直接敲字符发送（板卡菜单是单字符）；Esc 退出。" -ForegroundColor DarkGray
Write-Host ''

$interactive = $true
try { [void][Console]::KeyAvailable } catch { $interactive = $false }

try {
    while ($true) {
        if ($sp.BytesToRead -gt 0) {
            $chunk = $sp.ReadExisting()
            [Console]::Out.Write($chunk)
            $log.Write($chunk)
            $log.Flush()
        }
        if ($interactive) {
            if ([Console]::KeyAvailable) {
                $k = [Console]::ReadKey($true)
                if ($k.Key -eq 'Escape') { break }
                $sp.Write($k.KeyChar.ToString())
                $log.Write("[TX]" + $k.KeyChar)
                $log.Flush()
            }
        }
        Start-Sleep -Milliseconds 30
    }
}
finally {
    try { $sp.Close() } catch { }
    try { $log.WriteLine("# stop $(Get-Date -Format o)"); $log.Close() } catch { }
    Write-Host ''
    Write-Host "已断开，日志在 $logPath" -ForegroundColor DarkGray
}
