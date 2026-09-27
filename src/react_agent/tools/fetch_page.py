"""读取网页内容并提取正文（含 SSRF 防护）"""
import json
import re
from urllib import request as req
from urllib.parse import urlparse, quote

from react_agent.safety.net_guard import build_opener, validate_url

MAX_CHARS = 3000
_MAX_BYTES = 200_000


def _fetch(url: str, headers: dict) -> str:
    """经 SSRF 守卫抓取；重定向逐跳复检。"""
    ok, reason = validate_url(url)
    if not ok:
        return f"[已拦截] {reason}"
    try:
        request = req.Request(url, headers=headers)
        with build_opener().open(request, timeout=10) as resp:
            return resp.read(_MAX_BYTES).decode("utf-8", errors="replace")
    except Exception as e:
        return f"[读取失败] {e}"


def fetch_page(url: str) -> str:
    """读取网页内容并提取正文"""
    try:
        # 先做一次显式校验，让被拦截的地址有明确、可读的原因
        ok, reason = validate_url(url)
        if not ok:
            return f"不支持的地址: {reason}"

        parsed = urlparse(url)
        netloc = (parsed.hostname or "").lower()

        # 如果是维基百科，用 API 直接取纯文本
        if netloc == "wikipedia.org" or netloc.endswith(".wikipedia.org"):
            title = url.split("/wiki/")[-1].split("#")[0]
            api_url = (f"https://{netloc}/w/api.php"
                       f"?action=query&prop=extracts&explaintext"
                       f"&titles={quote(title)}&format=json&exchars=3000")
            raw = _fetch(api_url, {"User-Agent": "Mozilla/5.0"})
            if raw.startswith("["):
                return raw
            data = json.loads(raw)
            pages = data.get("query", {}).get("pages", {})
            for pid, pdata in pages.items():
                if pid != "-1" and "extract" in pdata:
                    text = pdata["extract"].strip()
                    if len(text) > MAX_CHARS:
                        text = text[:MAX_CHARS] + "\n\n...(截取)"
                    return text if text else "页面无内容"
            return "页面无内容"

        # 非维基百科：请求网页
        raw = _fetch(url, {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
        })
        if raw.startswith("[") and ("已拦截" in raw or "读取失败" in raw):
            return raw
        html = raw

        paras = re.findall(
            r'<p[^>]*>([^<]+(?:<[^/][^>]*>[^<]*</[^>]+>)?[^<]*)</p>',
            html, re.DOTALL
        )
        if paras:
            text = "\n".join(p.strip() for p in paras)
            text = re.sub(r'<[^>]+>', '', text)
            text = re.sub(r'\n{3,}', '\n\n', text).strip()
        else:
            text = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL)
            text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL)
            text = re.sub(r'<[^>]+>', '\n', text)
            text = re.sub(r'\n[ \t]+\n', '\n', text)
            text = re.sub(r'\n{3,}', '\n\n', text).strip()

        if len(text) > MAX_CHARS:
            text = text[:MAX_CHARS] + "\n\n...(截取)"
        return text if text else "页面无正文可提取"

    except Exception as e:
        return f"读取失败: {e}"


TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "fetch_page",
        "description": "读取网页内容，输入URL返回正文文本",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "要读取的网页地址"
                }
            },
            "required": ["url"],
        },
    },
}
