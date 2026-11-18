$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# Reproducible build in a project-only Python environment (.venv), so other Python
# projects on this computer are not touched.
#  - First build: creates .venv, installs requirements.txt and PyInstaller, then records
#    the exact versions in requirements-lock.txt.
#  - Later builds: install exactly what requirements-lock.txt lists.
# Keep requirements-lock.txt with the project. Delete it only when you mean to upgrade.

$venv = Join-Path $PSScriptRoot ".venv"
$python = Join-Path $venv "Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "Creating the project environment in .venv"
    py -3 -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw "Could not create .venv." }
}

$lock = Join-Path $PSScriptRoot "requirements-lock.txt"
if (Test-Path $lock) {
    Write-Host "Installing the locked versions from requirements-lock.txt"
    & $python -m pip install --disable-pip-version-check -r $lock
} else {
    Write-Host "No lock file yet. Installing requirements.txt and PyInstaller, then writing requirements-lock.txt"
    & $python -m pip install --disable-pip-version-check -r requirements.txt pyinstaller
    if ($LASTEXITCODE -ne 0) { throw "Package install failed." }
    & $python -m pip freeze | Set-Content -Encoding utf8 $lock
}
if ($LASTEXITCODE -ne 0) { throw "Package install failed." }

$tests = Join-Path $PSScriptRoot "tests"
if (Test-Path $tests) {
    Write-Host "Running tests"
    & $python -m unittest discover -s tests -t .
    if ($LASTEXITCODE -ne 0) { throw "Tests failed. The program was not built." }
} else {
    Write-Host "No tests folder, so tests were skipped."
}

& $python -m PyInstaller --noconfirm CardStripeExaminer.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }

$info = @(
    "Card Stripe Examiner build"
    "Built: $(Get-Date -Format s)"
    "Computer: $env:COMPUTERNAME"
    "Python: $(& $python --version)"
    ""
    "Packages:"
) + (& $python -m pip freeze)
$info | Set-Content -Encoding utf8 "dist\CardStripeExaminer\BUILD-INFO.txt"

Write-Host "Built dist\CardStripeExaminer\CardStripeExaminer.exe (versions in BUILD-INFO.txt)"

# Installer (Inno Setup 6). Skipped with a message if Inno Setup is not installed.
$iscc = @(
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
    (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
    (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $iscc) {
    Write-Host "Inno Setup 6 was not found, so no installer was made. Install it from jrsoftware.org to build one."
    exit 0
}
$version = (& $python -c "import card_stripe_examiner; print(card_stripe_examiner.__version__)").Trim()
& $iscc "/DAppVersion=$version" "installer.iss"
if ($LASTEXITCODE -ne 0) { throw "The installer could not be built." }
Write-Host "Built installer\CardStripeExaminer-Setup-$version.exe"
