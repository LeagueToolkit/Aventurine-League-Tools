@echo off
REM Build script for ritoddstex DLL
REM Requires Visual Studio 2022 Build Tools

REM Find and setup VS environment
set "VSCMD_START_DIR=%CD%"

REM Try VS 2022 Community
if exist "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" (
    call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"
    goto :build
)

REM Try VS 2022 Professional
if exist "C:\Program Files\Microsoft Visual Studio\2022\Professional\VC\Auxiliary\Build\vcvars64.bat" (
    call "C:\Program Files\Microsoft Visual Studio\2022\Professional\VC\Auxiliary\Build\vcvars64.bat"
    goto :build
)

REM Try VS 2022 Enterprise
if exist "C:\Program Files\Microsoft Visual Studio\2022\Enterprise\VC\Auxiliary\Build\vcvars64.bat" (
    call "C:\Program Files\Microsoft Visual Studio\2022\Enterprise\VC\Auxiliary\Build\vcvars64.bat"
    goto :build
)

REM Try VS 2022 BuildTools
if exist "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" (
    call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
    goto :build
)

echo ERROR: Could not find Visual Studio 2022 installation
exit /b 1

:build
echo Building ritoddstex.dll (64-bit)...

cl /nologo /O2 /W3 /DBUILD_DLL /LD ritoddstex_dll.c /Fe:ritoddstex.dll /link /DLL

if %ERRORLEVEL% EQU 0 (
    echo.
    echo Build successful! Created ritoddstex.dll

    REM Clean up intermediate files
    del /q *.obj *.exp *.lib 2>nul
) else (
    echo.
    echo Build FAILED!
    exit /b 1
)
