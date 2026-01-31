# Run OCRmyPDF on a PDF to generate a searchable text layer (-ocr.pdf).
# - Locates Tesseract, QPDF, and Ghostscript; installs Ghostscript if missing (via Install-Ghostscript.ps1).
# - Uses Python launcher `py` to invoke OCRmyPDF.
# Usage examples:
#   powershell -ExecutionPolicy Bypass -File .\scripts\Ocr-PDF.ps1
#   powershell -ExecutionPolicy Bypass -File .\scripts\Ocr-PDF.ps1 -Input "demo-app/assets/Physician_Report_Scanned.pdf" -Sidecar
#   powershell -ExecutionPolicy Bypass -File .\scripts\Ocr-PDF.ps1 -Input "C:\any\path\file.pdf" -Lang eng -Optimize 0 -Force
param(
  [Parameter(Mandatory = $false)]
  [string]$Source = "demo-app/assets/Physician_Report_Scanned.pdf",

  [Parameter(Mandatory = $false)]
  [string]$Output,

  [switch]$Sidecar,
  [string]$Lang = "eng",
  [int]$Optimize = 0,
  [switch]$Force
)

$ProgressPreference = 'SilentlyContinue'
$ErrorActionPreference = 'Stop'

function Get-RepoRoot {
  return (Resolve-Path (Split-Path -Parent $PSScriptRoot)).Path
}

function Resolve-AbsolutePath([string]$p) {
  if ([string]::IsNullOrWhiteSpace($p)) { return $null }
  # Normalize to Windows separators to avoid Path.Combine treating a leading '/' as rooted
  $pn = $p -replace '/', '\'
  if ([System.IO.Path]::IsPathRooted($pn)) {
    return [System.IO.Path]::GetFullPath($pn)
  }
  # If the path starts with a separator, treat it as relative to repo root (trim it)
  if ($pn.StartsWith('\')) {
    $pn = $pn.TrimStart('\')
  }
  $repoRoot = Get-RepoRoot
  $combined = Join-Path -Path $repoRoot -ChildPath $pn
  return [System.IO.Path]::GetFullPath($combined)
}

function Ensure-InPath([string[]]$dirs) {
  foreach ($d in $dirs) {
    if ($null -ne $d -and $d -ne "" -and (Test-Path $d)) {
      if (($env:Path -split ";") -notcontains $d) {
        $env:Path = "$d;$env:Path"
      }
    }
  }
}

function Find-ExeDir([string]$exeName) {
  try {
    $cmd = Get-Command $exeName -ErrorAction Stop
    return (Split-Path -Parent $cmd.Source)
  } catch {
    $dirs = @('C:\Program Files','C:\Program Files (x86)')
    $hit = Get-ChildItem -Path $dirs -Filter $exeName -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty DirectoryName
    return $hit
  }
}

try {
  # Resolve input/output
  $inPath = Resolve-AbsolutePath $Source
  Write-Host "Resolved Input: $inPath"
  if (-not (Test-Path -Path $inPath -PathType Leaf)) {
    throw "Input PDF not found: $inPath"
  }

  if (-not $Output -or $Output.Trim() -eq "") {
    $base = [System.IO.Path]::GetFileNameWithoutExtension($inPath)
    $dir  = [System.IO.Path]::GetDirectoryName($inPath)
    $Output = [System.IO.Path]::Combine($dir, ($base + "-ocr.pdf"))
  } else {
    $Output = Resolve-AbsolutePath $Output
  }

  if ((Test-Path -Path $Output -PathType Leaf) -and -not $Force) {
    throw "Output already exists: $Output (use -Force to overwrite)"
  }
  if ($Force -and (Test-Path -Path $Output -PathType Leaf)) {
    Remove-Item -Path $Output -Force -ErrorAction SilentlyContinue
  }
  # Ensure output directory exists
  $outDir = [System.IO.Path]::GetDirectoryName($Output)
  if (-not (Test-Path $outDir)) {
    New-Item -ItemType Directory -Path $outDir | Out-Null
  }
  Write-Host "Resolved Output: $Output"

  # Locate tools
  $tessDir = Find-ExeDir "tesseract.exe"
  $qpdfDir = Find-ExeDir "qpdf.exe"
  $gsDir   = Find-ExeDir "gswin64c.exe"

  # Install Ghostscript if missing
  if (-not $gsDir) {
    Write-Host "Ghostscript not found. Installing..."
    $installer = Join-Path $PSScriptRoot "Install-Ghostscript.ps1"
    if (-not (Test-Path $installer)) {
      throw "Missing helper script: $installer"
    }
    & powershell -NoProfile -ExecutionPolicy Bypass -File $installer | Tee-Object -Variable gsOut | Out-Host
    $m = ($gsOut | Select-String -Pattern 'GS_PATH=(.+)$' | Select-Object -First 1)
    if ($m) {
      $gsDir = Split-Path -Parent ($m.Matches[0].Groups[1].Value)
    }
  }

  # Put everything on PATH for this session
  Ensure-InPath @($tessDir, $qpdfDir, $gsDir, "C:\Program Files\Tesseract-OCR")

  # Verify commands
  & tesseract --version | Out-Null
  & qpdf --version     | Out-Null
  & gswin64c -v        | Out-Null

  # Verify Python + OCRmyPDF
  & py -V | Out-Null
  try {
    & py -m ocrmypdf --version | Out-Null
  } catch {
    throw "OCRmyPDF not installed. Run: py -m pip install --upgrade pip; py -m pip install ocrmypdf"
  }

  $args = @(
    "-m", "ocrmypdf",
    "--skip-text",
    "--language", $Lang,
    "--optimize", $Optimize.ToString()
  )

  $sidecarPath = $null
  if ($Sidecar) {
    $sidecarPath = [System.IO.Path]::ChangeExtension($Output, '.txt')
    $args += @("--sidecar", $sidecarPath)
  }

  $args += @($inPath, $Output)

  Write-Host "Running: py $($args -join ' ')"
  $p = Start-Process -FilePath "py" -ArgumentList $args -Wait -PassThru -NoNewWindow
  if ($p.ExitCode -ne 0) {
    throw "ocrmypdf failed with exit code $($p.ExitCode)"
  }

  if (-not (Test-Path $Output)) {
    throw "OCR completed but output file not found: $Output"
  }

  Write-Output "OK: $Output"
  if ($Sidecar -and $sidecarPath -and (Test-Path $sidecarPath)) {
    Write-Output "Sidecar: $sidecarPath"
  }
  exit 0
}
catch {
  Write-Error $_
  exit 1
}
