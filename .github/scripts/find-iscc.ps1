# Locate the Inno Setup compiler and export it as $env:ISCC for build.bat.
#
# WHY THIS EXISTS
#     Inno Setup 6 IS preinstalled on GitHub's windows-latest image (6.7.1 per the
#     runner-image manifest) but the manifest does NOT document its install path,
#     and `build.bat` only *warns* and continues when it cannot find ISCC. Relying
#     on the probe list matching an undocumented path is how you ship a release
#     with no installer in it.
#
#     So: find it here, deliberately and by several means, FAIL LOUDLY if absent,
#     and hand the absolute path to build.bat via %ISCC% (which build.bat honours
#     in preference to its own probing). The release workflow additionally asserts
#     a *-setup.exe actually appeared, so this is belt AND braces.
#
# Usage (GitHub Actions, shell: pwsh):
#     .github/scripts/find-iscc.ps1
# Writes ISCC=<path> to $GITHUB_ENV when running under Actions; always prints it.
#
# Exit 1 if not found, with the install command in the message.

$ErrorActionPreference = 'Stop'

$candidates = New-Object System.Collections.Generic.List[string]

# 1) On PATH already.
$onPath = Get-Command iscc.exe -ErrorAction SilentlyContinue
if ($onPath) { $candidates.Add($onPath.Source) }

# 2) The documented install locations, 64-bit and 32-bit Program Files plus the
#    per-user location `winget install JRSoftware.InnoSetup` uses.
foreach ($base in @($env:ProgramFiles, ${env:ProgramFiles(x86)},
                    "$env:LOCALAPPDATA\Programs")) {
    if ($base) {
        foreach ($v in @('Inno Setup 6', 'Inno Setup 5')) {
            $candidates.Add((Join-Path $base "$v\ISCC.exe"))
        }
    }
}

# 3) The uninstall registry key, which is authoritative wherever it was installed.
foreach ($hive in @(
        'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1',
        'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1',
        'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1')) {
    try {
        $loc = (Get-ItemProperty -Path $hive -ErrorAction Stop).InstallLocation
        if ($loc) { $candidates.Add((Join-Path $loc 'ISCC.exe')) }
    } catch { }
}

# 4) Last resort: a bounded search of the two Program Files roots. Bounded depth so
#    this cannot turn into a whole-drive scan.
foreach ($base in @($env:ProgramFiles, ${env:ProgramFiles(x86)})) {
    if ($base -and (Test-Path $base)) {
        Get-ChildItem -Path $base -Filter 'ISCC.exe' -Depth 2 -File `
            -ErrorAction SilentlyContinue |
            ForEach-Object { $candidates.Add($_.FullName) }
    }
}

$found = $null
foreach ($c in $candidates) {
    if ($c -and (Test-Path -LiteralPath $c -PathType Leaf)) { $found = $c; break }
}

if (-not $found) {
    Write-Host '::error::Inno Setup compiler (ISCC.exe) not found. Searched PATH, Program Files (both), %LOCALAPPDATA%\Programs, the uninstall registry keys, and a depth-2 scan of Program Files. Install it with: winget install JRSoftware.InnoSetup  (or choco install innosetup -y)'
    Write-Host 'Candidates considered:'
    $candidates | Select-Object -Unique | ForEach-Object { Write-Host "  $_" }
    exit 1
}

# Report the version so the log records exactly what built the installer.
# ISCC.exe does not always carry version resources (measured: 0.0.0.0 locally), so
# report "unknown" rather than printing a zero that looks like real information.
$version = $null
try {
    $info = (Get-Item -LiteralPath $found).VersionInfo
    foreach ($v in @($info.ProductVersion, $info.FileVersion)) {
        if ($v -and $v -notmatch '^0(\.0)*$') { $version = $v; break }
    }
} catch { }
if (-not $version) { $version = 'unknown (no version resource)' }
Write-Host "Found ISCC: $found (version $version)"

if ($env:GITHUB_ENV) {
    "ISCC=$found" | Out-File -FilePath $env:GITHUB_ENV -Append -Encoding utf8
    Write-Host 'Exported ISCC to $GITHUB_ENV for the build step.'
}
