#Requires -Version 7.0
# fix-mp4s.ps1 - salvage MP4s into <OutputDir>\<username>\
#
# Target player: THIS project's media library - plain <video> in Chromium/Edge.
# Forces H.264 (avc1) + yuv420p + AAC + faststart + fixed canvas; ffprobe-verified.
# NVENC by default: NVDEC decode + scale_cuda/pad_cuda + h264_nvenc (frames stay on GPU).
# No silent CPU fallback unless -AllowCpuFallback (software vf+NVENC, then libx264).
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

function Test-CudaPipelineAvailable {
    # NVDEC + scale_cuda + pad_cuda + NVENC; lavfi upload keeps the probe self-contained.
    $filters = & ffmpeg -hide_banner -filters 2>$null | Out-String
    if ($filters -notmatch 'scale_cuda' -or $filters -notmatch 'pad_cuda') { return $false }
    $hw = @(& ffmpeg -hide_banner -hwaccels 2>$null | ForEach-Object { "$_".Trim() } | Where-Object { $_ })
    if ($hw -notcontains 'cuda') { return $false }
    $probeLog = Join-Path $env:TEMP ("cuda-pipe-probe-{0}.log" -f [guid]::NewGuid().ToString('n'))
    try {
        & ffmpeg -hide_banner -loglevel error -f lavfi -i 'color=c=black:s=256x256:d=0.2' `
            -vf 'hwupload_cuda,scale_cuda=256:256:format=nv12,pad_cuda=256:256:0:0:black' `
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

$useCudaPipeline = $false
if ($preferNvenc) {
    $useCudaPipeline = Test-CudaPipelineAvailable
    if (-not $useCudaPipeline -and -not $allowCpuFallback -and $Encoder -eq 'Nvenc') {
        Write-Error 'Encoder Nvenc requested but CUDA filter pipeline (NVDEC/scale_cuda/pad_cuda) is not usable, and -AllowCpuFallback was not set.'
        exit 2
    }
}

if ($Encoder -eq 'Auto' -and -not $preferNvenc) {
    Write-Host 'NVENC not available; using libx264 (CPU).' -ForegroundColor Yellow
} elseif ($preferNvenc -and $useCudaPipeline) {
    $fbMsg = $allowCpuFallback ? 'CPU fallback ON' : 'no CPU fallback'
    Write-Host "CUDA pipeline OK - NVDEC + scale_cuda/pad_cuda + NVENC ($fbMsg)." -ForegroundColor Green
} elseif ($preferNvenc) {
    if ($allowCpuFallback) {
        Write-Host 'CUDA filters unavailable; NVENC encode with CPU scale (CPU fallback ON).' -ForegroundColor Yellow
    } else {
        Write-Host 'CUDA filters unavailable; NVENC encode with CPU scale (decode/scale on CPU).' -ForegroundColor Yellow
    }
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
} elseif ($useCudaPipeline -and $allowCpuFallback) {
    'NVDEC+CUDA vf+NVENC (+ CPU fallback)'
} elseif ($useCudaPipeline) {
    'NVDEC+CUDA vf+NVENC only'
} elseif ($allowCpuFallback) {
    'h264_nvenc (CPU vf) + libx264 fallback'
} else {
    'h264_nvenc (CPU vf) only'
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
    $UseCudaPipeline = $using:useCudaPipeline
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

    $srcVideo = & ffprobe -v error -select_streams v:0 `
        -show_entries stream=codec_name,pix_fmt -of csv=p=0 -- $File.FullName 2>$null
    $srcVideoParts = @("$srcVideo".Trim() -split ',')
    $srcPixFmt = if ($srcVideoParts.Count -ge 2) { $srcVideoParts[1].Trim().ToLowerInvariant() } else { '' }

    $srcAudio = & ffprobe -v error -select_streams a:0 `
        -show_entries stream=codec_name -of csv=p=0 -- $File.FullName 2>$null
    $srcAudioCodec = "$srcAudio".Trim().ToLowerInvariant()

    # -ignore_editlist is a mov/mp4 demuxer option only. Leftover recordings are often
    # real FLV bytes with a .mp4 name (format_name=flv); passing it there fails open.
    $srcFormat = & ffprobe -v error -show_entries format=format_name -of default=nk=1:nw=1 -- $File.FullName 2>$null
    $srcFormat = "$srcFormat".Trim().ToLowerInvariant()
    $useIgnoreEditlist = $srcFormat -match '(^|,)(mov|mp4|m4a|3gp|3g2|mj2)(,|$)'

    # Always re-encode video at the requested quality. setpts resets broken timestamps (CPU path).
    # CUDA path keeps frames on GPU (NVDEC -> scale_cuda/pad_cuda -> NVENC); genpts/reset_timestamps
    # cover broken input timing without a software setpts filter.
    $rangeFix = if ($srcPixFmt -eq 'yuvj420p') {
        ',scale=in_range=full:out_range=limited'
    } else {
        ''
    }
    $vfCpu = "scale=${w}:${h}:force_original_aspect_ratio=decrease,pad=${w}:${h}:(ow-iw)/2:(oh-ih)/2,format=yuv420p${rangeFix},setsar=1,setpts=PTS-STARTPTS"
    $vfCuda = "scale_cuda=${w}:${h}:force_original_aspect_ratio=decrease:force_divisible_by=2:format=nv12,pad_cuda=${w}:${h}:(ow-iw)/2:(oh-ih)/2:black"
    $cudaHwArgs = @(
        '-hwaccel', 'cuda',
        '-hwaccel_output_format', 'cuda',
        '-extra_hw_frames', '8',
        # Corrupt leftover FLVs often change size/format mid-stream (packet mismatch).
        # CUDA graphs cannot reinit (pad_cuda -> software auto_scale, ffmpeg -40).
        # Drop the changed frame instead of rebuilding the filtergraph.
        '-drop_changed:v', '1'
    )

    $encodeTailCpu = @(
        '-avoid_negative_ts', 'make_zero',
        '-reset_timestamps', '1',
        '-pix_fmt', 'yuv420p',
        '-profile:v', 'high',
        '-tag:v', 'avc1',
        '-max_muxing_queue_size', '9999'
    )
    # Do not force -pix_fmt yuv420p on CUDA frames (inserts a software auto_scale).
    # Clear full-range flag so ffprobe/dashboard see yuv420p (phone HEVC is often yuvj420p/pc).
    $encodeTailCuda = @(
        '-avoid_negative_ts', 'make_zero',
        '-reset_timestamps', '1',
        '-profile:v', 'high',
        '-tag:v', 'avc1',
        '-bsf:v', 'h264_metadata=video_full_range_flag=0',
        '-max_muxing_queue_size', '9999'
    )

    $nvencVideoArgs = @(
        '-c:v', 'h264_nvenc', '-preset', 'p5', '-tune', 'hq',
        '-rc', 'vbr', '-cq', "$NvencCq", '-b:v', '0',
        '-spatial-aq', '1', '-temporal-aq', '1', '-bf', '2'
    )

    $x264VideoArgs = @(
        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20',
        '-threads', "$CpuThreads"
    )

    function Test-EncodedVideo([string] $Path) {
        if (-not (Test-Path -LiteralPath $Path)) { return $false }
        if ((Get-Item -LiteralPath $Path).Length -le 0) { return $false }
        $v = & ffprobe -v error -select_streams v:0 `
            -show_entries stream=codec_name -of csv=p=0 -- $Path 2>$null
        return ("$v".Trim().ToLowerInvariant() -eq 'h264')
    }

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

    function Get-FfmpegErrTail([string] $ErrFile, [int] $MaxLines = 4, [int] $MaxChars = 240) {
        if (-not (Test-Path -LiteralPath $ErrFile)) { return $null }
        $lines = @(Get-Content -LiteralPath $ErrFile -ErrorAction SilentlyContinue |
            ForEach-Object { "$_".Trim() } |
            Where-Object { $_ })
        if (-not $lines.Count) { return $null }
        $tail = if ($lines.Count -gt $MaxLines) {
            $lines[($lines.Count - $MaxLines)..($lines.Count - 1)]
        } else {
            $lines
        }
        $text = $tail -join ' | '
        if ($text.Length -gt $MaxChars) {
            $text = $text.Substring(0, $MaxChars - 3) + '...'
        }
        return $text
    }

    function Save-FfmpegFailureLog([string] $ErrFile, [string] $SourceName, [string] $Phase) {
        $failDir = Join-Path $OutputDir '_fix-mp4s-failures'
        New-Item -ItemType Directory -Force -Path $failDir | Out-Null
        $safe = ($SourceName -replace '[^\w.\-]', '_')
        $dest = Join-Path $failDir ("{0}.{1}.log" -f $safe, $Phase)
        if (Test-Path -LiteralPath $ErrFile) {
            Copy-Item -LiteralPath $ErrFile -Destination $dest -Force
            return $dest
        }
        return $null
    }

    function Invoke-FfmpegJob {
        param(
            [string] $Phase,
            [string[]] $MiddleArgs,
            [string[]] $BeforeInputArgs = @(),
            [string] $InputPath = $File.FullName,
            [string] $OutputPath = $out,
            [switch] $TrackProgress,
            [switch] $VerifyDashboardPlayable
        )

        $progFile = Join-Path $env:TEMP ("fix-mp4s-prog-{0}.txt" -f [guid]::NewGuid().ToString('n'))
        $errFile = Join-Path $env:TEMP ("fix-mp4s-err-{0}.txt" -f [guid]::NewGuid().ToString('n'))
        Remove-Item -LiteralPath $progFile, $errFile -Force -ErrorAction SilentlyContinue
        if (Test-Path -LiteralPath $OutputPath) {
            Remove-Item -LiteralPath $OutputPath -Force -ErrorAction SilentlyContinue
        }

        $argList = @(
            '-hide_banner', '-y', '-nostats', '-loglevel', 'error'
        )
        if ($TrackProgress) {
            $argList += '-progress', $progFile
        }
        $argList += '-fflags', '+genpts+igndts+discardcorrupt'
        $argList += '-err_detect', 'ignore_err'
        if ($BeforeInputArgs -and $BeforeInputArgs.Count) {
            $argList += $BeforeInputArgs
        }
        # mov/mp4 only - must stay immediately before -i for the next input.
        if ($InputPath -ceq $File.FullName -and $useIgnoreEditlist) {
            $argList += '-ignore_editlist', '1'
        }
        $argList += '-i', $InputPath
        $argList += $MiddleArgs
        $argList += $OutputPath

        if ($TrackProgress) {
            $null = $Live.AddOrUpdate($File.Name, "0% $Phase", { param($k, $v) "0% $Phase" })
        }
        $proc = Start-Process -FilePath 'ffmpeg' -ArgumentList $argList `
            -WindowStyle Hidden -PassThru -RedirectStandardError $errFile
        $code = -1
        try {
            while (-not $proc.HasExited) {
                if ($TrackProgress -and (Test-Path -LiteralPath $progFile)) {
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
            if ($TrackProgress) {
                $null = $Live.TryRemove($File.Name, [ref]$null)
            }
        }

        $verified = if ($VerifyDashboardPlayable) {
            Test-DashPlayable $OutputPath
        } else {
            Test-EncodedVideo $OutputPath
        }
        $playable = ($code -eq 0) -and $verified
        $reason = $null
        $logFile = $null
        if (-not $playable) {
            $reason = Get-FfmpegErrTail -ErrFile $errFile
            $logFile = Save-FfmpegFailureLog -ErrFile $errFile -SourceName $File.Name -Phase $Phase
            if (-not $reason) {
                if ($code -ne 0) {
                    $reason = "ffmpeg exit $code"
                } elseif (Test-Path -LiteralPath $OutputPath) {
                    $reason = if ($VerifyDashboardPlayable) {
                        'output failed ffprobe (not H.264/yuv420p)'
                    } else {
                        'intermediate encode missing H.264 video'
                    }
                } else {
                    $reason = 'no output file produced'
                }
            }
        }

        Remove-Item -LiteralPath $progFile, $errFile -Force -ErrorAction SilentlyContinue
        return [pscustomobject]@{
            Ok       = $playable
            Phase    = $Phase
            ExitCode = $code
            Reason   = $reason
            LogFile  = $logFile
        }
    }

    function Get-RemuxMapArgs([string] $InputPath) {
        $hasAudio = & ffprobe -v error -select_streams a:0 `
            -show_entries stream=codec_type -of csv=p=0 -- $InputPath 2>$null
        if ("$hasAudio".Trim()) {
            return @('-map', '0:v:0?', '-map', '0:a:0?')
        }
        return @('-map', '0:v:0?')
    }

    function Format-EncodeFailures([object[]] $Attempts, [bool] $NoCpuFallback) {
        $parts = foreach ($a in $Attempts) {
            $bit = $a.Phase
            if ($a.ExitCode -ne 0) { $bit += " exit $($a.ExitCode)" }
            if ($a.Reason) { $bit += ": $($a.Reason)" }
            if ($a.LogFile) { $bit += " [log: $($a.LogFile)]" }
            $bit
        }
        $head = if ($NoCpuFallback -and $Attempts.Count -ge 1 -and ($Attempts[0].Phase -match '^nvenc')) {
            'NVENC/CUDA pipeline failed (no CPU fallback)'
        } else {
            'could not produce dashboard-playable H.264'
        }
        return "$head - " + ($parts -join '; ')
    }

    function Get-StreamMapArgs([string[]] $AudioArgs) {
        if ($AudioArgs -contains '-an') {
            return @('-map', '0:v:0?')
        }
        return @('-map', '0:v:0?', '-map', '0:a:0?')
    }

    function Get-AudioEncodeAttempts([string] $Codec) {
        $aacReencode = @(
            '-af', 'aresample=async=1:first_pts=0',
            '-c:a', 'aac', '-b:a', '160k', '-ac', '2'
        )
        if ($Codec -eq 'aac') {
            return @(
                [pscustomobject]@{ Label = 'aac-copy'; Args = @('-c:a', 'copy') },
                [pscustomobject]@{ Label = 'aac-re'; Args = $aacReencode },
                [pscustomobject]@{ Label = 'an'; Args = @('-an') }
            )
        }
        return @(
            [pscustomobject]@{ Label = 'aac-re'; Args = $aacReencode },
            [pscustomobject]@{ Label = 'an'; Args = @('-an') }
        )
    }

    function Invoke-VideoEncode {
        param(
            [string] $Phase,
            [string[]] $VideoArgs,
            [string[]] $AudioArgs,
            [string] $Vf,
            [string[]] $EncodeTailArgs,
            [string[]] $BeforeInputArgs = @()
        )
        $tempMkv = Join-Path $env:TEMP ("fix-mp4s-{0}-{1}.mkv" -f [guid]::NewGuid().ToString('n'), $Phase)
        try {
            # Corrupt salvaged MP4s often fail the MP4 muxer during NVENC. Encode to MKV
            # at the requested quality, then remux to dashboard MP4 without re-encoding.
            $encodeMiddle = (Get-StreamMapArgs -AudioArgs $AudioArgs) + @(
                '-vf', $Vf
            ) + $VideoArgs + $AudioArgs + $EncodeTailArgs
            $encode = Invoke-FfmpegJob -Phase $Phase -TrackProgress `
                -OutputPath $tempMkv `
                -BeforeInputArgs $BeforeInputArgs `
                -MiddleArgs $encodeMiddle `
                -VerifyDashboardPlayable:$false
            if (-not $encode.Ok) {
                return $encode
            }

            $remuxPhase = "$Phase+mp4"
            $remuxMiddle = (Get-RemuxMapArgs -InputPath $tempMkv) + @(
                '-c', 'copy',
                '-movflags', '+faststart',
                '-tag:v', 'avc1'
            )
            $remux = Invoke-FfmpegJob -Phase $remuxPhase `
                -InputPath $tempMkv `
                -OutputPath $out `
                -MiddleArgs $remuxMiddle `
                -VerifyDashboardPlayable
            return $remux
        } finally {
            Remove-Item -LiteralPath $tempMkv -Force -ErrorAction SilentlyContinue
        }
    }

    function Try-VideoEncode {
        param(
            [string] $EncoderPhase,
            [string[]] $VideoArgs,
            [string] $Vf,
            [string[]] $EncodeTailArgs,
            [string[]] $BeforeInputArgs = @()
        )
        $failed = @()
        foreach ($audio in (Get-AudioEncodeAttempts -Codec $srcAudioCodec)) {
            $phase = if ($audio.Label -eq 'aac-copy') { $EncoderPhase } else { "$EncoderPhase+$($audio.Label)" }
            $enc = Invoke-VideoEncode -Phase $phase -VideoArgs $VideoArgs -AudioArgs $audio.Args `
                -Vf $Vf -EncodeTailArgs $EncodeTailArgs -BeforeInputArgs $BeforeInputArgs
            if ($enc.Ok) {
                return [pscustomobject]@{ Result = $enc; Failures = $failed }
            }
            $failed += $enc
        }
        return [pscustomobject]@{ Result = $null; Failures = $failed }
    }

    $used = $null
    $ok = $false
    $failures = @()

    if ($PreferNvenc -and $UseCudaPipeline) {
        $try = Try-VideoEncode -EncoderPhase 'nvenc' -VideoArgs $nvencVideoArgs `
            -Vf $vfCuda -EncodeTailArgs $encodeTailCuda -BeforeInputArgs $cudaHwArgs
        if ($try.Result) {
            $ok = $true
            $used = 'nvenc'
        } else {
            $failures = @($try.Failures)
        }
    }

    # Software vf + NVENC: only when CUDA pipeline is off, or -AllowCpuFallback after CUDA failed.
    if (-not $ok -and $PreferNvenc -and (-not $UseCudaPipeline -or $AllowCpuFallback)) {
        $swPhase = if ($UseCudaPipeline) { 'nvenc-swf' } else { 'nvenc' }
        $try = Try-VideoEncode -EncoderPhase $swPhase -VideoArgs $nvencVideoArgs `
            -Vf $vfCpu -EncodeTailArgs $encodeTailCpu
        if ($try.Result) {
            $ok = $true
            $used = if ($UseCudaPipeline) { 'nvenc-swf' } else { 'nvenc' }
        } else {
            $failures += $try.Failures
        }
    }

    # libx264 only when Encoder=Cpu / NVENC unavailable, or -AllowCpuFallback.
    if (-not $ok -and (-not $PreferNvenc -or $AllowCpuFallback)) {
        $cpuPhase = $PreferNvenc ? 'x264-fb' : 'x264'
        $try = Try-VideoEncode -EncoderPhase $cpuPhase -VideoArgs $x264VideoArgs `
            -Vf $vfCpu -EncodeTailArgs $encodeTailCpu
        if ($try.Result) {
            $ok = $true
            $used = $PreferNvenc ? 'x264-fallback' : 'x264'
        } else {
            $failures += $try.Failures
        }
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
    $noCpuFallback = $PreferNvenc -and -not $AllowCpuFallback
    $result.Detail = Format-EncodeFailures -Attempts $failures -NoCpuFallback $noCpuFallback
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
                    'nvenc-swf' { $script:fb++ }
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
if ($fail -gt 0) {
    Write-Host "│ failure logs: $outputDir\_fix-mp4s-failures\"
}
Write-Host '│ OK files are ffprobe-verified H.264/yuv420p for the dashboard <video>.'
Write-Host '└────────────────────────────────────────────────────' -ForegroundColor Cyan
Write-Host ""
exit ($fail -gt 0 ? 1 : 0)
