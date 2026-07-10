"""hagent — handwritten-react-agent CLI

专业终端界面（基于 rich），类似 Claude Code / Codex 的交互体验。

用法：
    python hagent_cli.py            # 交互模式
    python hagent_cli.py run "..."  # 单次执行
    python hagent_cli.py eval "..." # 评测
"""
from __future__ import annotations
import os
import sys
import json
import importlib

# ── 路径 ──
_base = os.path.dirname(os.path.abspath(__file__))
for p in [_base, os.path.join(_base, "src"),
          os.path.join(_base, "experiments", "eval-engine")]:
    if p not in sys.path:
        sys.path.insert(0, p)

# ── rich 终端 ──
from rich.console import Console, Group
from rich.panel import Panel
from rich.markdown import Markdown
from rich.table import Table
from rich.prompt import Prompt
from rich.syntax import Syntax
from rich.layout import Layout
from rich.live import Live
from rich.text import Text
from rich import box
import typer

_console = Console()
_L = lambda: _console.print()  # 空行


def _import(mod: str, name: str):
    return getattr(importlib.import_module(mod), name)


# ══════════════════════════════════════════════
#  应用
# ══════════════════════════════════════════════

app = typer.Typer(name="hagent", help="handwritten-react-agent", no_args_is_help=True)


# ══════════════════════════════════════════════
#  shell — 交互模式
# ══════════════════════════════════════════════

@app.command()
def shell(
    provider: str = typer.Option("", "--provider", "-p"),
):
    """交互模式 — 类似 Claude Code 的终端对话体验"""
    if provider:
        os.environ["LLM_PROVIDER"] = provider

    _print_banner()
    _L()
    _console.print(Panel(
        f"  Provider: [bold]{os.environ.get('LLM_PROVIDER', 'default')}[/]"
        f"  |  输入 [bold]/help[/] 查看命令  |  输入 [bold]/exit[/] 退出",
        border_style="blue", title="hagent",
    ))
    _L()

    while True:
        try:
            query = Prompt.ask("[bold cyan]你觉得呢[/]")
        except (EOFError, KeyboardInterrupt):
            _console.print("\n👋 再见")
            break

        query = query.strip()
        if not query:
            continue
        if query.startswith("/"):
            _handle_slash(query)
            continue

        _execute_and_display(query)


def _handle_slash(cmd: str):
    """处理 / 命令"""
    parts = cmd.split()
    c = parts[0].lower()

    if c in ("/exit", "/quit", "/bye"):
        _console.print("👋 再见")
        raise SystemExit(0)
    elif c == "/help":
        _print_help()
    elif c == "/clear":
        os.system("cls" if os.name == "nt" else "clear")
    elif c == "/config":
        _cmd_config()
    else:
        _console.print(f"[red]未知命令: {c}[/] 输入 /help 查看可用命令")


def _print_banner():
    """打印启动 banner"""
    banner = """\
╔═══════════════════════════════════════╗
║  🤖 hagent - handwritten-react-agent ║
║  手写 LLM Agent · 权限控制 · Eval    ║
╚═══════════════════════════════════════╝"""
    _console.print(Panel(banner, border_style="bright_blue", box=box.HEAVY))


def _print_help():
    """打印帮助"""
    table = Table(box=box.SIMPLE, title="命令")
    table.add_column("命令", style="bold cyan")
    table.add_column("说明")
    table.add_row("/exit", "退出")
    table.add_row("/clear", "清屏")
    table.add_row("/config", "查看配置")
    table.add_row("/help", "显示此帮助")
    table.add_row("", "")
    table.add_row("[dim]直接输入问题开始对话[/]", "")
    _console.print(table)


def _execute_and_display(query: str):
    """执行查询并展示输出"""
    # 意图
    try:
        Classifier = _import("intent.classifier", "IntentClassifier")
        task_type = Classifier().classify(query)
    except Exception:
        task_type = "unknown"

    _console.print(Panel(
        f"[bold]{query}[/]\n\n[dim]{task_type}[/]",
        border_style="cyan", title="用户", box=box.SIMPLE,
    ))

    # 权限
    HITL = _import("core.human_in_the_loop", "HumanInTheLoop")
    PW = _import("integration.agent_wrapper", "PermissionWrapper")
    hitl = HITL(ask_fn=_hitl_ask)
    perm = PW(hitl=hitl)
    from src.handwritten_react_agent.react_loop import execute_tool_call as orig
    from src.handwritten_react_agent import react_loop as rl_mod
    rl_mod.execute_tool_call = perm.wrap(orig)

    # 执行
    with _console.status("[bold green]Agent 思考中...", spinner="dots"):
        try:
            result = rl_mod.react_loop(query, max_steps=10)
        except Exception as e:
            _console.print(f"[red]执行异常: {e}[/]")
            return

    # 输出
    if result:
        md = Markdown(result[:1000])
        _console.print(Panel(md, border_style="green", title="输出", box=box.SIMPLE))

    # 复盘
    report = perm.watch.summary()
    if report.has_issues or report.switch_count:
        _console.print(Panel(report.to_text(), border_style="yellow", title="复盘"))
        if hitl.check_direction("重试失败路径", details=report.one_liner):
            _execute_and_display(query)


def _hitl_ask(msg: str, choices: list[str]) -> str:
    """HITL 交互 — 终端弹窗式选择"""
    panel = Panel(msg, border_style="bold yellow", title="🔐 确认")
    _console.print(panel)
    return Prompt.ask("[yellow]选择[/]", choices=choices)


# ══════════════════════════════════════════════
#  run — 单次执行
# ══════════════════════════════════════════════

@app.command()
def run(
    query: str = typer.Argument(..., help="用户输入"),
    provider: str = typer.Option("", "--provider", "-p"),
    no_confirm: bool = typer.Option(False, "-y", help="跳过高风险确认"),
):
    """单次执行 Agent"""
    if provider:
        os.environ["LLM_PROVIDER"] = provider
    _execute_and_display(query)


# ══════════════════════════════════════════════
#  eval — 评测
# ══════════════════════════════════════════════

@app.command()
def eval_response(
    response: str = typer.Argument(..., help="回答"),
    context: str = typer.Option("", "--context", "-c"),
    json_output: bool = typer.Option(False, "--json", "-j"),
):
    """评测 LLM 回答"""
    report_mod = _import("report", "run_eval")
    fmt = _import("report", "format_text")

    report = report_mod(response=response, context=context)

    if json_output:
        fmt_json = _import("report", "format_json")
        _console.print(fmt_json(report))
    else:
        _console.print(Panel(fmt(report), border_style="green", title="评测报告"))


# ══════════════════════════════════════════════
#  config — 配置
# ══════════════════════════════════════════════

@app.command()
def config():
    """查看当前配置"""
    _cmd_config()


def _cmd_config():
    """展示配置"""
    from src.handwritten_react_agent.llm import list_providers

    table = Table(box=box.SIMPLE)
    table.add_column("配置项", style="bold")
    table.add_column("值")

    table.add_row("Provider", f"[cyan]{os.environ.get('LLM_PROVIDER', 'default')}[/]")
    table.add_row("可用", ", ".join(list_providers()))

    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if key:
        table.add_row("API Key", f"✅ 已配置 ({len(key)} 字符)")
    else:
        table.add_row("API Key", "❌ 未配置")

    perm = _import("core.permissions", "TOOL_PERMISSIONS")
    arg = _import("core.permissions", "ARG_RULES")
    levels = {}
    for _, v in perm.items():
        levels[v.value] = levels.get(v.value, 0) + 1
    table.add_row("工具权限", str(levels))
    table.add_row("参数级规则", f"{len(arg)} 条")

    _console.print(Panel(table, border_style="cyan", title="配置"))


# ══════════════════════════════════════════════
#  入口
# ══════════════════════════════════════════════

if __name__ == "__main__":
    if len(sys.argv) == 1:
        shell()
    else:
        app()
