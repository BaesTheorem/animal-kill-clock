# Animal Kill Clock -- Windows one-line installer. Run in PowerShell:
#
#   irm https://raw.githubusercontent.com/BaesTheorem/animal-kill-clock/main/install.ps1 | iex
#
# Why this never trips SmartScreen: SmartScreen only screens files stamped with
# the Mark-of-the-Web, which browsers attach to downloads as a Zone.Identifier
# stream. Nothing here is a downloaded file -- `irm | iex` runs this script from
# memory, and the widget is then WRITTEN to disk by your own PowerShell session
# from fetched text. A locally written file has no Mark-of-the-Web, so there is
# nothing for SmartScreen to warn about. The widget itself runs on mshta.exe,
# which ships with Windows, so no third-party executable is installed at all.
# You are trusting readable source, not somebody's unsigned binary.
#
# What it does:
#   1. writes AnimalKillClock.hta to %LOCALAPPDATA%\AnimalKillClock
#   2. puts an "Animal Kill Clock" shortcut on your Desktop
#   3. launches the widget
#
# Optional: run with -Startup to also start it at login.
#   & ([scriptblock]::Create((irm .../install.ps1))) -Startup
#
# Uninstall: delete the shortcut(s) and %LOCALAPPDATA%\AnimalKillClock
param([switch]$Startup)

$ErrorActionPreference = "Stop"
$repo = "BaesTheorem/animal-kill-clock"
$dir  = Join-Path $env:LOCALAPPDATA "AnimalKillClock"
$hta  = Join-Path $dir "AnimalKillClock.hta"

Write-Host "==> Fetching the widget source" -ForegroundColor Cyan
$src = Invoke-RestMethod "https://raw.githubusercontent.com/$repo/main/windows/AnimalKillClock.hta"

New-Item -ItemType Directory -Force -Path $dir | Out-Null
# Written from memory by this session: no Zone.Identifier, no SmartScreen.
Set-Content -Path $hta -Value $src -Encoding UTF8
# Belt and braces for machines with unusual zone policies; no-op otherwise.
Unblock-File -Path $hta -ErrorAction SilentlyContinue

Write-Host "==> Creating shortcuts" -ForegroundColor Cyan
$shell = New-Object -ComObject WScript.Shell
$mshta = Join-Path $env:WINDIR "System32\mshta.exe"

function New-AkcShortcut([string]$where) {
    $lnk = $shell.CreateShortcut((Join-Path $where "Animal Kill Clock.lnk"))
    $lnk.TargetPath = $mshta
    $lnk.Arguments = '"' + $hta + '"'
    $lnk.WorkingDirectory = $dir
    $lnk.Description = "Animal Kill Clock widget (animalclock.org)"
    $lnk.Save()
}

New-AkcShortcut ([Environment]::GetFolderPath("Desktop"))
if ($Startup) {
    New-AkcShortcut ([Environment]::GetFolderPath("Startup"))
    Write-Host "    (will also start at login)"
}

Write-Host "==> Launching" -ForegroundColor Cyan
Start-Process $mshta -ArgumentList ('"' + $hta + '"')

Write-Host "Done. Drag the card anywhere; Esc closes it." -ForegroundColor Green
Write-Host "Settings live at the top of $hta (open it in Notepad)."
