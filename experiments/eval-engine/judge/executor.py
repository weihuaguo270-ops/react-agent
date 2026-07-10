"""executor — Judge LLM 调用封装

Judge Executor 是 eval-engine 与 LLM 之间的桥梁。
所有评分最终都通过这里调用 Judge 模型。

关键设计：
  1. Judge 使用独立的 provider / model（通过 JUDGE_PROVIDER 环境变量或配置文件指定）
     建议使用比 Agent 更强或性价比更合适的模型做评分。
  2. 输出强制解析为 JSON，LLM 返回非 JSON 时有兜底
  3. 低 temperature（默认 0.1）保证评分一致性和可复现
  4. 复用已有 src/handwritten_react_agent/llm.py 的 infra，不重复造轮子

Judge 的 Provider 配置规则（优先级从高到低）：
  1. JUDGE_PROVIDER 环境变量（如 "deepseek"、"openai"）
  2. JUDGE_MODEL 环境变量 + JUDGE_BASE_URL + JUDGE_API_KEY（完全自定义）
  3. 回退到 Agent 的 LLM provider（复用 llm_config.json）
"""

from __future__ import annotations
import json
import os
import re
import sys
import time
from typing import Any, Optional, Callable
from urllib import request as req
from urllib.error import URLError


# ──────────────────────────────────────────────
# 默认 Judge System Prompt
# ──────────────────────────────────────────────

DEFAULT_JUDGE_SYSTEM_PROMPT = """你是一个严格但公正的 Agent 执行质量评估器。

你的任务：
1. 仔细阅读评分标准和上下文
2. 严格按照标准评分（不要宽松给分）
3. 始终输出纯 JSON 格式，不要附加任何其他文本

评分原则：
- 5 分 = 完美，没有任何问题
- 4 分 = 好，有细微可优化的点
- 3 分 = 及格，有明显不足但不致命
- 2 分 = 差，关键环节出错
- 1 分 = 完全失败，需要彻底重做

注意：编造信息（幻觉）直接给 1-2 分。"""


# ──────────────────────────────────────────────
# JSON 解析（带容错）
# ──────────────────────────────────────────────


def _extract_json(text: str) -> dict[str, Any]:
    """从 LLM 输出中提取 JSON

    LLM 有时会在 JSON 前后加说明文字，需要容错解析。
    支持以下格式：
      1. 纯 JSON：{"score": 4, ...}
      2. 被 ```json ... ``` 包裹
      3. JSON 前有/后有说明文字
      4. 输出包裹在 ``` 代码块中

    参数:
        text: LLM 原始输出文本

    返回:
        解析后的 JSON 字典

    异常:
        ValueError: 无法提取有效 JSON
    """
    text = text.strip()

    # 尝试 1: 直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 尝试 2: 提取 ```json ... ``` 块
    json_block = re.search(
        r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL
    )
    if json_block:
        try:
            return json.loads(json_block.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 尝试 3: 提取最外层的 { ... }（包括嵌套）
    brace_depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if start == -1:
                start = i
            brace_depth += 1
        elif ch == "}":
            brace_depth -= 1
            if brace_depth == 0 and start != -1:
                try:
                    return json.loads(text[start: i + 1])
                except json.JSONDecodeError:
                    start = -1  # 不是完整 JSON，继续找

    # 尝试 4: 找单个数字作为 score（最坏情况的兜底）
    score_match = re.search(r"score['\"]?\s*:\s*([0-9.]+)", text, re.IGNORECASE)
    if score_match:
        return {"score": float(score_match.group(1)), "_parse_warning": "部分解析"}

    raise ValueError(f"无法从 LLM 输出中提取 JSON:\n{text[:300]}")


# ──────────────────────────────────────────────
# Judge Executor
# ──────────────────────────────────────────────


class JudgeExecutor:
    """Judge LLM 执行器

    用法：
        judge = JudgeExecutor(provider="deepseek", model="deepseek-chat")
        result = judge("你的评分 prompt...")
        # → {"score": 4.5, "rubrics": [...], ...}

    也可以作为回调函数使用：
        scorer = ProcessRewardScorer(judge_fn=judge)
    """

    def __init__(
        self,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 1024,
        max_retries: int = 2,
        llm_config_path: Optional[str] = None,
    ):
        """初始化 Judge 执行器

        参数:
            provider:   Judge 使用的 LLM provider。
                       默认优先从 JUDGE_PROVIDER 环境变量读取，
                       没有则回退到 Agent 的 provider（通过 llm_config.json 的 default）。
            model:      强制指定模型名（覆盖 provider 配置中的 model）
            system_prompt: Judge 系统 prompt（默认使用严格评分风格的 prompt）
            temperature: Judge 温度参数（低温度 = 高一致性，默认 0.1）
            max_tokens:  每次评分的最大 token 数（默认 1024，足够输出评分 JSON）
            max_retries: LLM 调用失败时的重试次数
            llm_config_path: llm_config.json 的路径（默认自动查找）
        """
        self.provider_name = provider or os.environ.get("JUDGE_PROVIDER", "")
        self.model_override = model or os.environ.get("JUDGE_MODEL", "")
        self.system_prompt = system_prompt or DEFAULT_JUDGE_SYSTEM_PROMPT
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.max_retries = max_retries
        self.llm_config_path = llm_config_path

        # 内部状态
        self._base_url: str = ""
        self._api_key: str = ""
        self._model: str = ""
        self._stats = {"calls": 0, "errors": 0, "total_latency": 0.0}
        self._resolved = False

    # ── 懒解析配置 ──

    def _resolve(self) -> None:
        """解析 Judge 的 LLM 配置（懒加载）

        优先级：
          1. 环境变量 JUDGE_BASE_URL / JUDGE_API_KEY / JUDGE_MODEL
          2. 构造时传入的 provider
          3. Agent 的 llm_config.json 中的 provider
        """
        if self._resolved:
            return

        # 方法 1: 完全自定义（环境变量驱动）
        env_base = os.environ.get("JUDGE_BASE_URL", "")
        env_key = os.environ.get("JUDGE_API_KEY", "")
        env_model = os.environ.get("JUDGE_MODEL", "")

        if env_base and env_key:
            self._base_url = env_base.rstrip("/")
            self._api_key = env_key
            self._model = env_model or "gpt-4o-mini"
            self._resolved = True
            return

        # 方法 2: 通过 provider 名称从 llm_config.json 获取
        if self.provider_name:
            self._resolve_from_config(self.provider_name)
            self._resolved = True
            return

        # 方法 3: 回退到 Agent 的默认 provider
        try:
            config = self._load_project_config()
            default_provider = config.get("default", "deepseek")
            self._resolve_from_config(default_provider, config)
            self._resolved = True
            return
        except Exception as e:
            print(f"[JudgeExecutor] 无法从配置文件加载 LLM 配置: {e}")

        # 全部失败
        print("[JudgeExecutor] 警告：未配置任何 Judge LLM，请设置 JUDGE_PROVIDER 或 JUDGE_BASE_URL/JUDGE_API_KEY")
        self._resolved = True  # 避免重复打印

    def _resolve_from_config(
        self,
        provider_name: str,
        config: Optional[dict] = None,
    ) -> None:
        """从 llm_config.json 解析 provider 配置"""
        if config is None:
            config = self._load_project_config()

        providers = config.get("providers", {})
        if provider_name not in providers:
            available = ", ".join(providers.keys())
            print(f"[JudgeExecutor] 未知 provider '{provider_name}'，可用: {available}")
            print(f"[JudgeExecutor] 回退到 Agent 调用方式（通过 src/handwritten_react_agent.llm.LLM）")
            self._provider_name_for_fallback = provider_name
            return

        p = providers[provider_name]

        # base_url
        self._base_url = (p.get("base_url", "") or "").rstrip("/")
        base_url_env = p.get("base_url_env", "")
        if base_url_env:
            self._base_url = os.environ.get(base_url_env, self._base_url)

        # api_key
        self._api_key = p.get("api_key", "") or ""
        api_key_env = p.get("api_key_env", "")
        if api_key_env:
            self._api_key = os.environ.get(api_key_env, self._api_key)

        # model
        self._model = self.model_override or p.get("model", "gpt-4o-mini")
        model_env = p.get("model_env", "")
        if model_env:
            self._model = os.environ.get(model_env, self._model)

    def _load_project_config(self) -> dict:
        """加载项目 llm_config.json"""
        if self.llm_config_path:
            path = self.llm_config_path
        else:
            # 向上查找
            candidates = [
                os.path.join(os.path.dirname(__file__), "..", "..", "..", "llm_config.json"),
                os.path.join(os.getcwd(), "llm_config.json"),
            ]
            path = None
            for c in candidates:
                if os.path.exists(c):
                    path = c
                    break

        if not path or not os.path.exists(path):
            raise FileNotFoundError(
                "找不到 llm_config.json。请确保在项目根目录运行，"
                "或通过 JUDGE_BASE_URL/JUDGE_API_KEY 环境变量配置。"
            )

        with open(path, encoding="utf-8") as f:
            return json.load(f)

    # ── 核心调用 ──

    def __call__(self, prompt: str) -> dict[str, Any]:
        """作为回调函数使用（供 ProcessRewardScorer 调用）

        参数:
            prompt: 完整的评分 prompt（由 build_step_judge_prompt 等生成）

        返回:
            解析后的评分 JSON 字典
        """
        self._resolve()

        # 没有可用配置 → 返回兜底评分
        if not self._base_url and not self._api_key:
            return self._fallback_result(prompt)

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": prompt},
        ]

        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }

        url = f"{self._base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
        }
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        body = json.dumps(payload).encode("utf-8")
        r = req.Request(url, data=body, headers=headers, method="POST")

        last_error = ""
        for attempt in range(self.max_retries + 1):
            try:
                start = time.time()
                with req.urlopen(r, timeout=60) as resp:
                    result = json.loads(resp.read().decode("utf-8"))
                latency = time.time() - start

                self._stats["calls"] += 1
                self._stats["total_latency"] += latency

                llm_message = result["choices"][0]["message"]
                content = llm_message.get("content", "")

                # 提取 JSON
                parsed = _extract_json(content)

                # 记录元数据
                parsed["_judge_meta"] = {
                    "model": self._model,
                    "latency": round(latency, 2),
                    "prompt_tokens": result.get("usage", {}).get("prompt_tokens", 0),
                    "completion_tokens": result.get("usage", {}).get("completion_tokens", 0),
                }
                return parsed

            except (URLError, json.JSONDecodeError, ValueError) as e:
                last_error = str(e)
                self._stats["errors"] += 1
                if attempt < self.max_retries:
                    wait = 1.5 ** attempt
                    time.sleep(wait)
                    continue
                break

        self._stats["errors"] += 1
        error_result = self._fallback_result(prompt)
        error_result["_judge_error"] = last_error
        return error_result

    def _fallback_result(self, prompt: str) -> dict[str, Any]:
        """Judge 调用失败时的兜底评分"""
        # 尝试从 prompt 中提取一些信息
        step_type = "unknown"
        for st in ["thought", "action", "observation", "final"]:
            if f"类型: {st}" in prompt:
                step_type = st
                break

        return {
            "role_understanding": f"Judge 调用不可用（兜底评分）",
            "rubrics": [
                {
                    "dimension": "fallback",
                    "criteria": "Judge LLM 未配置或调用失败",
                    "score": 3.0,
                    "reason": "自动跳过评分（Judge 不可用）",
                },
            ],
            "step_score": 3.0,
            "needs_revision": False,
        }

    def batch_judge(self, prompts: list[str]) -> list[dict]:
        """批量评分

        参数:
            prompts: 评分 prompt 列表

        返回:
            list[dict]: 评分结果列表
        """
        return [self(p) for p in prompts]

    # ── 统计信息 ──

    @property
    def stats(self) -> dict[str, Any]:
        """返回调用统计"""
        avg_latency = (
            self._stats["total_latency"] / self._stats["calls"]
            if self._stats["calls"] > 0
            else 0
        )
        return {
            "total_calls": self._stats["calls"],
            "total_errors": self._stats["errors"],
            "avg_latency": round(avg_latency, 2),
            "model": self._model,
            "provider": self.provider_name or "(环境变量)",
        }

    def __repr__(self) -> str:
        return f"JudgeExecutor(model={self._model or '(未解析)'}, temperature={self.temperature})"
