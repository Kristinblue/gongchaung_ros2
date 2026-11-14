param(
  [Parameter(Mandatory)][string]$Qt,
  [Parameter(Mandatory)][string]$MinGW
)
$ErrorActionPreference = 'Stop'
$qtBin = Join-Path (Resolve-Path -LiteralPath $Qt).Path 'bin'
$mingwBin = Join-Path (Resolve-Path -LiteralPath $MinGW).Path 'bin'
$env:Path = "$mingwBin;$qtBin;$env:Path"
$root = $PSScriptRoot
$build = Join-Path $root 'build'
$dist = Join-Path $root 'dist'
cmake -S $root -B $build -G 'MinGW Makefiles' "-DCMAKE_PREFIX_PATH=$Qt" -DCMAKE_BUILD_TYPE=Release
if ($LASTEXITCODE) { exit $LASTEXITCODE }
cmake --build $build --parallel 2
if ($LASTEXITCODE) { exit $LASTEXITCODE }
New-Item -ItemType Directory -Force -Path $dist | Out-Null
Copy-Item -LiteralPath (Join-Path $build 'GongchuangClient.exe') -Destination $dist
& (Join-Path $qtBin 'windeployqt.exe') --release --no-translations (Join-Path $dist 'GongchuangClient.exe')
if ($LASTEXITCODE) { exit $LASTEXITCODE }
Compress-Archive -Path "$dist/*" -DestinationPath "$root/GongchuangClient.zip" -Force
