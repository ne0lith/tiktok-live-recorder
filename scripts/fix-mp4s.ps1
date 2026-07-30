#Requires -Version 7.0
# fix-mp4s.ps1 - salvage MP4s into <OutputDir>\<username>\
#
# Target player: THIS project's media library - plain <video> in Chromium/Edge.
# Forces H.264 (avc1) + yuv420p + AAC + faststart + fixed canvas; ffprobe-verified.
# NVENC by default when available. No silent CPU fallback unless -AllowCpuFallback
# (so -NvencCq actually means GPU quality, not "maybe x264 CRF 20").
#
# Usage:
#   uv run poe fix-mp4s -InputDir W:\to_fix -OutputDir W:\converted
#   .\scripts\fix-mp4s.ps1 -InputDir W:\to_fix -OutputDir W:\converted
# IMG phone exports (no username): 2025-12-29_23-54-18_IMG_6271.mp4 -> _unknown\

param(
    [string] $InputDir,
    [string] $OutputDir,
    [ValidateSet('Auto', 'Nvenc', 'Cpu')]
    [string] $Encoder = 'Auto',
    [ValidateRange(1, 8)]
    [int] $Parallel = 2,
    [ValidateRange(15, 35)]
    [int] $NvencCq = 21,
    [ValidateRange(1, 16)]
    [int] $CpuThreads = 4,
    # When NVENC is in use, do NOT fall back to libx264 unless this is set.
    [switch] $AllowCpuFallback
)

$ErrorActionPreference = 'Continue'

$pathsScript = Join-Path $PSScriptRoot 'resolve-fix-mp4s-paths.ps1'
if (-not (Test-Path -LiteralPath $pathsScript)) {
    Write-Error "Missing path helper: $pathsScript"
    exit 2
}
. $pathsScript
$paths = Resolve-FixMp4Paths -InputDir $InputDir -OutputDir $OutputDir
$inputDir = $paths.InputDir
$outputDir = $paths.OutputDir

$routingScript = Join-Path $PSScriptRoot 'fix-mp4s-routing.ps1'
if (-not (Test-Path -LiteralPath $routingScript)) {
    Write-Error "Missing routing helper: $routingScript"
    exit 2
}
. $routingScript

function Format-Bytes([long] $Bytes) {
    if ($Bytes -ge 1GB) { return '{0:N2} GB' -f ($Bytes / 1GB) }
    if ($Bytes -ge 1MB) { return '{0:N1} MB' -f ($Bytes / 1MB) }
    if ($Bytes -ge 1KB) { return '{0:N0} KB' -f ($Bytes / 1KB) }
    return "$Bytes B"
}

function Format-Duration([TimeSpan] $Span) {
    if ($Span.TotalHours -ge 1) { return $Span.ToString('h\:mm\:ss') }
    return $Span.ToString('mm\:ss')
}

function Test-NvencAvailable {
    $encoders = & ffmpeg -hide_banner -encoders 2>$null
    if ("$encoders" -notmatch 'h264_nvenc') { return $false }
    # NVENC rejects tiny frames (min ~128-145px); 256x256 is a safe probe.
    $probeLog = Join-Path $env:TEMP ("nvenc-probe-{0}.log" -f [guid]::NewGuid().ToString('n'))
    try {
        & ffmpeg -hide_banner -loglevel error -f lavfi -i 'color=c=black:s=256x256:d=0.2' `
            -frames:v 1 -c:v h264_nvenc -f null - 2>$probeLog | Out-Null
        return ($LASTEXITCODE -eq 0)
    } finally {
        Remove-Item -LiteralPath $probeLog -Force -ErrorAction SilentlyContinue
    }
}

$preferNvenc = switch ($Encoder) {
    'Nvenc' { $true }
    'Cpu' { $false }
    default { Test-NvencAvailable }
}

if ($Encoder -eq 'Nvenc' -and -not (Test-NvencAvailable)) {
    Write-Error 'Encoder Nvenc requested but h264_nvenc is not usable (check NVIDIA drivers / ffmpeg build).'
    exit 2
}
$allowCpuFallback = [bool]$AllowCpuFallback
if ($Encoder -eq 'Cpu') {
    $preferNvenc = $false
    $allowCpuFallback = $true
}

if ($Encoder -eq 'Auto' -and -not $preferNvenc) {
    Write-Host 'NVENC not available; using libx264 (CPU).' -ForegroundColor Yellow
} elseif ($preferNvenc) {
    $fbMsg = $allowCpuFallback ? 'CPU fallback ON' : 'no CPU fallback'
    Write-Host "NVENC OK - GPU encode enabled ($fbMsg)." -ForegroundColor Green
}

$files = @(Get-ChildItem -LiteralPath $inputDir -File -Filter '*.mp4')
if (-not $files) {
    Write-Host 'No .mp4 files found.'
    exit 0
}

$totalBytes = ($files | Measure-Object -Property Length -Sum).Sum
$total = $files.Count

Write-Host ""
Write-Host '┌─ fix-mp4s ─────────────────────────────────────────' -ForegroundColor Cyan
Write-Host "│ Input:    $inputDir"
Write-Host "│ Output:   $outputDir\<username>\"
$encLabel = if (-not $preferNvenc) {
    'libx264'
} elseif ($allowCpuFallback) {
    'h264_nvenc + libx264 fallback'
} else {
    'h264_nvenc only'
}
Write-Host "│ Encoder:  $encLabel"
Write-Host "│ Parallel: $Parallel   CQ: $($preferNvenc ? $NvencCq : 'n/a')   CPU threads: $CpuThreads"
Write-Host "│ Files:    $total   ($([string](Format-Bytes $totalBytes)))"
Write-Host '└────────────────────────────────────────────────────' -ForegroundColor Cyan
Write-Host ""

$live = [System.Collections.Concurrent.ConcurrentDictionary[string, string]]::new()

$work = for ($i = 0; $i -lt $files.Count; $i++) {
    $f = $files[$i]
    $r = Resolve-FixMp4Output -FileName $f.Name -OutputDir $outputDir
    [pscustomobject]@{
        Index   = $i + 1
        File    = $f
        User    = $r.User
        OutName = $r.OutName
        OutPath = $r.OutPath
        Pattern = $r.Pattern
    }
}

# NOTE: ForEach-Object -Parallel cannot $using: a scriptblock - keep all worker
# logic inline here and only pass simple/$using: values.
$job = $work | ForEach-Object -Parallel {
    $Index = $_.Index
    $File = $_.File
    $Total = $using:total
    $OutputDir = $using:outputDir
    $User = $_.User
    $OutName = $_.OutName
    $OutPath = $_.OutPath
    $Pattern = $_.Pattern
    $PreferNvenc = $using:preferNvenc
    $AllowCpuFallback = $using:allowCpuFallback
    $NvencCq = $using:NvencCq
    $CpuThreads = $using:CpuThreads
    $Live = $using:live

    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $short = $File.Name
    if ($short.Length -gt 52) { $short = $short.Substring(0, 49) + '...' }

    $result = [ordered]@{
        Index     = $Index
        Total     = $Total
        Status    = 'fail'
        Name      = $File.Name
        ShortName = $short
        Detail    = ''
        Encoder   = ''
        Pattern   = ''
        InBytes   = [long]$File.Length
        OutBytes  = [long]0
        Elapsed   = [TimeSpan]::Zero
    }

    if ($File.Length -eq 0) {
        $result.Status = 'skip'
        $result.Detail = 'empty (0 bytes)'
        $result.Elapsed = $sw.Elapsed
        return [pscustomobject]$result
    }

    $user = $User
    $outName = $OutName
    $out = $OutPath
    $result.Pattern = $Pattern
    $userDir = Join-Path $OutputDir $user
    New-Item -ItemType Directory -Force -Path $userDir | Out-Null

    if (Test-Path -LiteralPath $out) {
        $result.Status = 'skip'
        $result.Detail = "exists: $user\$outName"
        $result.Elapsed = $sw.Elapsed
        return [pscustomobject]$result
    }

    $probe = & ffprobe -v error -select_streams v:0 `
        -show_entries stream=width,height -of csv=p=0:s=x -- $File.FullName 2>$null
    $w = 1280
    $h = 720
    if ($probe -match '^(\d+)x(\d+)$') {
        $w = [int]$Matches[1]
        $h = [int]$Matches[2]
    }
    $w = [Math]::Max(2, $w - ($w % 2))
    $h = [Math]::Max(2, $h - ($h % 2))

    $durRaw = & ffprobe -v error -show_entries format=duration -of default=nk=1:nw=1 -- $File.FullName 2>$null
    $durationSec = 0.0
    if ($durRaw -match '^[\d.]+$') { $durationSec = [double]$durRaw }

    $vf = "scale=${w}:${h}:force_original_aspect_ratio=decrease,pad=${w}:${h}:(ow-iw)/2:(oh-ih)/2,setsar=1"

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

    function Invoke-Encode([string[]] $VideoArgs, [string] $Phase) {
        $progFile = Join-Path $env:TEMP ("fix-mp4s-prog-{0}.txt" -f [guid]::NewGuid().ToString('n'))
        $errFile = Join-Path $env:TEMP ("fix-mp4s-err-{0}.txt" -f [guid]::NewGuid().ToString('n'))
        Remove-Item -LiteralPath $progFile, $errFile -Force -ErrorAction SilentlyContinue
        if (Test-Path -LiteralPath $out) {
            Remove-Item -LiteralPath $out -Force -ErrorAction SilentlyContinue
        }

        $argList = @(
            '-hide_banner', '-y', '-nostats', '-loglevel', 'error',
            '-progress', $progFile,
            '-fflags', '+genpts+igndts+discardcorrupt',
            '-err_detect', 'ignore_err',
            '-i', $File.FullName,
            '-map', '0:v:0?', '-map', '0:a:0?',
            '-vf', $vf
        ) + $VideoArgs + @(
            '-c:a', 'aac', '-b:a', '160k', '-ac', '2',
            '-movflags', '+faststart',
            '-avoid_negative_ts', 'make_zero',
            '-pix_fmt', 'yuv420p',
            '-profile:v', 'high',
            '-tag:v', 'avc1',
            '-max_muxing_queue_size', '9999',
            $out
        )

        $null = $Live.AddOrUpdate($File.Name, "0% $Phase", { param($k, $v) "0% $Phase" })
        $proc = Start-Process -FilePath 'ffmpeg' -ArgumentList $argList `
            -WindowStyle Hidden -PassThru -RedirectStandardError $errFile
        try {
            while (-not $proc.HasExited) {
                if (Test-Path -LiteralPath $progFile) {
                    $lines = @(Get-Content -LiteralPath $progFile -ErrorAction SilentlyContinue)
                    $outUs = $null
                    foreach ($line in $lines) {
                        if ($line -match '^out_time_us=(\d+)$') { $outUs = [int64]$Matches[1] }
                        elseif ($line -match '^out_time_ms=(\d+)$') { $outUs = [int64]$Matches[1] * 1000 }
                    }
                    if ($null -ne $outUs) {
                        if ($durationSec -gt 0) {
                            $pct = [Math]::Max(0, [Math]::Min(99, [int](($outUs / 1000000.0) / $durationSec * 100)))
                            $null = $Live.AddOrUpdate($File.Name, "$pct% $Phase", { param($k, $old) "$pct% $Phase" })
                        } else {
                            $sec = [int]($outUs / 1000000)
                            $null = $Live.AddOrUpdate($File.Name, "$Phase ${sec}s", { param($k, $old) "$Phase ${sec}s" })
                        }
                    }
                }
                Start-Sleep -Milliseconds 400
            }
            $proc.WaitForExit()
            $code = $proc.ExitCode
        } finally {
            $null = $Live.TryRemove($File.Name, [ref]$null)
            Remove-Item -LiteralPath $progFile, $errFile -Force -ErrorAction SilentlyContinue
        }
        return ($code -eq 0 -and (Test-DashPlayable $out))
    }

    $used = $null
    $ok = $false

    if ($PreferNvenc) {
        $ok = Invoke-Encode -VideoArgs @(
            '-c:v', 'h264_nvenc', '-preset', 'p5', '-tune', 'hq',
            '-rc', 'vbr', '-cq', "$NvencCq", '-b:v', '0',
            '-spatial-aq', '1', '-temporal-aq', '1', '-bf', '2'
        ) -Phase 'nvenc'
        if ($ok) { $used = 'nvenc' }
    }

    # CPU only when Encoder=Cpu / NVENC unavailable, or -AllowCpuFallback.
    if (-not $ok -and (-not $PreferNvenc -or $AllowCpuFallback)) {
        $ok = Invoke-Encode -VideoArgs @(
            '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20',
            '-threads', "$CpuThreads"
        ) -Phase ($PreferNvenc ? 'x264-fb' : 'x264')
        if ($ok) { $used = $PreferNvenc ? 'x264-fallback' : 'x264' }
    }

    $result.Elapsed = $sw.Elapsed
    if ($ok) {
        $result.Status = 'ok'
        $result.Encoder = $used
        $result.Detail = "$user\$outName (${w}x${h})"
        if (Test-Path -LiteralPath $out) {
            $result.OutBytes = [long](Get-Item -LiteralPath $out).Length
        }
        return [pscustomobject]$result
    }

    if (Test-Path -LiteralPath $out) {
        Remove-Item -LiteralPath $out -Force -ErrorAction SilentlyContinue
    }
    $result.Status = 'fail'
    $result.Detail = ($PreferNvenc -and -not $AllowCpuFallback) ?
        'NVENC failed (no CPU fallback)' :
        'could not produce dashboard-playable H.264'
    return [pscustomobject]$result
} -ThrottleLimit $Parallel -AsJob

$ok = 0; $skip = 0; $fail = 0
$nv = 0; $fb = 0; $cpu = 0
$done = 0
$seen = [System.Collections.Generic.HashSet[string]]::new()
$swAll = [System.Diagnostics.Stopwatch]::StartNew()

function Write-ResultLine($r) {
    $idx = '[{0}/{1}]' -f $r.Index, $r.Total
    $time = Format-Duration $r.Elapsed
    $inSz = Format-Bytes $r.InBytes
    switch ($r.Status) {
        'ok' {
            $outSz = Format-Bytes $r.OutBytes
            $ratio = $r.InBytes -gt 0 ? ('{0:N0}%' -f (100.0 * $r.OutBytes / $r.InBytes)) : '?'
            Write-Host "  x $idx " -ForegroundColor Green -NoNewline
            Write-Host "$($r.ShortName) " -NoNewline
            Write-Host "-> $($r.Detail) " -ForegroundColor DarkGray -NoNewline
            Write-Host "[$($r.Encoder)] " -ForegroundColor Cyan -NoNewline
            if ($r.Pattern) {
                Write-Host "[$($r.Pattern)] " -ForegroundColor DarkCyan -NoNewline
            }
            Write-Host "$inSz->$outSz ($ratio) " -ForegroundColor DarkGray -NoNewline
            Write-Host $time -ForegroundColor DarkGray
        }
        'skip' {
            Write-Host "  · $idx " -ForegroundColor DarkYellow -NoNewline
            Write-Host "$($r.ShortName) " -NoNewline
            Write-Host "skip - $($r.Detail)" -ForegroundColor DarkGray
        }
        'fail' {
            Write-Host "  x $idx " -ForegroundColor Red -NoNewline
            Write-Host "$($r.ShortName) " -NoNewline
            Write-Host "FAIL - $($r.Detail)" -ForegroundColor Red
        }
    }
}

function Receive-Batch {
    if (-not $job) { return }
    $batch = @(Receive-Job -Job $job -ErrorAction SilentlyContinue)
    foreach ($r in $batch) {
        if ($null -eq $r -or -not $r.Name) { continue }
        $key = '{0}:{1}' -f $r.Index, $r.Name
        if (-not $seen.Add($key)) { continue }
        $script:done++
        switch ($r.Status) {
            'ok' {
                $script:ok++
                switch ($r.Encoder) {
                    'nvenc' { $script:nv++ }
                    'x264-fallback' { $script:fb++ }
                    'x264' { $script:cpu++ }
                }
            }
            'skip' { $script:skip++ }
            'fail' { $script:fail++ }
        }
        Write-ResultLine $r
    }
}

function Update-ProgressBar {
    $pct = $total -gt 0 ? [int](100 * $done / $total) : 100
    $elapsed = $swAll.Elapsed
    $etaText = '--:--'
    if ($done -gt 0 -and $done -lt $total) {
        $avgTicks = $elapsed.Ticks / [Math]::Max(1, $done)
        $etaText = Format-Duration ([TimeSpan]::FromTicks([int64]($avgTicks * ($total - $done))))
    } elseif ($done -ge $total -and $total -gt 0) {
        $etaText = '0:00'
    }

    $activeParts = @(foreach ($kv in $live.GetEnumerator()) {
        $n = $kv.Key
        if ($n.Length -gt 28) { $n = $n.Substring(0, 25) + '...' }
        '{0} {1}' -f $n, $kv.Value
    })
    $activeText = $activeParts.Count -gt 0 ? ($activeParts -join '  ·  ') : 'starting encoders…'

    # Fold active encodes into Status - some hosts hide CurrentOperation.
    $status = "ok=$ok  skip=$skip  fail=$fail  |  {0}  |  ETA {1}" -f (Format-Duration $elapsed), $etaText
    if ($activeParts.Count -gt 0) {
        $status = "$status  |  $activeText"
    }

    Write-Progress `
        -Id 1 `
        -Activity "fix-mp4s  $done / $total  ($pct%)" `
        -Status $status `
        -PercentComplete ([Math]::Min(100, $pct)) `
        -CurrentOperation $activeText
}

try {
    while ($job) {
        Receive-Batch
        Update-ProgressBar
        if ($job.State -ne 'Running') {
            Start-Sleep -Milliseconds 200
            Receive-Batch
            break
        }
        Start-Sleep -Milliseconds 350
    }
} finally {
    Receive-Batch
    Write-Progress -Id 1 -Activity 'fix-mp4s' -Completed
    if ($job) {
        Remove-Job -Job $job -Force -ErrorAction SilentlyContinue
    }
}

Write-Host ""
Write-Host '┌─ summary ──────────────────────────────────────────' -ForegroundColor Cyan
Write-Host ("│ Done in {0}" -f (Format-Duration $swAll.Elapsed))
Write-Host ("│ ok={0}  (nvenc={1}  fallback={2}  x264={3})  skip={4}  fail={5}" -f $ok, $nv, $fb, $cpu, $skip, $fail)
Write-Host "│ -> $outputDir"
Write-Host '│ OK files are ffprobe-verified H.264/yuv420p for the dashboard <video>.'
Write-Host '└────────────────────────────────────────────────────' -ForegroundColor Cyan
Write-Host ""
exit ($fail -gt 0 ? 1 : 0)
