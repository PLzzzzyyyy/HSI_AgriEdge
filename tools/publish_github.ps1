[CmdletBinding()]
param(
    [ValidatePattern('^([A-Za-z0-9-]+/)?[A-Za-z0-9_.-]+$')]
    [string]$Repository = 'HSI_AgriEdge'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$script:ProjectRoot = [System.IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\', '/')
$releaseTag = 'snapshot-20261028'
$dataArchive = Join-Path (Split-Path -Parent $script:ProjectRoot) 'HSI_AgriEdge_data_20261028.zip'

function Invoke-Checked {
    param([string]$Program, [string[]]$ArgumentList)
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $nativeOutput = & $Program @ArgumentList 2>&1
        $nativeExit = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($nativeExit -ne 0) {
        throw ('Command failed ({0}): {1} {2}{3}{4}' -f $nativeExit, $Program, ($ArgumentList -join ' '), [Environment]::NewLine, ($nativeOutput -join [Environment]::NewLine))
    }
    return $nativeOutput
}

function Resolve-PackageFile {
    param([string]$RelativePath)
    if ([string]::IsNullOrWhiteSpace($RelativePath) -or $RelativePath -match '[:\\]' -or $RelativePath.StartsWith('/') -or $RelativePath.Split('/') -contains '..') {
        throw "Unsafe package path: $RelativePath"
    }
    $resolvedFile = [System.IO.Path]::GetFullPath((Join-Path $script:ProjectRoot $RelativePath))
    if (-not $resolvedFile.StartsWith($script:ProjectRoot + [System.IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Package path escapes project: $RelativePath"
    }
    return $resolvedFile
}

function Get-GitHubTarget {
    param([string]$RemoteUrl)
    if ($RemoteUrl -match '^https://github\.com/([^/]+/[^/]+?)(?:\.git)?/?$') { return $Matches[1] }
    if ($RemoteUrl -match '^git@github\.com:([^/]+/[^/]+?)(?:\.git)?$') { return $Matches[1] }
    if ($RemoteUrl -match '^ssh://git@github\.com/([^/]+/[^/]+?)(?:\.git)?/?$') { return $Matches[1] }
    return $null
}

try {
    if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
        Write-Host 'GitHub CLI is required. Install it from https://cli.github.com/ and run this script again.'
        exit 1
    }
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw 'Git is required. Install Git for Windows, then run this script again.'
    }
    $ErrorActionPreference = 'Continue'
    & gh auth status --hostname github.com *> $null
    $authExit = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    if ($authExit -ne 0) {
        Write-Host 'Sign in with your own GitHub account, then run this script again:'
        Write-Host '  gh auth login --hostname github.com'
        exit 1
    }
    if (-not (Test-Path -LiteralPath $dataArchive -PathType Leaf)) {
        throw "Data archive is required before publishing: $dataArchive"
    }
    $manifestPath = Join-Path $script:ProjectRoot 'package_manifest.json'
    $packageManifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $packageManifest.files -or @($packageManifest.files).Count -eq 0) {
        throw 'package_manifest.json must contain a nonempty files array.'
    }
    $trackedPaths = [System.Collections.Generic.List[string]]::new()
    foreach ($entry in $packageManifest.files) {
        $filePath = Resolve-PackageFile $entry.path
        if (-not (Test-Path -LiteralPath $filePath -PathType Leaf)) { throw "Missing package file: $($entry.path)" }
        if ((Get-FileHash -LiteralPath $filePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.sha256.ToLowerInvariant()) {
            throw "Package file changed: $($entry.path). Rebuild the reviewed package manifest before publishing."
        }
        $trackedPaths.Add([string]$entry.path)
    }
    $trackedPaths.Add('package_manifest.json')
    $trackedPaths = @($trackedPaths | Sort-Object -Unique)
    $githubUser = (Invoke-Checked 'gh' @('api', '--hostname', 'github.com', 'user') | Out-String | ConvertFrom-Json)
    $targetRepository = if ($Repository.Contains('/')) { $Repository } else { "$($githubUser.login)/$Repository" }

    $ErrorActionPreference = 'Continue'
    $existingRoot = & git -C $script:ProjectRoot rev-parse --show-toplevel 2>$null
    $rootExit = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    if ($rootExit -eq 0) {
        $canonicalGitRoot = [System.IO.Path]::GetFullPath(($existingRoot | Select-Object -First 1)).TrimEnd('\', '/')
        if (-not $canonicalGitRoot.Equals($script:ProjectRoot, [StringComparison]::OrdinalIgnoreCase)) {
            throw 'This folder belongs to a parent Git repository. Publish an independent copy instead.'
        }
    } else {
        Invoke-Checked 'git' @('-C', $script:ProjectRoot, 'init', '-b', 'main') | Out-Host
    }
    $branchName = (Invoke-Checked 'git' @('-C', $script:ProjectRoot, 'symbolic-ref', '--short', 'HEAD') | Out-String).Trim()
    if ([string]::IsNullOrWhiteSpace($branchName)) { throw 'A named Git branch is required.' }
    $remotes = @(Invoke-Checked 'git' @('-C', $script:ProjectRoot, 'remote'))
    if (@($remotes | Where-Object { $_ -and $_ -ne 'origin' }).Count -gt 0) {
        throw 'Unexpected Git remote found. Review the independent package repository before publishing.'
    }
    $hasOrigin = $remotes -contains 'origin'
    if ($hasOrigin) {
        $originUrls = @(Invoke-Checked 'git' @('-C', $script:ProjectRoot, 'remote', 'get-url', '--all', 'origin'))
        $originUrls += @(Invoke-Checked 'git' @('-C', $script:ProjectRoot, 'remote', 'get-url', '--push', '--all', 'origin'))
        foreach ($originUrl in $originUrls) {
            $originTarget = Get-GitHubTarget ([string]$originUrl)
            if (-not $originTarget -or -not $originTarget.Equals($targetRepository, [StringComparison]::OrdinalIgnoreCase)) {
                throw "Existing origin does not match the requested repository: $targetRepository"
            }
        }
        $remoteRepository = Invoke-Checked 'gh' @('repo', 'view', $targetRepository, '--json', 'nameWithOwner,url,isPrivate') | Out-String | ConvertFrom-Json
        if ($remoteRepository.isPrivate) { throw 'The existing target is private; this script does not change repository visibility.' }
    }
    $stagedPaths = @(Invoke-Checked 'git' @('-C', $script:ProjectRoot, 'diff', '--cached', '--name-only'))
    foreach ($stagedPath in $stagedPaths) {
        if ($stagedPath -and $trackedPaths -notcontains $stagedPath) {
            throw "Unrelated staged file found: $stagedPath"
        }
    }
    for ($offset = 0; $offset -lt $trackedPaths.Count; $offset += 40) {
        $last = [Math]::Min($offset + 39, $trackedPaths.Count - 1)
        $batch = @($trackedPaths[$offset..$last])
        Invoke-Checked 'git' (@('-C', $script:ProjectRoot, 'add', '--') + $batch) | Out-Host
    }
    & git -C $script:ProjectRoot diff --cached --quiet
    $diffExit = $LASTEXITCODE
    if ($diffExit -notin @(0, 1)) { throw 'Unable to inspect the staged Git changes.' }
    if ($diffExit -eq 1) {
        $authorName = & git -C $script:ProjectRoot config user.name 2>$null
        $authorEmail = & git -C $script:ProjectRoot config user.email 2>$null
        $commitArguments = @('-C', $script:ProjectRoot)
        if ([string]::IsNullOrWhiteSpace(($authorName | Out-String))) { $commitArguments += @('-c', "user.name=$($githubUser.login)") }
        if ([string]::IsNullOrWhiteSpace(($authorEmail | Out-String))) { $commitArguments += @('-c', "user.email=$($githubUser.id)+$($githubUser.login)@users.noreply.github.com") }
        $commitArguments += @('commit', '-m', 'Package HSI_AgriEdge source and firmware snapshot (2026-10-28)')
        Invoke-Checked 'git' $commitArguments | Out-Host
    }
    $headRevision = (Invoke-Checked 'git' @('-C', $script:ProjectRoot, 'rev-parse', 'HEAD') | Out-String).Trim()
    if (-not $hasOrigin) {
        Invoke-Checked 'gh' @('repo', 'create', $targetRepository, '--public', '--source', $script:ProjectRoot, '--remote', 'origin', '--push') | Out-Host
    } else {
        Invoke-Checked 'git' @('-C', $script:ProjectRoot, 'push', '--set-upstream', 'origin', $branchName) | Out-Host
    }
    $releaseList = @(Invoke-Checked 'gh' @('release', 'list', '--repo', $targetRepository, '--json', 'tagName', '--limit', '1000') | Out-String | ConvertFrom-Json)
    if (-not ($releaseList | Where-Object { $_.tagName -eq $releaseTag })) {
        Invoke-Checked 'gh' @('release', 'create', $releaseTag, '--repo', $targetRepository, '--target', $headRevision, '--title', 'HSI_AgriEdge snapshot 2026-10-28', '--notes', 'Source and existing local demonstration firmware snapshot. Extract the separate data ZIP into the repository root, then run verify_package.py --with-data. File integrity checks do not constitute portability or hardware acceptance.') | Out-Host
    }
    $releaseInfo = Invoke-Checked 'gh' @('api', '--hostname', 'github.com', "repos/$targetRepository/releases/tags/$releaseTag") | Out-String | ConvertFrom-Json
    $archiveName = Split-Path -Leaf $dataArchive
    $existingAssets = @($releaseInfo.assets | Where-Object { $_.name -eq $archiveName })
    if ($existingAssets.Count -gt 1) { throw 'Multiple same-name release assets exist; review them manually.' }
    if ($existingAssets.Count -eq 1) {
        if ($existingAssets[0].size -ne (Get-Item -LiteralPath $dataArchive).Length) {
            throw 'The same-name data asset has a different size. It has not been overwritten.'
        }
        Write-Host "The data asset already exists; it has not been overwritten: $archiveName"
    } else {
        Invoke-Checked 'gh' @('release', 'upload', $releaseTag, $dataArchive, '--repo', $targetRepository) | Out-Host
    }
    $publishedRepository = Invoke-Checked 'gh' @('repo', 'view', $targetRepository, '--json', 'url') | Out-String | ConvertFrom-Json
    Write-Host ('Repository: ' + $publishedRepository.url)
    Write-Host ('Release: ' + $releaseInfo.html_url)
} catch {
    Write-Error $_
    exit 1
}
