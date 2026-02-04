# PowerShell build script for ritoddstex DLL

$ErrorActionPreference = "Stop"

# Find Visual Studio installation
$vsPath = $null
$possiblePaths = @(
    "C:\Program Files\Microsoft Visual Studio\2022\Community",
    "C:\Program Files\Microsoft Visual Studio\2022\Professional",
    "C:\Program Files\Microsoft Visual Studio\2022\Enterprise",
    "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools"
)

foreach ($path in $possiblePaths) {
    $vcvars = Join-Path $path "VC\Auxiliary\Build\vcvars64.bat"
    if (Test-Path $vcvars) {
        $vsPath = $path
        break
    }
}

if (-not $vsPath) {
    Write-Error "Could not find Visual Studio 2022 installation"
    exit 1
}

Write-Host "Found Visual Studio at: $vsPath"
Write-Host "Building ritoddstex.dll (64-bit)..."

# Change to script directory
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $scriptDir

# Build using cmd with vcvars
$vcvars = Join-Path $vsPath "VC\Auxiliary\Build\vcvars64.bat"
$buildCmd = @"
call "$vcvars" && cl /nologo /O2 /W3 /DBUILD_DLL /LD ritoddstex_dll.c /Fe:ritoddstex.dll /link /DLL
"@

cmd /c $buildCmd

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "Build successful! Created ritoddstex.dll" -ForegroundColor Green

    # Clean up intermediate files
    Remove-Item -Force *.obj, *.exp, *.lib -ErrorAction SilentlyContinue
} else {
    Write-Error "Build FAILED!"
    exit 1
}

Pop-Location
