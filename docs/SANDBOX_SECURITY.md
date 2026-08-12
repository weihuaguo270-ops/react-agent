# Sandbox 安全部署

## 安全目标

harness/sandbox.py 提供两个后端：

| 后端 | 用途 | 安全边界 |
|------|------|----------|
| process | 本地开发、崩溃和超时隔离 | 无；继承宿主用户权限 |
| container | 执行不可信工具参数和 Python 代码 | 容器运行时提供的 OS 隔离 |

生产模式必须同时配置：

~~~powershell
docker build -f Dockerfile.sandbox -t react-agent-sandbox:0.7.0 .  # 或 podman build

$env:REACT_AGENT_SANDBOX_STRATEGY = "on"
$env:REACT_AGENT_SANDBOX_BACKEND = "container"
$env:REACT_AGENT_SANDBOX_REQUIRED = "1"
$env:REACT_AGENT_SANDBOX_RUNTIME = "podman"  # Docker 环境改为 docker
$env:REACT_AGENT_SANDBOX_IMAGE = "react-agent-sandbox:0.7.0"
~~~

required=1 是失败关闭开关：策略不是 on、后端不是 container、运行时缺失或
镜像不存在时，服务会拒绝启动，不会回退到宿主进程执行。

## 容器约束

每次工具调用创建一个短生命周期容器，并应用：

- UID/GID 65532:65532，禁止 root。
- 只读根文件系统，仅 /tmp 为 noexec,nosuid,nodev tmpfs。
- 丢弃全部 Linux capabilities，并设置 no-new-privileges。
- Docker/Podman 默认 seccomp 配置。
- 默认关闭网络。
- CPU、内存、PID、文件描述符和输出大小限制。
- 工具参数经 stdin 传递，不进入进程命令行。
- 每次只允许调用一个指定工具，Runner 拒绝白名单外工具。
- 不传递 API Key、.env 或宿主完整环境。
- 超时后强制删除命名容器。

默认资源配置：

| 环境变量 | 默认值 |
|----------|--------|
| REACT_AGENT_SANDBOX_MEMORY | 256m |
| REACT_AGENT_SANDBOX_CPUS | 0.5 |
| REACT_AGENT_SANDBOX_PIDS | 64 |
| REACT_AGENT_SANDBOX_TMPFS | 64m |
| REACT_AGENT_SANDBOX_MAX_OUTPUT | 65536 |
| REACT_AGENT_SANDBOX_MAX_INPUT | 1048576 |

## 网络与 MCP

网络默认关闭。web_search、fetch_page 只有在配置
REACT_AGENT_SANDBOX_EGRESS_NETWORK 后才加入指定容器网络。该网络应只连接
认证的 egress proxy；不要直接使用 Docker 默认 bridge 作为生产出站策略。

严格容器模式禁止 MCP Client 在宿主进程直连。生产部署需要把 MCP Server
放入独立容器或隔离 Worker，并通过受控 Broker 接入；在完成该接入前调用会
返回 blocked by sandbox boundary。

## 部署要求

1. 使用 rootless Docker/Podman 或独立 Sandbox Worker，不把 Docker Socket
   挂载进面向用户的 API 容器。
2. 基础镜像在发布流水线中固定 digest，并进行漏洞扫描、SBOM 和签名校验。
3. Linux 生产节点验证默认 seccomp 已启用；更高风险场景使用 gVisor、Kata
   Containers 或 microVM。
4. egress proxy 执行域名/IP 白名单、DNS 重绑定防护、请求和响应大小限制。
5. 采集容器启动、拒绝、超时、OOM、退出码和策略版本，但不记录完整工具参数。
6. 保持 REACT_AGENT_PERMISSION_GATE=1；required=1 会自动启用无 HITL
   严格确认。

## 验证

不依赖容器运行时的策略测试：

~~~powershell
python -m pytest tests/test_sandbox_security.py -q
~~~

真实容器验证要求主机先安装 Docker/Podman 并构建镜像。当前代码会通过
image inspect 检查镜像，检查失败时拒绝运行。仓库测试不会把模拟命令构造
结果冒充为真实容器隔离证明。

### 本机实测记录（2026-08-12）

验证环境为 Windows WSL2、Podman 5.8.3 rootless、cgroup v2 和 crun；Podman
报告 seccomp 已启用。镜像 `react-agent-sandbox:0.7.0` 构建成功，本次镜像 ID
为 `897cd67f8450`。

| 检查项 | 实测结果 |
|--------|----------|
| 工具调用 | `calculator` 通过 stdin 在容器内返回 `5` |
| 身份与提权 | UID/GID 为 `65532:65532`，`CapEff=0`，`NoNewPrivs=1` |
| syscall 过滤 | `/proc/self/status` 显示 `Seccomp=2` |
| 文件系统 | 写 `/etc` 返回 `Errno 30`；`/tmp` 可写，执行文件返回 `Errno 13` |
| 环境变量 | 宿主 `DEEPSEEK_API_KEY` 在容器内为 `None` |
| 网络 | 默认 `network=none`，网络工具连接被拒绝 |
| 资源 | memory=256 MiB、pids=64、cpu.max=`50000 100000`、nofile=64 |
| 生命周期 | 1 秒超时后强制清理，未发现 `react-agent-sbx-*` 遗留容器 |

安全回归为 `15 passed`，全量回归为 `180 passed, 3 skipped`。这些结果证明本机
Podman 路径上的约束实际生效，不替代生产节点逃逸测试、镜像供应链审计和多租户
隔离评审。

## 边界

容器后端是生产安全基线，不等于完成企业安全认证。Docker daemon、宿主内核、
镜像供应链和 egress proxy 都属于可信计算基。多租户高风险代码应采用独立节点
和 microVM，并由安全团队完成逃逸测试、压力测试和应急预案评审。
