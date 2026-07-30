#Requires -Version 7.0
# Delete sources when a matching ffprobe-verified output exists under -OutputDir.
#
# Usage:
#   uv run poe delete-verified-sources -InputDir W:\to_fix -OutputDir W:\converted -WhatIf
#   .\scripts\delete-verified-sources.ps1 -InputDir W:\to_fix -OutputDir W:\converted

param(
    [string] $InputDir,
    [string] $OutputDir,
    [switch] $WhatIf
)

$pathsScript = Join-Path $PSScriptRoot 'resolve-fix-mp4s-paths.ps1'
if (-not (Test-Path -LiteralPath $pathsScript)) {
    Write-Error "Missing path helper: $pathsScript"
    exit 2
}
. $pathsScript
$paths = Resolve-FixMp4Paths -InputDir $InputDir -OutputDir $OutputDir
$InputDir = $paths.InputDir
$OutputDir = $paths.OutputDir

$routingScript = Join-Path $PSScriptRoot 'fix-mp4s-routing.ps1'
if (-not (Test-Path -LiteralPath $routingScript)) {
    Write-Error "Missing routing helper: $routingScript"
    exit 2
}
. $routingScript

function Test-DashPlayable([string] $Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $false }
    if ((Get-Item -LiteralPath $Path).Length -le 0) { return $false }
    $v = & ffprobe -v error -select_streams v:0 `
        -show_entries stream=codec_name,pix_fmt -of csv=p=0 -- $Path 2>$null
    if (-not $v) { return $false }
    $parts = "$v".Trim() -split ','
    if ($parts.Count -lt 2) { return $false }
    return ($parts[0].Trim().ToLowerInvariant() -eq 'h264' -and
            $parts[1].Trim().ToLowerInvariant() -eq 'yuv420p')
}

$files = @(Get-ChildItem -LiteralPath $InputDir -File -Filter '*.mp4')
$delete = @()
$keep = @()

foreach ($f in $files) {
    $route = Resolve-FixMp4Output -FileName $f.Name -OutputDir $OutputDir
    $out = $route.OutPath

    if ((Test-Path -LiteralPath $out) -and (Test-DashPlayable $out)) {
        $delete += $f
    } else {
        $keep += [pscustomobject]@{
            Name   = $f.Name
            Reason = if (-not (Test-Path -LiteralPath $out)) { 'missing output' } else { 'output not playable' }
        }
    }
}

Write-Host "Sources: $($files.Count)"
Write-Host "Safe to delete: $($delete.Count)"
Write-Host "Keep: $($keep.Count)"
if ($keep.Count) {
    Write-Host 'Keeping:'
    $keep | ForEach-Object { Write-Host "  $($_.Name) ($($_.Reason))" }
}

if (-not $delete.Count) {
    exit 0
}

$bytes = ($delete | Measure-Object -Property Length -Sum).Sum
Write-Host ("Would free ~{0:N2} GB" -f ($bytes / 1GB))

foreach ($f in $delete) {
    if ($WhatIf) {
        Write-Host "WhatIf: remove $($f.FullName)"
    } else {
        Remove-Item -LiteralPath $f.FullName -Force
    }
}

if (-not $WhatIf) {
    Write-Host "Deleted $($delete.Count) source file(s)."
}
