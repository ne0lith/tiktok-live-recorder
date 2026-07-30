#Requires -Version 7.0
# Shared output routing for fix-mp4s.ps1 and delete-verified-sources.ps1

$script:FixMp4TkRe = [regex]'^TK_(.+)_(\d{4}\.\d{2}\.\d{2}_\d{2}-\d{2}-\d{2})(?:_flv)?\.mp4$'
$script:FixMp4ImgRe = [regex]'^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_IMG_\d+\.mp4$'

function Resolve-FixMp4Output {
    param(
        [string] $FileName,
        [string] $OutputDir
    )

    $tk = $script:FixMp4TkRe.Match($FileName)
    if ($tk.Success) {
        $user = $tk.Groups[1].Value
        $outName = $FileName -replace '_flv\.mp4$', '.mp4'
        return [pscustomobject]@{
            User    = $user
            OutName = $outName
            OutPath = Join-Path (Join-Path $OutputDir $user) $outName
            Pattern = 'tk'
        }
    }

    if ($script:FixMp4ImgRe.IsMatch($FileName)) {
        return [pscustomobject]@{
            User    = '_unknown'
            OutName = $FileName
            OutPath = Join-Path (Join-Path $OutputDir '_unknown') $FileName
            Pattern = 'img'
        }
    }

    $outName = $FileName -replace '_flv\.mp4$', '.mp4'
    return [pscustomobject]@{
        User    = '_unknown'
        OutName = $outName
        OutPath = Join-Path (Join-Path $OutputDir '_unknown') $outName
        Pattern = 'other'
    }
}
