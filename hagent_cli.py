"""Agent CLI — 统一入口

用法：
    cli run "帮我写一份报告"     # 执行 Agent（权限 + 复盘）
    cli eval "回答内容"          # 评测
    cli config                   # 查看配置
"""
from __future__ import annotations
import os
import sys

import typer

# 路径设置
_base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _base)
sys.path.insert(0, os.path.join(_base, "src"))
sys.path.insert(0, os.path.join(_base, "experiments", "eval-engine"))

# 延迟导入（模块内部使用）
_imported = {}

def _import(module: str, name: str):
    """延迟导入，避免启动时加载全部模块"""
    import importlib
    mod = importlib.import_module(module)
    return getattr(mod, name)


cli_app = typer.Typer(name="cli", help="handwritten-react-agent — 统一入口", no_args_is_help=True)


# ══════════════════════════════════════════════
#  run
# ══════════════════════════════════════════════

@cli_app.command()
def run(
    query: str = typer.Argument(..., help="用户输入"),
    provider: str = typer.Option("", "--provider", "-p", help="LLM Provider"),
    max_steps: int = typer.Option(10, "--max-steps", "-s", help="最大步数"),
    no_confirm: bool = typer.Option(False, "--no-confirm", "-y", help="跳过高风险确认"),
    no_trace: bool = typer.Option(False, "--no-trace", "-T", help="跳过复盘"),
):
    """执行 Agent（带权限 + 复盘）"""
    if provider:
        os.environ["LLM_PROVIDER"] = provider

    typer.echo(f"Provider: {os.environ.get('LLM_PROVIDER', 'default')}")

    # 意图分类
    Classifier = _import("intent.classifier", "IntentClassifier")
    task_type = Classifier().classify(query)
    typer.echo(f"任务类型: {task_type}")

    # 权限包装
    if not no_confirm:
        HITL = _import("core.human_in_the_loop", "HumanInTheLoop")
        PW = _import("integration.agent_wrapper", "PermissionWrapper")
        hitl = HITL(ask_fn=_ask_user)
        perm = PW(hitl=hitl)
        from src.handwritten_react_agent.react_loop import execute_tool_call as orig
        wrapped = perm.wrap(orig)
        import src.handwritten_react_agent.react_loop as rl
        rl.execute_tool_call = wrapped

    # 执行 Agent
    from src.handwritten_react_agent.react_loop import react_loop
    try:
        result = react_loop(query, max_steps=max_steps)
        typer.echo(f"\n最终答案: {result[:200]}")
    except Exception as e:
        typer.echo(f"执行异常: {e}")
        raise typer.Exit(1)

    # 复盘
    if not no_trace and not no_confirm:
        report = perm.watch.summary()
        text = report.to_text()
        if text:
            typer.echo(text)


def _ask_user(msg: str, choices: list[str]) -> str:
    typer.echo(f"\n{msg}")
    try:
        return input("> ").strip()
    except (EOFError, KeyboardInterrupt):
        return choices[-1]


# ══════════════════════════════════════════════
#  eval
# ══════════════════════════════════════════════

@cli_app.command()
def eval_response(
    response: str = typer.Argument(..., help="要评测的回答"),
    context: str = typer.Option("", "--context", "-c", help="参考上下文"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 格式"),
):
    """评测 LLM 回答质量"""
    report_mod = _import("report", "run_eval")
    fmt = _import("report", "format_text")
    fmt_json = _import("report", "format_json")

    report = report_mod(response=response, context=context)
    if json_output:
        typer.echo(fmt_json(report))
    else:
        typer.echo(fmt(report))


# ══════════════════════════════════════════════
#  config
# ══════════════════════════════════════════════

@cli_app.command()
def config():
    """查看当前配置"""
    from src.handwritten_react_agent.llm import list_providers

    typer.echo("配置概览:")
    typer.echo(f"  可用 Provider: {', '.join(list_providers())}")
    typer.echo(f"  当前 Provider: {os.environ.get('LLM_PROVIDER', 'default')}")

    key = os.environ.get("DEEPSEEK_API_KEY", "")
    typer.echo(f"  API Key: {'✅ 已配置' if key else '❌ 未配置'}")

    Perm = _import("core.permissions", "TOOL_PERMISSIONS")
    Arg = _import("core.permissions", "ARG_RULES")
    levels = {}
    for _, v in Perm.items():
        levels[v.value] = levels.get(v.value, 0) + 1
    typer.echo(f"  工具权限规则: {levels}")
    typer.echo(f"  参数级规则: {len(Arg)} 条")


if __name__ == "__main__":
    cli_app()
