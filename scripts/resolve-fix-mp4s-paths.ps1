#Requires -Version 7.0
# Prompt for or validate -InputDir / -OutputDir used by fix-mp4s.ps1 and delete-verified-sources.ps1

function Resolve-FixMp4Paths {
    param(
        [string] $InputDir,
        [string] $OutputDir
    )

    if (-not $InputDir) {
        $InputDir = Read-Host 'Input directory (sources to fix)'
    }
    if (-not $OutputDir) {
        $OutputDir = Read-Host 'Output directory (writes <username>\file.mp4 beneath this)'
    }

    $InputDir = "$InputDir".Trim()
    $OutputDir = "$OutputDir".Trim()
    if (-not $InputDir -or -not $OutputDir) {
        Write-Error 'Both -InputDir and -OutputDir are required.'
        exit 2
    }

    if (-not (Test-Path -LiteralPath $InputDir)) {
        Write-Error "Input directory not found: $InputDir"
        exit 2
    }

    $resolvedInput = (Resolve-Path -LiteralPath $InputDir).Path
    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

    return [pscustomobject]@{
        InputDir  = $resolvedInput
        OutputDir = $OutputDir
    }
}
