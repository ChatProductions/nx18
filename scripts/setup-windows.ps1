# Windows setup for the real nxnative NSO rewriter; NO Apple SDK/downloads.
# This clones only source code. Game assets and keys stay on your own computer.
param(
    [string]$Vendor = "vendor\nxnative",
    [switch]$SkipPip
)
$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repo

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python 3.9+ not installed. Install from python.org, not from Apple's Developer site."
}
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git not found. Install Git for Windows: https://git-scm.com/download/win"
}
$branch = "ios16-ios17-compat"
if (-not (Test-Path (Join-Path $Vendor "dm\tools\patch_nso.py"))) {
    if (Test-Path $Vendor) {
        throw "$Vendor already exists but does not contain the nxnative rewriter."
    }
    git clone --depth 1 --branch $branch https://github.com/widmonstertony/nxnative.git $Vendor
    if ($LASTEXITCODE -ne 0) { throw "Git clone failed" }
}
$sha = git -C $Vendor rev-parse HEAD
if ($LASTEXITCODE -ne 0) { throw "Cannot read upstream revision" }
Write-Host "Native legacy renderer/rewrite checkout: $sha"
if (-not $SkipPip) {
    python -m pip install "capstone>=5,<6" "lz4>=4,<5"
    if ($LASTEXITCODE -ne 0) { throw "Python package installation failed" }
}
python -m unittest discover -s tests -p "test_*exefs.py" -v
if ($LASTEXITCODE -ne 0) { throw "Wrapper tests failed" }
Write-Host "Ready. Next: python tools/rewrite_exefs.py EXEFS --upstream $Vendor"
Write-Host "Generated rewritten modules are NOT a playable IPA."
