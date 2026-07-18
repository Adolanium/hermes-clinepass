# Install hermes-clinepass into the local Hermes plugins directory.
$ErrorActionPreference = "Stop"

$HermesHome = if ($env:HERMES_HOME) { $env:HERMES_HOME } else { Join-Path $env:LOCALAPPDATA "hermes" }
$Dest = Join-Path $HermesHome "plugins\model-providers\clinepass"
$RepoUrl = if ($env:HERMES_CLINEPASS_URL) { $env:HERMES_CLINEPASS_URL } else { "https://github.com/Adolanium/hermes-clinepass.git" }
$Tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("hermes-clinepass-" + [guid]::NewGuid().ToString("n"))

try {
    Write-Host "Installing ClinePass plugin -> $Dest"
    git clone --depth 1 $RepoUrl $Tmp
    $parent = Split-Path $Dest -Parent
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    if (Test-Path $Dest) { Remove-Item -Recurse -Force $Dest }
    Copy-Item -Recurse -Force (Join-Path $Tmp "clinepass") $Dest

    Write-Host ""
    Write-Host "Done."
    Write-Host ""
    Write-Host "Next:"
    Write-Host "  1. Add CLINE_API_KEY to $HermesHome\.env"
    Write-Host "  2. hermes chat -q `"hi`" --provider clinepass -m cline-pass/kimi-k3"
    Write-Host ""
}
finally {
    if (Test-Path $Tmp) { Remove-Item -Recurse -Force $Tmp -ErrorAction SilentlyContinue }
}
