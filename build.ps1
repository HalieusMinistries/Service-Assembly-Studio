$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host "Installing dependencies..."
python -m pip install -r requirements.txt --quiet

Write-Host "Running tests..."
python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) {
    throw "Tests failed."
}

Write-Host "Building executable..."
python -m PyInstaller `
    --noconfirm `
    --windowed `
    --name "Service Assembly Studio" `
    --collect-all PySide6 `
    main.py

$DistDir = Join-Path $Root "dist\Service Assembly Studio"
$FfmpegSrc = "C:\Users\user\ffmpeg\ffmpeg-8.1-essentials_build\bin"
if (Test-Path $FfmpegSrc) {
    Write-Host "Bundling FFmpeg..."
    $FfmpegDest = Join-Path $DistDir "ffmpeg\bin"
    New-Item -ItemType Directory -Force -Path $FfmpegDest | Out-Null
    Copy-Item (Join-Path $FfmpegSrc "ffmpeg.exe") $FfmpegDest
    Copy-Item (Join-Path $FfmpegSrc "ffprobe.exe") $FfmpegDest
}

Write-Host "Build complete: $DistDir"
