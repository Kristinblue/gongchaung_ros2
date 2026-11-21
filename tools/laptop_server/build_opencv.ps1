param([Parameter(Mandatory)][string]$BuildDir)

$ErrorActionPreference = 'Stop'
$prefix = Join-Path $BuildDir 'opencv-install'
$ready = Join-Path $prefix '.core-imgproc-built'
if (Test-Path $ready) { return }
New-Item -ItemType Directory -Force -Path $BuildDir | Out-Null
$archive = Join-Path ([IO.Path]::GetTempPath()) 'gc-opencv-4.5.4.tar.gz'
$hash = 'C20BB83DD790FC69DF9F105477E24267706715A9D3C705CA1E7F613C7B3BAD3D'
if (!(Test-Path -LiteralPath $archive) -or (Get-FileHash -LiteralPath $archive).Hash -ne $hash) {
  curl.exe --fail --location --retry 2 --output $archive https://codeload.github.com/opencv/opencv/tar.gz/refs/tags/4.5.4
  if ($LASTEXITCODE -or (Get-FileHash -LiteralPath $archive).Hash -ne $hash) { throw 'OpenCV archive verification failed' }
}
$source = Join-Path $BuildDir 'opencv-4.5.4'
if (!(Test-Path (Join-Path $source 'CMakeLists.txt'))) {
  tar.exe -xzf $archive -C $BuildDir
  if ($LASTEXITCODE) { throw 'OpenCV extraction failed' }
}
$opencvBuild = Join-Path $BuildDir 'opencv'
$options = @(
  '-DBUILD_LIST=core,imgproc', '-DBUILD_SHARED_LIBS=OFF', '-DBUILD_TESTS=OFF',
  '-DBUILD_PERF_TESTS=OFF', '-DBUILD_EXAMPLES=OFF', '-DBUILD_opencv_apps=OFF',
  '-DBUILD_JAVA=OFF', '-DWITH_ITT=OFF', '-DWITH_IPP=OFF', '-DWITH_OPENCL=OFF',
  '-DWITH_1394=OFF', '-DWITH_FFMPEG=OFF', '-DWITH_MSMF=OFF', '-DWITH_PTHREADS_PF=OFF',
  '-DWITH_ADE=OFF', '-DWITH_VTK=OFF', '-DWITH_PROTOBUF=OFF', '-DWITH_QUIRC=OFF',
  '-DWITH_JPEG=OFF', '-DWITH_PNG=OFF', '-DWITH_TIFF=OFF', '-DWITH_WEBP=OFF',
  '-DWITH_OPENJPEG=OFF', '-DWITH_JASPER=OFF', '-DWITH_OPENEXR=OFF'
)
cmake -S $source -B $opencvBuild -G 'MinGW Makefiles' "-DCMAKE_INSTALL_PREFIX=$prefix" -DCMAKE_BUILD_TYPE=Release @options
if ($LASTEXITCODE) { throw 'OpenCV configuration failed' }
cmake --build $opencvBuild --parallel 4
if ($LASTEXITCODE) { throw 'OpenCV build failed' }
cmake --install $opencvBuild
if ($LASTEXITCODE) { throw 'OpenCV installation failed' }
New-Item -ItemType File -Force -Path $ready | Out-Null
