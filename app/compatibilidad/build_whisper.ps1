$ErrorActionPreference = 'Stop'
$julioRoot = (Get-Location).Path
$julioBuildTools = Join-Path $julioRoot 'work\tools\build-python'
$julioZig = Join-Path $julioBuildTools 'ziglang\zig.exe'
$julioCmake = Join-Path $julioBuildTools 'cmake\data\bin\cmake.exe'
$julioNinja = Join-Path $julioBuildTools 'bin\ninja.exe'
$env:PYTHONPATH = $julioBuildTools
$env:ZIG_GLOBAL_CACHE_DIR = Join-Path $julioRoot 'work\tools\zig-global-cache'
$env:ZIG_LOCAL_CACHE_DIR = Join-Path $julioRoot 'work\tools\zig-local-cache'
$julioWrappers = Join-Path $julioRoot 'work\tools\compiler-wrappers'
New-Item -ItemType Directory -Force $julioWrappers | Out-Null
Set-Content -LiteralPath (Join-Path $julioWrappers 'cc.cmd') -Value ('@"' + $julioZig + '" cc %*') -Encoding ascii
Set-Content -LiteralPath (Join-Path $julioWrappers 'cxx.cmd') -Value ('@"' + $julioZig + '" c++ %*') -Encoding ascii
Set-Content -LiteralPath (Join-Path $julioWrappers 'ar.cmd') -Value ('@"' + $julioZig + '" ar %*') -Encoding ascii
Set-Content -LiteralPath (Join-Path $julioWrappers 'ranlib.cmd') -Value ('@"' + $julioZig + '" ranlib %*') -Encoding ascii
$julioOptions = @('-S','work/tools/whisper-source/whisper.cpp-1.7.6','-B','work/tools/whisper-generic','-G','Ninja',"-DCMAKE_MAKE_PROGRAM=$julioNinja", "-DCMAKE_C_COMPILER=$(Join-Path $julioWrappers 'cc.cmd')", "-DCMAKE_CXX_COMPILER=$(Join-Path $julioWrappers 'cxx.cmd')", "-DCMAKE_AR=$(Join-Path $julioWrappers 'ar.cmd')", "-DCMAKE_RANLIB=$(Join-Path $julioWrappers 'ranlib.cmd')",'-DCMAKE_BUILD_TYPE=Release','-DCMAKE_C_FLAGS=-mcpu=x86_64 -fno-sanitize=undefined','-DCMAKE_CXX_FLAGS=-mcpu=x86_64 -fno-sanitize=undefined','-DGGML_NATIVE=OFF','-DGGML_AVX=OFF','-DGGML_AVX2=OFF','-DGGML_F16C=OFF','-DGGML_FMA=OFF','-DGGML_BMI2=OFF','-DGGML_AVX512=OFF','-DGGML_SSE42=OFF','-DGGML_CPU_REPACK=OFF','-DGGML_OPENMP=OFF','-DBUILD_SHARED_LIBS=OFF','-DWHISPER_BUILD_TESTS=OFF','-DWHISPER_BUILD_SERVER=OFF')
& $julioCmake @julioOptions
if ($LASTEXITCODE -ne 0) { throw 'No se configuró Whisper genérico.' }
& $julioCmake --build work/tools/whisper-generic --target whisper-cli --parallel 2
if ($LASTEXITCODE -ne 0) { throw 'No se compiló Whisper genérico.' }


