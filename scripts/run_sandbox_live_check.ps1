[CmdletBinding()]
param(
    [string]$Image = "react-agent-sandbox:0.7.0",
    [string]$OutputPath = "docs/snapshots/sandbox_live_check_latest.json",
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "项目虚拟环境不存在: $Python"
}
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "找不到 Docker CLI"
}

Push-Location $ProjectRoot
try {
    & docker info 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "无法连接 Docker daemon。请启动 Docker Desktop，并确认当前用户有 Docker pipe 访问权限。"
    }

    & docker image inspect $Image 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        if ($SkipBuild) {
            throw "Sandbox 镜像不存在且指定了 -SkipBuild: $Image"
        }
        Write-Host "[sandbox] 构建镜像: $Image"
        & docker build -f Dockerfile.sandbox -t $Image . | Out-Host
        if ($LASTEXITCODE -ne 0) {
            throw "Sandbox 镜像构建失败: $Image"
        }
    }

    $env:REACT_AGENT_SANDBOX_STRATEGY = "on"
    $env:REACT_AGENT_SANDBOX_BACKEND = "container"
    $env:REACT_AGENT_SANDBOX_REQUIRED = "1"
    $env:REACT_AGENT_SANDBOX_RUNTIME = "docker"
    $env:REACT_AGENT_SANDBOX_IMAGE = $Image

    & $Python examples/eval/run_sandbox_live_check.py --out $OutputPath
    if ($LASTEXITCODE -ne 0) {
        throw "Sandbox live check 失败。"
    }

    Write-Host "[sandbox] 验证完成: $OutputPath"
}
finally {
    Pop-Location
}
