# Installs 64-bit Ghostscript on Windows by downloading the latest release from Artifex (GitHub).
# Silent install, then outputs the discovered gswin64c.exe path on success.
# Usage: powershell -ExecutionPolicy Bypass -File scripts\Install-Ghostscript.ps1

param(
  [string]$OutFile = "$env:TEMP\ghostscript_installer.exe"
)

$ProgressPreference = 'SilentlyContinue'
$ErrorActionPreference = 'Stop'

try {
  Write-Host "Fetching latest Ghostscript release metadata..."
  $headers = @{ 'User-Agent' = 'curl/7.55.0' }
  $release = Invoke-RestMethod -Uri 'https://api.github.com/repos/ArtifexSoftware/ghostpdl-downloads/releases/latest' -Headers $headers

  $asset = $release.assets | Where-Object { $_.name -match '^gs.*w64\.exe$' } | Select-Object -First 1
  if (-not $asset) {
    throw "Could not find a 64-bit Ghostscript installer asset in latest release."
  }

  Write-Host "Downloading $($asset.name) ..."
  Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $OutFile -UseBasicParsing

  Write-Host "Running silent installer ..."
  Start-Process -FilePath $OutFile -ArgumentList '/S' -Wait

  # Verify installation by locating gswin64c.exe
  Write-Host "Locating gswin64c.exe ..."
  $gs = Get-ChildItem -Path 'C:\Program Files','C:\Program Files (x86)' -Filter gswin64c.exe -Recurse -ErrorAction SilentlyContinue |
    Select-Object -First 1 -ExpandProperty FullName

  if ($gs) {
    Write-Output "GS_PATH=$gs"
    exit 0
  } else {
    throw "Ghostscript CLI (gswin64c.exe) not found after install."
  }
}
catch {
  Write-Error $_
  exit 1
}
