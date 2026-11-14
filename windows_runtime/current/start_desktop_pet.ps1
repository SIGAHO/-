param(
    [switch]$LookNow,
    [string]$Sprite,
    [string]$Model = 'qwen3.5:4b'
)
$ErrorActionPreference = 'Stop'
$runtime = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $Sprite) { $Sprite = Join-Path (Split-Path -Parent $runtime) 'assets\gomi_blink.gif' }
if (-not (Test-Path -LiteralPath $Sprite)) { throw "Sprite GIF がありません: $Sprite" }

$bundled = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\pythonw.exe'
if (Test-Path -LiteralPath $bundled) {
    $pythonw = $bundled
} else {
    $pythonw = (Get-Command pythonw.exe -ErrorAction Stop).Source
}
$python = Join-Path (Split-Path -Parent $pythonw) 'python.exe'
& $python -c 'import tkinter; from PIL import Image, ImageTk, ImageGrab'
if ($LASTEXITCODE -ne 0) { throw 'Python の Tkinter と Pillow が必要です。' }

$script = Join-Path $runtime 'breaktail_desktop_pet.py'
$running = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
    Where-Object { $_.CommandLine -and $_.CommandLine.Contains($script) } |
    Select-Object -First 1
if ($running) {
    Write-Host "Breaktailの画面キャラは起動済みです (PID $($running.ProcessId))。"
    return
}
$arguments = @($script, '--sprite', $Sprite, '--model', $Model)
if ($LookNow) { $arguments += '--look-on-start' }
$pet = Start-Process -FilePath $pythonw -ArgumentList $arguments -WorkingDirectory $runtime -PassThru
Start-Sleep -Milliseconds 800
if ($pet.HasExited) { throw 'Breaktail の画面キャラが起動直後に終了しました。' }
Write-Host "Breaktailの画面キャラを起動しました (PID $($pet.Id))。右クリックで画面を見る・自動観察・終了を選べます。"

