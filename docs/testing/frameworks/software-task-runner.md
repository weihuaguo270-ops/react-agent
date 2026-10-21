# 软件任务隔离执行

`SoftwareTaskRunner` 是冻结任务 Schema 与 GitHub 交付之间的执行层。默认使用
Docker；它先检出任务的 `base_commit`，再把测试命令放进一次性 Docker 容器执行。

## 执行边界

容器默认使用 `--network none`、只读根文件系统、非 root 用户、丢弃全部
Linux capabilities、`no-new-privileges`、进程数/内存/CPU 上限，并只挂载一个
可写的 `/workspace`。测试命令必须匹配 `python -m pytest`、`python3 -m pytest`
或 `pytest` 前缀；例如任意 PowerShell 删除命令会在启动容器前被拒绝。

`golden` 和 `held_out` 任务还必须声明 `hidden_test_asset`。它是隐藏测试根目录
下的相对路径，资产不会复制进 Agent 工作区；Runner 只在执行
`hidden_test_command` 时将它以只读方式挂载到 `/hidden-tests/<文件名>`。公开测试不会看到
该挂载，绝对路径、`..` 路径、缺失资产或未配置 `hidden_test_root` 都会失败关闭。

任务结果包含任务哈希、退出码、耗时、截断后的 stdout/stderr、修改文件、
越权修改文件和容器配置，可直接交给后续 Episode 或发布门禁。

## 当前边界

该执行器当前运行任务声明的测试，不负责让 Agent 在容器内完成代码修改；代码
修改仍由现有 GitHub delivery workflow 完成。容器镜像必须预装项目测试所需依赖，
因为默认断网，不能在测试时从公网安装依赖。Docker daemon、可执行文件和镜像必须
由部署环境提供；运行前会执行 `docker info` 和 `docker image inspect`。未验证时
不会把容器结果写成生产容量或安全认证。
