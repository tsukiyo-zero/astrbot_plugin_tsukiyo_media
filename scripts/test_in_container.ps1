# 把当前插件源码同步进容器并跑单测（本机没装 Python，用容器里的）
# 用法：powershell -ExecutionPolicy Bypass -File scripts\test_in_container.ps1

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$container = "xiaofeiyu-astrbot-1"
$dest = "/tmp/t/astrbot_plugin_tsukiyo_media"

docker exec $container sh -c "rm -rf $dest" | Out-Null
docker exec $container mkdir -p /tmp/t | Out-Null
docker cp $repo "${container}:/tmp/t/astrbot_plugin_tsukiyo_media" | Out-Null

docker exec $container sh -c "cd $dest && python -m unittest discover -s tests -p 'test_*.py'"
exit $LASTEXITCODE
