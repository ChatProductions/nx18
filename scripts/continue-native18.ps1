# One-command local continuation of an iPhone NX18 ExeFS export on Windows 11.
# No Apple Developer software, iOS JIT or public upload of game content.
param(
    [Parameter(Mandatory = $true)][string]$ExeFS,
    [string]$Output = "work\native-from-phone",
    [string]$TitleId = "",
    [switch]$VerifyOnly,
    [switch]$SkipSetup
)
$ErrorActionPreference = "Stop"
Set-Location (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$source = (Resolve-Path -LiteralPath $ExeFS).Path
$vendor = Join-Path (Get-Location) "vendor\nxnative"
if (-not $VerifyOnly -and -not $SkipSetup) {
    if (-not (Test-Path (Join-Path $vendor "dm\tools\guest_dylib.py"))) {
        & "$PSScriptRoot\setup-windows.ps1"
        if ($LASTEXITCODE -ne 0) { throw "nxnative setup failed" }
    }
}
$arguments = @("tools/continue_native18.py", $source, "--upstream", $vendor,
               "--output", $Output)
if ($TitleId) { $arguments += @("--title-id", $TitleId) }
if ($VerifyOnly) { $arguments += "--verify-only" }
& python @arguments
if ($LASTEXITCODE -ne 0) { throw "NX18 native continuation failed" }
if ($VerifyOnly) {
    Write-Host "NX18 ExeFS checksum and NSO verification passed; no conversion ran."
    return
}
Write-Host "NX18 native continuation finished. See $Output\pipeline-report.json for the actual stage."
Write-Host "Guest.framework is native ARM64 code, NOT a playable or signed IPA."
