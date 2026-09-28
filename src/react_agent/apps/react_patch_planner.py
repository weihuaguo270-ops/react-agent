"""把 ReAct/LLM 调用封装为 RepairLoop 所需的补丁规划器。"""
from __future__ import annotations

import json
from typing import Any, Callable, Mapping


class ReActPatchPlanner:
    """可注入模型调用，强制将文本结果解析为结构化补丁计划。

    model_call 接收提示词并返回字符串或映射；该适配器不读取隐藏测试资产。
    """

    def __init__(self, model_call: Callable[[str], str | Mapping[str, Any]]) -> None:
        self.model_call = model_call

    def __call__(self, context: Mapping[str, Any]) -> Mapping[str, Any]:
        prompt = {
            "task": context.get("task", context.get("issue", "")),
            "issue": context.get("issue", ""),
            "source": context.get("source", ""),
            "allowed_paths": context.get("allowed_paths", ()),
            "public_feedback": context.get("failure", {}),
            "repair_feedback": context.get("repair_feedback", {}),
            "instruction": "响应必须是一个 JSON 对象，首字符为 {、末字符为 }，禁止 Markdown、代码围栏、解释、推理或额外字段。格式必须是 {\"replacements\":[{\"path\":\"...\",\"old\":\"...\",\"new\":\"...\"}]}。必须同时满足全部验收条件，包含运行时行为和静态类型检查器可见的声明；并发缓存修复必须复用源码已有的重建锁接口，若新增锁则命名为 _rebuild_lock 并让所有相关缓存方法共用它；获取锁后必须再次读取版本并复用已更新缓存，未更新时才构建临时列表；必须先写回 self 的共享缓存字段、再更新版本、最后返回 self 的共享缓存字段，禁止返回局部列表；每个 old/new 只保留完成修复所需的最小唯一连续片段，避免复制整个方法；每轮均从所提供的基线源码重新开始；old 必须唯一且逐字匹配。优先根据 repair_feedback / public_feedback 中的失败信号修复。",
        }
        result = self.model_call(json.dumps(prompt, ensure_ascii=False))
        if isinstance(result, Mapping):
            return result
        if not isinstance(result, str):
            raise TypeError("model_call must return JSON text or mapping")
        result = result.strip()
        if result.startswith("```"):
            result = result.split("\n", 1)[1] if "\n" in result else result
            if result.endswith("```"):
                result = result[:-3].rstrip()
        try:
            parsed = json.loads(result)
        except json.JSONDecodeError:
            parsed = None
            decoder = json.JSONDecoder()
            for index, char in enumerate(result):
                if char != "{":
                    continue
                try:
                    candidate, _ = decoder.raw_decode(result[index:])
                except json.JSONDecodeError:
                    continue
                if isinstance(candidate, Mapping) and "replacements" in candidate:
                    parsed = candidate
                    break
            if parsed is None:
                preview = " ".join(result.split())[:300]
                raise ValueError(f"model output is not valid JSON: {preview}")
        if not isinstance(parsed, Mapping):
            raise ValueError("model output must be a JSON object")
        return parsed


__all__ = ["ReActPatchPlanner", "configured_model_call"]


def configured_model_call(llm: Any) -> Callable[[str], str]:
    if llm.provider_name != "ollama" and not llm.api_key:
        raise RuntimeError("LLM credential is not configured")

    def call(prompt: str) -> str:
        reply = llm.chat([{"role": "user", "content": prompt}], temperature=0, max_tokens=32768,
                         response_format={"type": "json_object"})
        content = reply.get("content")
        if not isinstance(content, str) or not content.strip():
            reasoning = reply.get("reasoning_content")
            if isinstance(reasoning, str) and reasoning.strip():
                content = reasoning
            else:
                fields = ",".join(sorted(str(key) for key in reply.keys()))
                raise RuntimeError(f"LLM response has no text content; fields={fields}")
        if content.startswith(("LLM调用失败", "LLM调用异常", "解析LLM返回失败")):
            raise RuntimeError(content[:500])
        return content
    return call
