"""resilience 模块测试"""
import sys, os, time, threading
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from react_agent.console_io import configure_stdio

# 本文件用 emoji 打印进度；GBK 控制台上直接 print 会抛 UnicodeEncodeError，
# 所以先放开 errors=replace（pytest 捕获输出时无影响）。
configure_stdio()

from react_agent.resilience import (
    classify_error, is_retryable, ErrorCategory,
    retry, CircuitBreaker, guarded_call,
)


def test_classify_auth():
    assert classify_error(Exception("401 Unauthorized")) == ErrorCategory.AUTH
    assert classify_error(Exception("API key is invalid")) == ErrorCategory.AUTH
    print("  ✅ AUTH 分类正确")


def test_classify_timeout():
    assert classify_error(Exception("timeout")) == ErrorCategory.TIMEOUT
    assert classify_error(Exception("Connection timed out")) == ErrorCategory.TIMEOUT
    print("  ✅ TIMEOUT 分类正确")


def test_retryable():
    assert is_retryable(ErrorCategory.TIMEOUT) is True
    assert is_retryable(ErrorCategory.API_ERROR) is True
    assert is_retryable(ErrorCategory.AUTH) is False
    assert is_retryable(ErrorCategory.VALIDATION) is False
    print("  ✅ 重试判断正确")


def test_retry_success():
    """重试后成功"""
    call_count = {"n": 0}

    @retry(max_attempts=3, base_delay=0.1)
    def flaky():
        call_count["n"] += 1
        if call_count["n"] < 2:
            raise Exception("timeout")
        return "ok"

    result = flaky()
    assert result == "ok"
    assert call_count["n"] == 2
    print("  ✅ 重试后成功")


def test_retry_exhausted():
    """重试耗尽后抛出异常"""
    call_count = {"n": 0}

    @retry(max_attempts=2, base_delay=0.1)
    def always_fail():
        call_count["n"] += 1
        raise Exception("timeout")

    try:
        always_fail()
        assert False, "应抛出异常"
    except Exception:
        assert call_count["n"] == 2
    print("  ✅ 重试耗尽后抛出")


def test_retry_auth_not_retry():
    """AUTH 错误不重试"""
    call_count = {"n": 0}

    @retry(max_attempts=3, base_delay=0.1)
    def auth_fail():
        call_count["n"] += 1
        raise Exception("401 Unauthorized")

    try:
        auth_fail()
    except Exception:
        assert call_count["n"] == 1  # 只尝试一次
    print("  ✅ AUTH 错误不重试")


def test_circuit_breaker():
    """熔断器"""
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.5, name="test")

    assert cb.state == "CLOSED"
    assert cb.is_open() is False

    cb.on_failure()
    assert cb.state == "CLOSED"

    cb.on_failure()
    assert cb.state == "OPEN"
    assert cb.is_open() is True

    # 恢复期后变为半开
    time.sleep(0.6)
    assert cb.state == "HALF_OPEN"
    assert cb.is_open() is False

    # 半开后成功 → 关闭
    cb.on_success()
    assert cb.state == "CLOSED"
    print("  ✅ 熔断器状态机正确")


def test_guarded_call_fallback():
    """带熔断的重试 + 降级"""
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=30)
    call_count = {"main": 0, "fallback": 0}

    def main():
        call_count["main"] += 1
        raise Exception("timeout")

    def fallback(**kw):
        call_count["fallback"] += 1
        return "fallback_ok"

    result = guarded_call(main, cb, max_attempts=2, base_delay=0.1, fallback=fallback)
    assert result == "fallback_ok"
    assert call_count["fallback"] == 1
    # main 失败 2 次 + 重试 1 次 = 2 次尝试
    assert call_count["main"] > 0
    print("  ✅ 降级调用正确")


def test_circuit_breaker_trips():
    """熔断器打开后直接走降级"""
    cb = CircuitBreaker(failure_threshold=1, recovery_timeout=30)
    cb.on_failure()  # 打开熔断器

    call_count = {"main": 0, "fallback": 0}

    def main():
        call_count["main"] += 1
        return "main_ok"

    def fallback(**kw):
        call_count["fallback"] += 1
        return "fb"

    result = guarded_call(main, cb, fallback=fallback)
    assert result == "fb"
    assert call_count["main"] == 0  # 熔断器打开，不走主函数
    assert call_count["fallback"] == 1
    print("  ✅ 熔断器打开后直接降级")


def test_tool_guard_retry():
    """ToolGuard 重试"""
    from react_agent.resilience import ToolGuard
    guard = ToolGuard()
    call_count = {"n": 0}

    def flaky_tool(tc):
        call_count["n"] += 1
        if call_count["n"] < 3:
            raise Exception("timeout")
        return "ok"

    wrapped = guard.wrap(flaky_tool)
    result = wrapped({"function": {"name": "get_time", "arguments": "{}"}})
    assert result == "ok"
    assert call_count["n"] == 3
    print("  ✅ ToolGuard 重试成功")


def test_tool_guard_timeout():
    """ToolGuard 超时保护"""
    import json
    from react_agent.resilience import ToolGuard
    guard = ToolGuard()
    # 将该工具超时压到 1 秒，避免单测真睡 30s+
    guard._TOOL_TIMEOUTS = {**ToolGuard._TOOL_TIMEOUTS, "execute_python": 1}

    def slow_tool(tc):
        time.sleep(3)
        return "ok"

    wrapped = guard.wrap(slow_tool)
    result = wrapped({"function": {"name": "execute_python", "arguments": "{}"}})
    parsed = json.loads(result)
    assert "超时" in parsed.get("error", ""), f"应超时，实际: {result}"
    print("  ✅ ToolGuard 超时保护正确")


def test_tool_guard_dangerous_no_retry():
    """危险工具不重试"""
    from react_agent.resilience import ToolGuard
    guard = ToolGuard()
    call_count = {"n": 0}

    def fail_tool(tc):
        call_count["n"] += 1
        raise Exception("error")

    wrapped = guard.wrap(fail_tool)
    wrapped({"function": {"name": "delete_directory", "arguments": "{}"}})
    assert call_count["n"] == 1  # 不重试
    print("  ✅ 危险工具不重试")


def test_tool_guard_rate_limit():
    """频率限制"""
    from react_agent.resilience import ToolGuard
    guard = ToolGuard()
    guard._max_rate = 2

    def ok_tool(tc):
        return "ok"

    wrapped = guard.wrap(ok_tool)
    tc = {"function": {"name": "web_search", "arguments": "{}"}}
    assert wrapped(tc) == "ok"  # 第1次
    assert wrapped(tc) == "ok"  # 第2次
    import json
    r = json.loads(wrapped(tc))  # 第3次
    assert r.get("blocked") is True
    print("  ✅ 频率限制正确")


def test_tool_guard_timeout_does_not_retry_detached_call():
    """超时且原调用仍在后台运行时不得重试。

    线程无法终止，重试只会在同一个卡住的工具上再叠加一个线程；对写类工具
    还意味着同一操作被并发执行两次。execute_python 属写类（max_retries=1），
    所以修复前这里会被调用 2 次。
    """
    import json
    from react_agent.resilience import ToolGuard
    guard = ToolGuard()
    guard._TOOL_TIMEOUTS = {**ToolGuard._TOOL_TIMEOUTS, "execute_python": 1}
    calls = {"n": 0}
    release = threading.Event()

    def stuck_tool(tc):
        calls["n"] += 1
        release.wait(timeout=10)  # 远长于 1s 超时，保证超时时线程仍在跑
        return "ok"

    try:
        result = json.loads(guard.wrap(stuck_tool)(
            {"function": {"name": "execute_python", "arguments": "{}"}}))
        assert "超时" in result.get("error", ""), result
        assert calls["n"] == 1, f"仍在运行的超时调用不应重试，实际调用 {calls['n']} 次"
    finally:
        release.set()
    print("  ✅ 超时且仍在运行时不再重试")


def test_tool_guard_blocks_when_detached_calls_saturated(monkeypatch):
    """后台遗留调用触顶时快速失败，而不是继续叠加线程。"""
    import json
    from react_agent import resilience
    from react_agent.resilience import ToolGuard

    monkeypatch.setattr(resilience, "_detached_calls", resilience.MAX_DETACHED_CALLS)
    guard = ToolGuard()
    result = json.loads(guard.wrap(lambda tc: "ok")(
        {"function": {"name": "get_time", "arguments": "{}"}}))
    assert result.get("blocked") is True, result
    assert "仍在后台运行" in result.get("error", ""), result
    print("  ✅ 遗留调用触顶后快速失败")


def test_detached_call_count_recovers_after_thread_finishes():
    """后台调用结束后计数必须回落，不能永久泄漏。"""
    from react_agent.resilience import _call_with_timeout, detached_call_count
    release = threading.Event()

    def stuck(tc):
        release.wait(timeout=10)
        return "ok"

    raised = False
    try:
        _call_with_timeout(stuck, {}, timeout=0.2)
    except TimeoutError:
        raised = True
    assert raised, "应抛出 TimeoutError"
    assert detached_call_count() >= 1, "超时后应计入遗留调用"

    release.set()
    deadline = time.time() + 5
    while detached_call_count() and time.time() < deadline:
        time.sleep(0.05)
    assert detached_call_count() == 0, "后台线程结束后计数应回落到 0"
    print("  ✅ 遗留调用计数可回落")


if __name__ == "__main__":
    print("=" * 50)
    print("  Resilience 模块测试")
    print("=" * 50)
    test_classify_auth()
    test_classify_timeout()
    test_retryable()
    test_retry_success()
    test_retry_exhausted()
    test_retry_auth_not_retry()
    test_circuit_breaker()
    test_guarded_call_fallback()
    test_circuit_breaker_trips()
    test_tool_guard_retry()
    test_tool_guard_timeout()
    test_tool_guard_dangerous_no_retry()
    test_tool_guard_rate_limit()
    # test_tool_guard_blocks_when_detached_calls_saturated 需要 pytest 的 monkeypatch
    test_tool_guard_timeout_does_not_retry_detached_call()
    test_detached_call_count_recovers_after_thread_finishes()
    print("\n  ✅ 全部测试通过")
