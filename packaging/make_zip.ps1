<#
Robustly (re)create the Windows distribution zip. Called by build.bat.

Why not a plain `Compress-Archive`:
  * Compress-Archive intermittently dies with "the process cannot access the
    file ... because it is being used by another process" when antivirus is
    still scanning PyInstaller's freshly written payload (base_library.zip is
    the usual victim). That error is NON-TERMINATING, so the old one-liner
    exited 0 and build.bat happily printed "Built ...zip" with no valid archive.
  * It is also slow on the ~1.4 GB native tree.

This uses a single .NET ZipFile call (faster + clearer failures), RETRIES on the
transient AV lock, and exits non-zero on real failure so build.bat's ERRORLEVEL
check catches it. includeBaseDirectory=$true keeps the top-level CellSmith\
folder inside the zip (extract -> CellSmith\CellSmith.exe), matching the prior
`Compress-Archive -Path dist\CellSmith` behaviour exactly.

If the lock persists across ALL retries, exclude dist\ from real-time antivirus
scanning (or close any running CellSmith.exe) and rebuild.
#>
param(
    [Parameter(Mandatory=$true)][string]$Source,   # e.g. dist\CellSmith
    [Parameter(Mandatory=$true)][string]$Dest,     # e.g. dist\CellSmith-v1-win64.zip
    [int]$Retries = 6,
    [int]$DelaySeconds = 3
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression.FileSystem | Out-Null

# GetFullPath resolves a relative path against the current dir and leaves an
# absolute one unchanged (ZipFile needs full paths).
$srcFull  = [System.IO.Path]::GetFullPath($Source)
$destFull = [System.IO.Path]::GetFullPath($Dest)

if (-not (Test-Path -LiteralPath $srcFull)) {
    Write-Error "make_zip: source not found: $srcFull"
    exit 1
}

for ($i = 1; $i -le $Retries; $i++) {
    try {
        if (Test-Path -LiteralPath $destFull) { Remove-Item -Force -LiteralPath $destFull }
        [System.IO.Compression.ZipFile]::CreateFromDirectory(
            $srcFull, $destFull,
            [System.IO.Compression.CompressionLevel]::Optimal, $true)
        Write-Host "Zipped $Source -> $Dest"
        exit 0
    } catch {
        Write-Warning "zip attempt $i/$Retries failed: $($_.Exception.Message)"
        if ($i -lt $Retries) { Start-Sleep -Seconds $DelaySeconds }
    }
}
Write-Error "make_zip: failed to create $Dest after $Retries attempts (file lock?)."
exit 1
