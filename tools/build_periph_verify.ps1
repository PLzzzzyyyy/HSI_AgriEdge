# Rebuild current C3 sources against an existing XSCT BSP without starting Eclipse.
# Does not modify the Vitis workspace or replace board/periph's legacy ELF.
param([string]$Workspace = '', [string]$OutputDir = '')
$root = Split-Path $PSScriptRoot -Parent
if (!$Workspace) { $Workspace = Join-Path $root 'build/board/periph_ws' }
if (!$OutputDir) { $OutputDir = Join-Path $root ('build/board/periph_verify_' + (Get-Date -Format 'yyyyMMdd_HHmmss')) }
if (Test-Path -LiteralPath $OutputDir) { throw "Output exists; choose a new directory: $OutputDir" }
$cc = 'D:/xilinx/Vitis/2020.2/gnu/aarch64/nt/aarch64-none/bin/aarch64-none-elf-g++.exe'
$bsp = Join-Path $Workspace 'periph_plat/export/periph_plat/sw/periph_plat/standalone_domain'
$ld = Join-Path $Workspace 'periph_zu5ev/src/lscript.ld'
foreach ($p in @($cc, $ld, "$bsp/bspinclude/include/xparameters.h", "$bsp/bsplib/lib/libxil.a")) {
    if (!(Test-Path -LiteralPath $p)) { throw "Missing input: $p" }
}
New-Item -ItemType Directory -Path $OutputDir -ErrorAction Stop | Out-Null
$OutputDir = (Resolve-Path -LiteralPath $OutputDir).Path
$log = Join-Path $OutputDir 'build.log'
$objects = @()
# Compiler emits harmless #pragma notes to stderr; inspect exit status, not stderr alone.
$ErrorActionPreference = 'Continue'
foreach ($src in Get-ChildItem -LiteralPath "$root/src/ps/periph" -Filter '*.cpp') {
    $obj = Join-Path $OutputDir ($src.BaseName + '.o')
    $flags = @('-Wall','-Wextra','-Werror','-O2','-mcpu=cortex-a53','-c',"-I$bsp/bspinclude/include",$src.FullName,'-o',$obj)
    "$cc $flags" | Add-Content -LiteralPath $log
    & $cc @flags 2>&1 | ForEach-Object { "$_" } | Tee-Object -FilePath $log -Append
    if ($LASTEXITCODE -ne 0) { throw "Compile failed: $src" }
    $objects += $obj
}
if ($objects.Count -ne 6) { throw 'Expected six peripheral translation units' }
$elf = Join-Path $OutputDir 'periph_zu5ev.elf'
$flags = @('-Wl,-T',"-Wl,$ld","-L$bsp/bsplib/lib",'-o',$elf) + $objects + @(
    '-Wl,--start-group,-lxil,-lgcc,-lc,-lstdc++,--end-group',
    '-Wl,--start-group,-lxilffs,-lxil,-lgcc,-lc,--end-group',
    '-Wl,--start-group,-lxil,-llwip4,-lgcc,-lc,--end-group')
"$cc $flags" | Add-Content -LiteralPath $log
& $cc @flags 2>&1 | ForEach-Object { "$_" } | Tee-Object -FilePath $log -Append
if ($LASTEXITCODE -ne 0) { throw 'Link failed' }
if (Select-String -LiteralPath $log -Pattern 'warning:') { throw 'Warnings found; inspect log' }
Get-FileHash -Algorithm SHA256 -LiteralPath $elf | Format-List | Out-String | Add-Content -LiteralPath $log
'BUILD PASS: current source, six files, -Wall -Wextra -Werror, existing BSP (not XSCT end-to-end)' | Tee-Object -FilePath $log -Append
'ELF: ' + $elf
