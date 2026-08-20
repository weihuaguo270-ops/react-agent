[CmdletBinding()]
param(
    [string]$Runtime = "podman",
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
if (-not (Get-Command $Runtime -ErrorAction SilentlyContinue)) {
    throw "找不到容器运行时: $Runtime"
}

Push-Location $ProjectRoot
try {
    if ($Runtime -eq "podman") {
        $InspectOutput = @(& podman machine inspect 2>&1)
        if ($LASTEXITCODE -ne 0) {
            $detail = ($InspectOutput -join " ").Trim()
            throw "无法读取 Podman machine 状态。请在当前用户 PowerShell 检查 Podman 权限和连接。详情: $detail"
        }
        try {
            $Machine = $InspectOutput -join [Environment]::NewLine | ConvertFrom-Json
        }
        catch {
            throw "Podman machine inspect 返回了无法解析的结果: $($_.Exception.Message)"
        }
        if (-not $Machine -or $Machine.Count -eq 0) {
            throw "未发现 Podman machine；请先在当前用户会话初始化 Podman。"
        }
        if ($Machine[0].State -ne "running") {
            Write-Host "[sandbox] 启动 Podman machine: $($Machine[0].Name)"
            & podman machine start | Out-Host
        }
    }

    & $Runtime image inspect $Image 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        if ($SkipBuild) {
            throw "Sandbox 镜像不存在且指定了 -SkipBuild: $Image"
        }
        Write-Host "[sandbox] 构建镜像: $Image"
        & $Runtime build -f Dockerfile.sandbox -t $Image . | Out-Host
        if ($LASTEXITCODE -ne 0) {
            throw "Sandbox 镜像构建失败: $Image"
        }
    }

    $env:REACT_AGENT_SANDBOX_STRATEGY = "on"
    $env:REACT_AGENT_SANDBOX_BACKEND = "container"
    $env:REACT_AGENT_SANDBOX_REQUIRED = "1"
    $env:REACT_AGENT_SANDBOX_RUNTIME = $Runtime
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
