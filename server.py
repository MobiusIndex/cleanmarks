#!/usr/bin/env python3
"""界面 + 转发层（www 服务，跑在 wm-web 容器里）。

架构：浏览器 ⇄ 本进程（静态页面 + 少量自研端点）⇄ wr-core（清洗引擎）。
浏览器不直接连 wr-core：它不发 CORS 头，而且原始二进制要在这里换成引擎
要求的 base64 JSON 信封。

和上一版的区别（这一版把"能跑"改成"跑对"）：

* 二进制直传。页面把 File 作为请求体发过来，这里流式落盘、分块编码后再
  送给引擎，输出解码回二进制用 `application/octet-stream` 回给浏览器。
  上一版让浏览器自己做 base64（大文件会卡死主线程，且 1.33 倍膨胀全在
  页面内存里）；现在页面只拿到一个 Blob，report 走 `X-Wm-Report` 头。
* 按引擎自己的扩展名表分流。纯文本（.txt/.json/.py…）引擎的 /clean 会强制
  要求 Layer B 重写后端，未配置时必然 400，所以这类文件在这里用引擎自带的
  text_unicode 做 Layer A；Markdown/HTML/SVG 这类"文本型容器"走引擎（剥
  frontmatter、内嵌 data URI），需要时再补一遍 Layer A 归一化。上一版是
  先发一次请求撞 400 再回退，每个文件多一个来回。
* /api/meta 一次性把能力、选项白名单、限额交给页面。上一版靠 13 次空请求
  探测哪些选项被接受，慢且随引擎版本漂移。
* 大响应不再整个读进内存：上游 JSON 落盘后按 mmap 扫出 `cleaned` 字段，
  分块 base64 解码直接写目标文件。

    python3 server.py [--port 8770] [--upstream http://127.0.0.1:8765]
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import shutil
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http import HTTPStatus
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
WEB_VERSION = "0.7.5"
UPSTREAM = os.environ.get("WATERMARKS_UPSTREAM", "http://127.0.0.1:8765").rstrip("/")
SCRIPTS_DIR = Path(os.environ.get("WATERMARKS_SCRIPTS", "/app/scripts"))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

# 引擎的输入上限（common.py: MAX_INPUT_BYTES）。base64 信封是它的 1.5 倍。
MAX_INPUT = int(os.environ.get("WATERMARKS_MAX_INPUT_BYTES", str(256 << 20)))
MAX_ENVELOPE = MAX_INPUT + (MAX_INPUT >> 1)
MAX_BATCH = int(os.environ.get("WATERMARKS_MAX_BATCH_FILES", "50"))
# 纯文本要整体读进内存做 Layer A（含 LLM 时还要再拼一份），单独设个上限
MAX_TEXT_BYTES = int(os.environ.get("WATERMARKS_MAX_TEXT_BYTES", str(32 << 20)))
UPSTREAM_TIMEOUT = int(os.environ.get("WATERMARKS_WEB_TIMEOUT", "1800"))

CHUNK = 1 << 20

# wr-core 0.7.0 的 format_dispatch 扩展名表（同一张表决定引擎走哪条管线）。
# 这里抄一份是为了不让界面层 import container_meta/image_meta —— 那是几百 KB
# 的重模块，只为一个扩展名判断不值得。
IMAGE_EXTS = frozenset(
    ".avif .bmp .gif .heic .heif .jpeg .jpg .png .tif .tiff .webp".split()
)
CONTAINER_EXTS = frozenset(
    ".docx .epub .htm .html .markdown .md .mdx .odt .pdf .pptx .svg .xlsx".split()
)
TEXT_EXTS = frozenset(
    ".adoc .arb .asciidoc .astro .bash .c .cc .cfg .cjs .conf .cpp .cs .css .csv "
    ".dart .gd .gdshader .go .h .hpp .ini .java .js .json .jsx .kt .kts .lua .mjs "
    ".org .php .pl .po .pot .properties .ps1 .py .r .rb .resx .rs .rst .scala .sh "
    ".sql .strings .svelte .swift .tex .text .toml .ts .tsv .tsx .txt .vue .yaml "
    ".yml .zsh".split()
)
AV_EXTS = frozenset(".flac .m4a .m4v .mov .mp3 .mp4 .wav".split())

# 磁盘上是纯文本、但引擎按"容器"处理（要剥 frontmatter / 内嵌 data URI）的
# 格式。需要 NFKC/同形字时可以对清洗结果再补一遍 Layer A。
TEXT_LIKE_CONTAINERS = frozenset(".md .markdown .mdx .html .htm .svg".split())

# 引擎 /clean 的选项白名单。启动时用 /openapi.json 覆盖，探测失败才用这份。
FALLBACK_CLEAN_OPTIONS = {
    "nfkc": bool,
    "aggressive_homoglyphs": bool,
    "normalize_spaces": bool,
    "keep_non_ai_metadata": bool,
    "also_layer_a_text": bool,
    "remove_pixel": str,
    "remove_audio_watermark": bool,
    "strip_all_metadata": bool,
    "detect_before": bool,
    "detect_after": bool,
    "deep_images": str,
    "style": str,
    "strategy": str,
}
DEEP_IMAGE_MODES = ("auto", "always", "lossless", "never")

STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/i18n.js": ("i18n.js", "text/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/favicon.ico": (None, "image/x-icon"),
}

# 每个清理请求在 /tmp（tmpfs）上的峰值约 3.3–3.7 倍文件大小，限量并发免得打满内存
CLEAN_SLOTS = threading.BoundedSemaphore(int(os.environ.get("WATERMARKS_WEB_CONCURRENCY", "2")))

META_TTL = 60.0
_LAYER_B_TTL_OK = 1800.0
_LAYER_B_TTL_NO = 300.0
_layer_b_cache: dict[str, object] = {"at": 0.0, "value": None}
_meta_lock = threading.Lock()
_meta_cache: dict[str, object] = {"at": 0.0, "value": None}


def _upstream_host_port() -> tuple[str, int]:
    parts = urllib.parse.urlsplit(UPSTREAM)
    if parts.scheme not in ("http", "https"):
        raise ValueError(f"不支持的 upstream 协议: {UPSTREAM}")
    host = parts.hostname or "127.0.0.1"
    port = parts.port or (443 if parts.scheme == "https" else 80)
    return host, port


def _core_options(options: dict) -> dict:
    """只把引擎认识的键转发过去；界面侧的多余开关（如 strip_bidi）不给上游。"""
    allowed = _allowed_options()
    return {k: v for k, v in options.items() if k in allowed}


def _allowed_options() -> set[str]:
    cached = _meta_cache.get("value")
    if isinstance(cached, dict) and cached.get("clean_options"):
        return set(cached["clean_options"])
    return set(FALLBACK_CLEAN_OPTIONS)


def _classify(name: str) -> str:
    ext = Path(name).suffix.lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in AV_EXTS:
        return "av"
    if ext in CONTAINER_EXTS:
        return "container"
    if ext in TEXT_EXTS:
        return "text"
    return "unknown"


def _sniff(head: bytes) -> tuple[str, str]:
    """按文件头猜类型，只认不会误判的魔数。

    用于没有扩展名的文件（截图工具、clipboard、导出时的临时名）。扩展名可用时
    一律以扩展名为准，和引擎的判定保持一致。
    """
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "image", ".png"
    if head[:3] == b"\xff\xd8\xff":
        return "image", ".jpg"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "image", ".gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image", ".webp"
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "av", ".wav"
    if head[:4] == b"fLaC":
        return "av", ".flac"
    if head[:4] == b"ID3":
        return "av", ".mp3"
    if head[:2] == b"BM":
        return "image", ".bmp"
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return "image", ".tiff"
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in (b"avif", b"avis"):
            return "image", ".avif"
        if brand in (b"heic", b"heix", b"hevx", b"mif1"):
            return "image", ".heic"
        if brand == b"qt  ":
            return "av", ".mov"
        if brand in (b"M4A ", b"M4B "):
            return "av", ".m4a"
        return "av", ".mp4"
    if head[:5] == b"%PDF-":
        return "container", ".pdf"
    return "unknown", ""


def _safe_filename(name: str) -> str:
    """引擎会拒绝带路径的文件名；这里只留文件名部分。"""
    name = (name or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(ch for ch in name if ch >= " " and ch != "\x7f").strip()
    if not name:
        return "file"
    if len(name) <= 180:
        return name
    # 截断时保住扩展名：否则 200 字符的文件名会丢掉 .docx，格式判定直接失败
    suffix = Path(name).suffix
    if suffix:
        return name[: max(1, 180 - len(suffix))] + suffix
    return name[:180]


def _plausible_text(head: bytes, total: int) -> bool:
    """没有扩展名时的兜底判断：这看起来是不是一个纯文本文件。

    覆盖 Dockerfile / Makefile / LICENSE / .gitignore 这类没有后缀的常见文件——
    引擎的扩展名表管不到它们，但内容确实是文本。
    """
    if total > 32 * 1024 * 1024:      # 大文件不猜，交给魔数或拒绝
        return False
    if b"\x00" in head:
        return False
    sample = head.decode("utf-8", errors="replace")
    if not sample:
        return False
    bad = sum(1 for ch in sample if ord(ch) < 32 and ch not in "\t\n\r\f\v")
    return bad / len(sample) < 0.01


# --------------------------------------------------------------------------
# 可选的 AI 接口配置（Layer B 文本改写）
#
# 配置由浏览器通过 X-Wm-Llm 头按请求带来，服务端不落盘、不写环境变量，
# 因此不改 compose、不重启引擎也能用。没带这个头就走原来的纯 Layer A 流程。
# --------------------------------------------------------------------------

LLM_HEADER = "X-Wm-Llm"
LLM_TIMEOUT_RANGE = (10, 600)
LLM_TACTICS = ("paraphrase", "backtranslate", "structural", "humanize", "code", "chunk")


def _b64json(value: str) -> dict:
    raw = value + "=" * (-len(value) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(raw).decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        raise UpstreamError(f"{LLM_HEADER} 不是合法的 base64url JSON: {e}", 400) from None
    if not isinstance(data, dict):
        raise UpstreamError(f"{LLM_HEADER} 必须是 JSON 对象", 400)
    return data


def _normalize_llm(raw: dict) -> dict:
    """校验并归一化来自浏览器的 LLM 配置。"""
    if not raw.get("enabled"):
        return {}
    base_url = str(raw.get("base_url") or "").strip().rstrip("/")
    if not base_url:
        raise UpstreamError("已启用 AI 接口，但没填 Base URL", 400)
    if not base_url.startswith(("http://", "https://")):
        raise UpstreamError("Base URL 只支持 http/https", 400)
    model = str(raw.get("model") or "").strip()
    if not model:
        raise UpstreamError("已启用 AI 接口，但没填模型名", 400)
    backend = str(raw.get("backend") or "openai-compatible").strip()
    if backend not in ("openai-compatible", "ollama"):
        raise UpstreamError(f"不支持的后端类型: {backend}", 400)
    strategy = str(raw.get("strategy") or "paraphrase@0.8").strip()
    try:
        from rewrite_text import parse_strategy

        steps = parse_strategy(strategy)
    except ImportError as e:
        raise UpstreamError(f"镜像里缺少重写模块 rewrite_text: {e}", 500) from None
    except ValueError as e:
        raise UpstreamError(f"重写策略不合法: {e}", 400) from None
    if any(t == "mlm" for t, _ in steps):
        raise UpstreamError("策略里的 mlm 战术需要 transformers，当前镜像未安装", 400)
    try:
        timeout = int(float(raw.get("timeout") or 120))
    except (TypeError, ValueError):
        timeout = 120
    timeout = max(LLM_TIMEOUT_RANGE[0], min(LLM_TIMEOUT_RANGE[1], timeout))
    try:
        temperature = float(raw.get("temperature", 0.9))
    except (TypeError, ValueError):
        temperature = 0.9
    temperature = max(0.0, min(2.0, temperature))
    effort = str(raw.get("reasoning_effort") or "none").strip()
    if effort not in ("none", "off", "low", "medium", "high"):
        effort = "none"
    return {
        "backend": backend,
        "base_url": base_url,
        "model": model,
        "api_key": str(raw.get("api_key") or "").strip(),
        "strategy": strategy,
        "steps": steps,
        "timeout": timeout,
        "temperature": temperature,
        "reasoning_effort": effort,
        "lang": str(raw.get("lang") or "English").strip() or "English",
        "original_lang": str(raw.get("original_lang") or "Chinese").strip() or "Chinese",
        "style": str(raw.get("style") or "").strip(),
        "provider": str(raw.get("provider") or "").strip(),
    }


def _chat_endpoint(base: str) -> str:
    """把用户填的 Base URL 拼成 chat/completions 端点。

    各家前缀不一样：OpenAI/DeepSeek 是 /v1，智谱是 /api/paas/v4，百炼是
    /compatible-mode/v1，Gemini 的 OpenAI 兼容层是 /v1beta/openai。
    """
    b = base.rstrip("/")
    if b.endswith("/chat/completions"):
        return b
    for suffix in ("/v1", "/v2", "/v3", "/v4", "/openai"):
        if b.endswith(suffix):
            return b + "/chat/completions"
    return b + "/v1/chat/completions"


def _scrub_secret(text: str, secret: str) -> str:
    """错误信息里不要出现密钥。"""
    if secret:
        text = text.replace(secret, "***")
    return text[:400]


def _is_local_host(host: str) -> bool:
    """这个主机名是不是"本机/内网"——只有这种才值得做网关回退。

    云服务商的域名（api.openai.com、open.bigmodel.cn…）解析不了就是配错了，
    换成网关 IP 重发只会把 Authorization 头送给别人；本地模型则反过来，容器
    根本解析不到 host.docker.internal，必须回退。
    """
    h = (host or "").lower().strip(".")
    if not h:
        return False
    if h in {"localhost", "host.docker.internal", "gateway.docker.internal", "host.containers.internal"}:
        return True
    if "." not in h:                      # ollama / lmstudio 这类裸主机名
        return True
    if h.endswith((".local", ".internal", ".localhost", ".lan", ".home", ".localdomain")):
        return True
    if h.startswith(("127.", "10.", "192.168.", "169.254.")):
        return True
    if h.startswith("172."):
        try:
            return 16 <= int(h.split(".")[1]) <= 31
        except (IndexError, ValueError):
            return False
    return False


def _host_candidates(host: str) -> list[str]:
    """域名解析不了时，按可能性顺序给出备选主机。

    这台机器的 Docker 是跑在 WSL 里的（不是 Docker Desktop），容器里没有
    host.docker.internal 这个 DNS；WSL 侧的服务（Ollama、中转脚本）在容器的
    默认网关上，所以网关地址排在最前面。Windows 上跑的服务（LM Studio）走
    Docker 网关是够不到的——WSL 与 Windows 不共享 loopback。
    """
    cands: list[str] = [host]

    def add(ip: str) -> None:
        if ip and ip not in cands and not ip.startswith("127."):
            cands.append(ip)

    # 容器自己的默认网关 = 宿主机（WSL）在这条 docker 网络上的地址
    try:
        for line in Path("/proc/net/route").read_text().splitlines()[1:]:
            parts = line.split()
            if len(parts) > 2 and parts[1] == "00000000":
                add(".".join(str(int(parts[2][i:i + 2], 16)) for i in (6, 4, 2, 0)))
    except (OSError, ValueError):
        pass
    add("172.17.0.1")
    try:
        for line in Path("/etc/resolv.conf").read_text().splitlines():
            if line.startswith("nameserver"):
                add(line.split()[1])
    except OSError:
        pass
    return cands


def _url_with_host(url: str, host: str) -> str:
    parts = urllib.parse.urlsplit(url)
    netloc = parts.netloc
    if "@" in netloc:
        netloc = netloc.split("@", 1)[1]
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return urllib.parse.urlunsplit((parts.scheme, f"{host}:{parts.port}" if parts.port else host,
                                    parts.path, parts.query, parts.fragment))


def _llm_chat(cfg: dict, prompt: str) -> str:
    """调用一次 chat completions，返回文本内容。"""
    timeout = cfg["timeout"]
    if cfg["backend"] == "ollama":
        url = cfg["base_url"].rstrip("/") + "/api/chat"
        payload = {
            "model": cfg["model"],
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": cfg["temperature"]},
        }
    else:
        url = _chat_endpoint(cfg["base_url"])
        payload = {
            "model": cfg["model"],
            "messages": [{"role": "user", "content": prompt}],
            "temperature": cfg["temperature"],
        }
        if cfg["reasoning_effort"] not in ("none", "off"):
            payload["reasoning_effort"] = cfg["reasoning_effort"]
    headers = {"Content-Type": "application/json"}
    if cfg["api_key"]:
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    body = json.dumps(payload).encode("utf-8")
    host = urllib.parse.urlsplit(url).hostname or ""
    # 只有本机/内网地址才做网关回退：云服务商的域名解析不了就是配错了，
    # 换成网关 IP 重发等于把 Bearer 密钥送给别人（明文 http 下尤其危险）
    candidates = _host_candidates(host) if _is_local_host(host) else [host]
    last: Exception | None = None
    for candidate in candidates:
        target = _url_with_host(url, candidate)
        req = urllib.request.Request(target, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read() or b"{}")
            break
        except urllib.error.HTTPError as e:
            detail = _scrub_secret(e.read()[:300].decode("utf-8", "replace"), cfg["api_key"])
            raise UpstreamError(f"AI 接口返回 {e.code}: {detail}", 400) from None
        except urllib.error.URLError as e:
            last = e
            continue
        except TimeoutError:
            raise UpstreamError(f"AI 接口超时（>{timeout}s）", 504) from None
        except Exception as e:  # noqa: BLE001
            raise UpstreamError(
                f"AI 接口调用失败: {_scrub_secret(str(e), cfg['api_key'])}", 400
            ) from None
    else:
        reason = getattr(last, "reason", last) if last else "未知原因"
        raise UpstreamError(f"连不上 AI 接口（{cfg['base_url']}）: {reason}", 400)

    if cfg["backend"] == "ollama":
        content = (data.get("message") or {}).get("content")
    else:
        choices = data.get("choices") or []
        content = ((choices[0].get("message") or {}).get("content") if choices else None)
    if not content:
        raise UpstreamError("AI 接口没有返回内容", 400)
    return str(content).strip()


def _apply_layer_b(text: str, cfg: dict) -> tuple[str, dict]:
    """按策略跑 Layer B 改写。

    提示词与策略解析直接用引擎镜像里的 rewrite_text（上游原文），只有「调哪
    个接口」这一步在我们这边实现——这样各家服务商的前缀差异都能支持。
    """
    from rewrite_text import build_prompt

    cur = text
    step_stats: list[dict] = []
    for tactic, intensity in cfg["steps"]:
        prompt = build_prompt(
            tactic,
            cur,
            lang=cfg["lang"],
            original_lang=cfg["original_lang"],
            rewrite_level=intensity,
            style=cfg["style"] or None,
        )
        # 上游提示词是英文的，且没写"保持原语言"——中文正文容易被顺手翻成英文，
        # 这里补一句约束（backtranslate 自带语言参数，不加）。
        if tactic != "backtranslate":
            prompt += "\n\nKeep the output in the same language as the input."
        out = _llm_chat(cfg, prompt)
        step_stats.append({
            "tactic": tactic,
            "intensity": round(intensity, 4),
            "in_chars": len(cur),
            "out_chars": len(out),
        })
        cur = out
    # 改写结果再扫一遍隐形字符（上游 layer_a_after 的行为）
    try:
        from text_unicode import clean_text

        cur, _ = clean_text(cur, nfkc=False, aggressive_homoglyphs=False, normalize_spaces=True)
    except Exception:  # noqa: BLE001
        pass
    stats = {
        "backend": cfg["backend"],
        "mode": "strategy",
        "strategy": [f"{t}@{i:g}" for t, i in cfg["steps"]],
        "steps": step_stats,
        "model": cfg["model"],
        "provider": cfg["provider"],
        "input_chars": len(text),
        "output_chars": len(cur),
    }
    return cur, stats



REPORT_HEADER_LIMIT = 12 * 1024


def _pack_report(report: dict) -> str:
    """report 以 base64 放在 X-Wm-Report 里；超过 12KB 会裁明细。

    部分代理/客户端会丢弃过大的响应头，宁可带个 truncated 标记也不要整条丢。
    """

    def pack(obj: dict) -> str:
        return base64.b64encode(json.dumps(obj, ensure_ascii=False).encode("utf-8")).decode("ascii")

    packed = pack(report)
    if len(packed) <= REPORT_HEADER_LIMIT:
        return packed
    slim = dict(report)
    slim["truncated"] = True
    for key in ("findings", "post_findings", "findings_confidence", "actions", "suspicious", "tools"):
        value = slim.get(key)
        if isinstance(value, list) and len(value) > 8:
            slim[key] = value[:8]
    for key in ("report", "details", "trace"):
        slim.pop(key, None)
    packed = pack(slim)
    while len(packed) > REPORT_HEADER_LIMIT:
        shrunk = False
        for key in ("findings", "post_findings", "actions"):
            value = slim.get(key)
            if isinstance(value, list) and value:
                slim[key] = value[: len(value) // 2]
                shrunk = True
        if not shrunk:
            break
        packed = pack(slim)
    return packed


def _content_disposition(name: str) -> str:
    ascii_name = name.encode("ascii", "replace").decode("ascii").replace('"', "_")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{urllib.parse.quote(name)}"


def _log_exc(what: str, exc: BaseException) -> None:
    """内部异常只进日志，不回给客户端（避免暴露模块名/路径）。"""
    try:
        import traceback

        sys.stderr.write(f"[wm-web] {what}: {type(exc).__name__}: {exc}\n")
        traceback.print_exc(file=sys.stderr)
    except Exception:  # noqa: BLE001
        pass


class UpstreamError(RuntimeError):
    def __init__(self, message: str, status: int = 502) -> None:
        super().__init__(message)
        self.status = status


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "wm-web"
    # 慢上传 / 慢下载不能无限期占住线程
    timeout = 120
    tmpdir = Path(tempfile.gettempdir())

    # ---------------------------------------------------------------- 输出

    def _send(self, code: int, body: bytes, ctype: str, extra: dict[str, str] | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        # 4xx 大多是"没读请求体就回话"，socket 里还留着上传数据；不关连接的话
        # 这些字节会被当成下一个请求解析（keep-alive 错位，日志里能看到
        # `"0123...GET /api/health" 501`）。出错就关连接，简单可靠。
        if code >= 400:
            self.close_connection = True
            self.send_header("Connection", "close")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code: int, data: object) -> None:
        self._send(code, json.dumps(data, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _fail(self, code: int, message: str) -> None:
        self._json(code, {"ok": False, "error": message})

    # ---------------------------------------------------------------- 路由

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def do_GET(self) -> None:  # noqa: N802
        try:
            self._do_get()
        except UpstreamError as e:
            self._fail(e.status, str(e))
        except Exception as e:  # noqa: BLE001
            _log_exc("GET 处理失败", e)
            self._fail(500, "内部错误，详情见容器日志")

    def _do_get(self) -> None:
        path = urllib.parse.urlsplit(self.path).path
        if path in STATIC:
            fname, ctype = STATIC[path]
            if fname is None:
                self._send(204, b"", ctype)
                return
            self._static(fname, ctype)
            return
        if path == "/api/ping":
            # 只报 web 进程自己活着。健康检查用它，引擎挂掉时容器不该跟着判死
            self._json(200, {"ok": True, "web_version": WEB_VERSION})
            return
        if path == "/api/meta":
            self._json(200, _build_meta())
            return
        if path.startswith("/api/"):
            self._proxy(self.path)      # 带上 query，别把它吞掉
            return
        # 任意深链接一律回首页（单页应用，刷新不会 404）
        self._static("index.html", "text/html; charset=utf-8")

    def do_POST(self) -> None:  # noqa: N802
        path = urllib.parse.urlsplit(self.path).path
        # 同源校验：服务只绑回环，但任意网页都能用 fetch 打过来（CORS simple
        # request 不需要预检）。带 Origin 且与 Host 不一致的，一律拒绝。
        origin = self.headers.get("Origin")
        if origin and origin != "null":
            host = self.headers.get("Host") or ""
            if urllib.parse.urlsplit(origin).netloc != host:
                self._fail(403, "跨站请求被拒绝")
                return
        try:
            if path == "/api/raw/clean":
                self._raw_clean()
                return
            if path == "/api/raw/inspect":
                self._raw_inspect()
                return
            if path == "/api/text-clean":
                self._text_clean_json()
                return
            if path == "/api/llm/test":
                self._llm_test()
                return
            if path.startswith("/api/"):
                self._proxy(path)
                return
        except UpstreamError as e:
            self._fail(e.status, str(e))
            return
        except BrokenPipeError:
            raise
        except Exception as e:  # noqa: BLE001
            _log_exc("处理请求失败", e)
            self._fail(500, "内部错误，详情见容器日志")
            return
        self._fail(404, "not found")

    def _static(self, fname: str, ctype: str) -> None:
        try:
            body = (HERE / fname).read_bytes()
        except OSError as e:
            self._fail(500, f"{fname} 读取失败: {e}")
            return
        self._send(200, body, ctype)

    # ---------------------------------------------------------------- 请求体

    def _content_length(self) -> int:
        # 浏览器发 File 时一定带 Content-Length；但脚本用户可能用 chunked，
        # 而我们不解析分块体——直接说清楚，别把空文件当成合法输入。
        if (self.headers.get("Transfer-Encoding") or "").lower().strip() == "chunked":
            raise UpstreamError("不支持分块传输（Transfer-Encoding: chunked），请带 Content-Length", 411)
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise UpstreamError("invalid Content-Length", 400) from None
        if n < 0:
            raise UpstreamError("invalid Content-Length", 400)
        return n

    def _spool(self, remaining: int, into: Path | None = None) -> Path:
        """把请求体流式写到临时文件，不在内存里攒。

        `into` 指向本次请求的临时目录——必须传，否则这个文件会在 /tmp 里
        留下（/tmp 是 tmpfs，等于把每个上传的文件永久留在内存里）。
        """
        out = Path(tempfile.mkstemp(prefix="in-", dir=into or self.tmpdir)[1])
        try:
            with out.open("wb") as fh:
                while remaining > 0:
                    chunk = self.rfile.read(min(CHUNK, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    fh.write(chunk)
        except BaseException:
            out.unlink(missing_ok=True)
            raise
        if remaining:
            # 客户端少发了字节（连接被截断、代理截流、脚本写错），不能把半截
            # 文件当成完整输入——否则用户会拿到一个"清理成功"的残缺文件。
            out.unlink(missing_ok=True)
            raise UpstreamError(f"请求体不完整：还差 {remaining} 字节", 400)
        return out

    def _envelope(self, src: Path, name: str, options: dict | None, into: Path) -> Path:
        """把原始文件包成引擎要的 {"file": "<base64>", ...} JSON（分块，不整体进内存）。"""
        with src.open("rb") as fin, into.open("wb") as fout:
            fout.write(b'{"file":"')
            while True:
                chunk = fin.read(CHUNK - (CHUNK % 3))
                if not chunk:
                    break
                fout.write(base64.b64encode(chunk))
            fout.write(b'"')
            if name:
                fout.write(b',"name":')
                fout.write(json.dumps(name).encode("utf-8"))
            if options:
                fout.write(b',"options":')
                fout.write(json.dumps(options, ensure_ascii=False).encode("utf-8"))
            fout.write(b"}")
        return into

    def _read_meta_headers(self, want_llm: bool = True) -> tuple[str, dict, dict]:
        raw_name = self.headers.get("X-Wm-Name") or ""
        raw_opts = self.headers.get("X-Wm-Options") or ""
        raw_llm = self.headers.get(LLM_HEADER) or ""
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        name = ""
        if raw_name:
            try:
                name = base64.urlsafe_b64decode(raw_name + "=" * (-len(raw_name) % 4)).decode("utf-8")
            except Exception:  # noqa: BLE001
                raise UpstreamError("X-Wm-Name 不是合法的 base64url", 400) from None
        elif "name" in query:
            name = query["name"][0]
        options: dict = {}
        if raw_opts:
            try:
                options = json.loads(base64.urlsafe_b64decode(
                    raw_opts + "=" * (-len(raw_opts) % 4)).decode("utf-8")) or {}
            except Exception:  # noqa: BLE001
                raise UpstreamError("X-Wm-Options 不是合法的 base64url JSON", 400) from None
        elif "options" in query:
            try:
                options = json.loads(query["options"][0]) or {}
            except Exception:  # noqa: BLE001
                raise UpstreamError("options 查询参数不是合法 JSON", 400) from None
        if not isinstance(options, dict):
            raise UpstreamError("options 必须是对象", 400)
        llm = _normalize_llm(_b64json(raw_llm)) if (raw_llm and want_llm) else {}
        return _safe_filename(name), options, llm

    # ---------------------------------------------------------------- 上游

    def _upstream(self, path: str, body_path: Path, length: int,
                  workdir: Path | None = None) -> tuple[int, dict, bytes | Path]:
        """POST 到引擎。返回 (status, headers, body)。大响应落盘，小响应给 bytes。"""
        host, port = _upstream_host_port()
        conn = HTTPConnection(host, port, timeout=UPSTREAM_TIMEOUT)
        try:
            conn.putrequest("POST", path, skip_accept_encoding=True)
            conn.putheader("Content-Type", "application/json")
            conn.putheader("Content-Length", str(length))
            conn.putheader("Accept", "application/json")
            conn.endheaders()
            with body_path.open("rb") as fh:
                while True:
                    chunk = fh.read(CHUNK)
                    if not chunk:
                        break
                    conn.send(chunk)
            resp = conn.getresponse()
            status = resp.status
            headers = {k.lower(): v for k, v in resp.getheaders()}
            length_hdr = int(headers.get("content-length") or 0)
            # 没给 Content-Length（chunked）也走落盘，否则会把几十 MB 的 base64
            # 整个读进内存，绕开 mmap 那套设计。
            if status != 200 or length_hdr <= 0 or length_hdr > 8 * CHUNK:
                spill = Path(tempfile.mkstemp(prefix="resp-", dir=workdir or self.tmpdir)[1])
                try:
                    with spill.open("wb") as fh:
                        while True:
                            chunk = resp.read(CHUNK)
                            if not chunk:
                                break
                            fh.write(chunk)
                except BaseException:
                    spill.unlink(missing_ok=True)
                    raise
                return status, headers, spill
            return status, headers, resp.read()
        except (ConnectionError, OSError) as e:
            raise UpstreamError(f"与 wr-core 通信失败（{UPSTREAM}）: {e}") from None
        finally:
            conn.close()

    def _proxy(self, path: str) -> None:
        """兼容旧调用：/api/xxx → 引擎 /xxx，请求体原样转发（JSON 信封）。"""
        length = self._content_length()
        if length > MAX_ENVELOPE:
            self._fail(413, f"请求体过大：{length} 字节，上限 {MAX_ENVELOPE}")
            return
        if self.command == "GET":
            target = f"{UPSTREAM}{path[len('/api'):] or '/'}"
            try:
                with urllib.request.urlopen(target, timeout=60) as r:
                    self._send(r.status, r.read(), r.headers.get("Content-Type", "application/json"))
            except urllib.error.HTTPError as e:
                self._send(e.code, e.read(), e.headers.get("Content-Type", "application/json"))
            except urllib.error.URLError as e:
                self._fail(502, f"无法连接 wr-core ({UPSTREAM}): {e.reason}")
            return
        tmp = Path(tempfile.mkdtemp(prefix="wm-proxy-", dir=self.tmpdir))
        try:
            src = self._spool(length, tmp) if length else Path(tempfile.mkstemp(prefix="in-", dir=tmp)[1])
            status, headers, body = self._upstream(path[len("/api"):] or "/", src, src.stat().st_size, tmp)
            if isinstance(body, Path):
                data = body.read_bytes()
                body.unlink(missing_ok=True)
            else:
                data = body
            self._send(status, data, headers.get("content-type", "application/json; charset=utf-8"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # ---------------------------------------------------------------- 原始二进制端点

    def _raw_inspect(self) -> None:
        length = self._content_length()
        if length > MAX_INPUT:
            self._fail(413, f"文件过大：{length} 字节，单文件上限 {MAX_INPUT}")
            return
        name, _, _ = self._read_meta_headers(want_llm=False)
        tmp = Path(tempfile.mkdtemp(prefix="wm-ins-", dir=self.tmpdir))
        try:
            src = self._spool(length, tmp)
            env = self._envelope(src, name, None, tmp / "req.json")
            status, headers, body = self._upstream("/inspect", env, env.stat().st_size, tmp)
            data = body.read_bytes() if isinstance(body, Path) else body
            if isinstance(body, Path):
                body.unlink(missing_ok=True)
            self._send(status, data, headers.get("content-type", "application/json; charset=utf-8"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _raw_clean(self) -> None:
        length = self._content_length()
        if length > MAX_INPUT:
            self._fail(413, f"文件过大：{length} 字节，单文件上限 {MAX_INPUT}")
            return
        # 一次只放行 2 个清理请求：每个在 tmpfs 上约占文件大小的 3.3–3.7 倍
        if not CLEAN_SLOTS.acquire(timeout=300):
            self._fail(503, "并发清理请求过多，请稍后重试")
            return
        try:
            self._raw_clean_locked(length)
        finally:
            CLEAN_SLOTS.release()

    def _raw_clean_locked(self, length: int) -> None:
        name, options, llm = self._read_meta_headers()
        tmp = Path(tempfile.mkdtemp(prefix="wm-clean-", dir=self.tmpdir))
        try:
            src = self._spool(length, tmp)
            kind = _classify(name)
            if kind == "unknown":
                # 没扩展名（截图、clipboard、临时导出）时按魔数认；认不出但内容
                # 确实是文本（Dockerfile / Makefile / .gitignore …）也按文本处理。
                with src.open("rb") as fh:
                    head = fh.read(8192)
                kind, ext = _sniff(head)
                if kind == "unknown":
                    # 只有「完全没有扩展名」才猜文本（Dockerfile / Makefile /
                    # .gitignore）；带扩展名但认不出的（.bin/.xyz）照样拒绝，
                    # 免得把无 NUL 的二进制当文本改写坏。
                    if not Path(name).suffix and _plausible_text(head, src.stat().st_size):
                        kind = "text"
                    else:
                        self._fail(415, f"无法识别的格式：{name or '(无文件名)'}"
                                        "（既没有已知扩展名，文件头也不匹配）")
                        return
                if ext:
                    name = (name or "file") + ext
            if kind == "text":
                report, cleaned = self._clean_text_file(src, options, llm)
            elif kind == "container" and Path(name).suffix.lower() in TEXT_LIKE_CONTAINERS and (
                options.get("nfkc") or options.get("aggressive_homoglyphs")
                or options.get("strip_bidi") or options.get("strip_emoji_glue") or llm
            ):
                # 先让引擎剥 frontmatter/内嵌数据，再补一遍 Layer A 归一化。
                report, cleaned = self._clean_upstream(src, name, _core_options(options), tmp)
                if isinstance(cleaned, Path):
                    cleaned = cleaned.read_bytes()
                report, cleaned = self._extra_layer_a(cleaned, report, options, llm)
            else:
                report, cleaned = self._clean_upstream(src, name, _core_options(options), tmp)
            self._send_cleaned(name, kind, cleaned, report, tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _clean_upstream(self, src: Path, name: str, options: dict, tmp: Path) -> tuple[dict, bytes | Path]:
        env = self._envelope(src, name, options, tmp / "req.json")
        status, headers, body = self._upstream("/clean", env, env.stat().st_size, tmp)
        body_path = body if isinstance(body, Path) else None
        if status != 200:
            payload = body_path.read_bytes() if body_path else body
            if body_path:
                body_path.unlink(missing_ok=True)
            try:
                err = json.loads(payload).get("error") or payload[:300].decode("utf-8", "replace")
            except Exception:  # noqa: BLE001
                err = payload[:300].decode("utf-8", "replace")
            raise UpstreamError(f"引擎返回 {status}: {err}", status)
        # 上游成功响应是 {"ok":true,"kind":..,"cleaned":"<base64>","report":{..}}。
        # 直接 json.loads 会把 1.33 倍的 base64 字符串整个塞进内存，所以先把
        # 响应落盘再按字段扫，解码结果也只落在临时文件里。
        if body_path is None:
            body_path = Path(tempfile.mkstemp(prefix="resp-", dir=self.tmpdir)[1])
            body_path.write_bytes(body)  # type: ignore[arg-type]
        out_path = tmp / "out.bin"
        try:
            out_path, report = _split_clean_response(body_path, out_path)
        finally:
            body_path.unlink(missing_ok=True)
        return report, out_path

    def _clean_text_file(self, src: Path, options: dict, llm: dict | None = None) -> tuple[dict, bytes]:
        data = src.read_bytes()
        if len(data) > MAX_TEXT_BYTES:
            raise UpstreamError(
                f"文本文件过大：{len(data)} 字节，纯文本上限 {MAX_TEXT_BYTES}"
                "（可调 WATERMARKS_MAX_TEXT_BYTES）", 413)
        if _looks_binary(data):
            raise UpstreamError("这看起来是二进制文件，但后缀是文本格式，已拒绝按文本清理", 422)
        try:
            text = data.decode("utf-8", errors="surrogateescape")
        except Exception as e:  # noqa: BLE001
            raise UpstreamError(f"解码失败: {e}", 422) from None
        from text_unicode import clean_text as scrub

        cleaned, stats = scrub(
            text,
            nfkc=bool(options.get("nfkc")),
            aggressive_homoglyphs=bool(options.get("aggressive_homoglyphs")),
            normalize_spaces=bool(options.get("normalize_spaces", True)),
            strip_emoji_glue=bool(options.get("strip_emoji_glue")),
            strip_bidi=bool(options.get("strip_bidi")),
        )
        report = {
            "kind": "text",
            "stats": stats,
            "changed": bool(stats.get("removed_count") or stats.get("replaced_count")
                            or stats.get("nfkc_changed")),
            "bytes_in": len(data),
            "bytes_out": len(cleaned.encode("utf-8", errors="surrogateescape")),
            "layer_a_only": True,
            "actions": [],
        }
        if llm:
            cleaned, layer_b = self._layer_b(cleaned, llm)
            report["layer_b"] = layer_b
            report["layer_a_only"] = False
            report["changed"] = True
            report["bytes_out"] = len(cleaned.encode("utf-8", errors="surrogateescape"))
            report["actions"] = [
                "Layer B 重写: " + ", ".join(layer_b.get("strategy") or [])
                + f"（{layer_b.get('model')}）"
            ]
        out = cleaned.encode("utf-8", errors="surrogateescape")
        return report, out

    def _layer_b(self, text: str, llm: dict) -> tuple[str, dict]:
        """跑 Layer B；失败时抛 4xx，错误里不带密钥。"""
        try:
            return _apply_layer_b(text, llm)
        except UpstreamError:
            raise
        except Exception as e:  # noqa: BLE001
            raise UpstreamError(
                f"Layer B 失败: {_scrub_secret(str(e), llm.get('api_key') or '')}", 400
            ) from None

    def _extra_layer_a(self, cleaned: bytes, report: dict, options: dict,
                       llm: dict | None = None) -> tuple[dict, bytes]:
        """文本型容器清洗后再做一遍 Layer A（引擎的容器管线不做 NFKC/同形字），
        配置了 AI 接口的话再跑 Layer B 改写。"""
        try:
            text = cleaned.decode("utf-8", errors="surrogateescape")
        except Exception:  # noqa: BLE001
            return report, cleaned
        try:
            from text_unicode import clean_text as scrub
            out_text, stats = scrub(
                text,
                nfkc=bool(options.get("nfkc")),
                aggressive_homoglyphs=bool(options.get("aggressive_homoglyphs")),
                normalize_spaces=bool(options.get("normalize_spaces", True)),
                strip_emoji_glue=bool(options.get("strip_emoji_glue")),
                strip_bidi=bool(options.get("strip_bidi")),
            )
        except Exception:  # noqa: BLE001
            return report, cleaned
        out = out_text.encode("utf-8", errors="surrogateescape")
        # 只发生 NFKC 变化时 removed/replaced 都是 0，但字节确实变了
        if out != cleaned or stats.get("removed_count") or stats.get("replaced_count"):
            report = dict(report)
            report.setdefault("actions", [])
            report["actions"] = list(report["actions"]) + [
                f"layer A 归一化: removed={stats.get('removed_count', 0)} "
                f"replaced={stats.get('replaced_count', 0)}"
            ]
            report["layer_a"] = stats
            report["bytes_out"] = len(out)
            report["changed"] = True
        if llm:
            new_text, layer_b = self._layer_b(out_text, llm)
            out = new_text.encode("utf-8", errors="surrogateescape")
            report = dict(report)
            report["layer_b"] = layer_b
            report["layer_a_only"] = False
            report["changed"] = True
            report["bytes_out"] = len(out)
            report["actions"] = list(report.get("actions") or []) + [
                "Layer B 重写: " + ", ".join(layer_b.get("strategy") or [])
                + f"（{layer_b.get('model')}）"
            ]
        return report, out

    def _send_cleaned(self, name: str, kind: str, body: bytes | Path, report: dict, tmp: Path) -> None:
        # 下载名必须区别于原文件，且扩展名要跟着引擎的真实输出格式走
        # （WAV → M4A 走破坏性音频链，写成 .wav 会得到一个内容对不上后缀的文件）。
        fmt = str(report.get("format") or "").lower()
        arm = report.get("audio_mark_removal")
        if isinstance(arm, dict) and arm.get("available"):
            fmt = "m4a"
        fmt = _FORMAT_EXT.get(fmt, fmt)
        stem, dot, ext = name.rpartition(".")
        if not dot or not stem:
            stem, ext = name, ""
        if fmt and fmt != ext.lower():
            # 引擎可能换容器/换扩展名（.htm→.html、wav→m4a），前端要能看见
            report = dict(report)
            report["renamed_from"] = f".{ext.lower()}" if ext else ""
            ext = fmt
        out_name = f"{stem}.cleaned.{ext}" if ext else f"{name}.cleaned"

        ctype = mimetypes.guess_type(out_name)[0] or "application/octet-stream"
        for e, mime in _MIME_OVERRIDES.items():
            if out_name.lower().endswith(e):
                ctype = mime
                break
        packed = _pack_report(report)
        extra = {
            "Content-Disposition": _content_disposition(out_name),
            "X-Wm-Report": packed,
            "X-Wm-Kind": kind,
            "X-Wm-Out-Name": base64.urlsafe_b64encode(out_name.encode("utf-8")).decode("ascii").rstrip("="),
        }
        if isinstance(body, Path):
            size = body.stat().st_size
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(size))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Wm-Bytes-Out", str(size))
            for k, v in extra.items():
                self.send_header(k, v)
            self.end_headers()
            if self.command == "HEAD":
                return
            with body.open("rb") as fh:
                while True:
                    chunk = fh.read(CHUNK)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
            return
        self._send(200, body, ctype, {**extra, "X-Wm-Bytes-Out": str(len(body))})

    def _llm_test(self) -> None:
        """AI 接口探活：发一个最小的 chat 请求，返回延迟与回复摘要。"""
        length = self._content_length()
        if length > 64 * 1024:
            self._fail(413, "配置过大")
            return
        body = self.rfile.read(length) if length else b"{}"
        try:
            raw = json.loads(body)
            if not isinstance(raw, dict):
                raise ValueError("必须是对象")
        except Exception as e:  # noqa: BLE001
            self._fail(400, f"请求格式错误: {e}")
            return
        raw["enabled"] = True
        try:
            cfg = _normalize_llm(raw)
        except UpstreamError as e:
            self._json(200, {"ok": False, "error": str(e)})
            return
        started = time.time()
        try:
            reply = _llm_chat(cfg, "Reply with the single word: OK")
        except UpstreamError as e:
            self._json(200, {
                "ok": False,
                "error": str(e),
                "latency_ms": int((time.time() - started) * 1000),
            })
            return
        endpoint = (cfg["base_url"] + "/api/chat" if cfg["backend"] == "ollama"
                    else _chat_endpoint(cfg["base_url"]))
        self._json(200, {
            "ok": True,
            "latency_ms": int((time.time() - started) * 1000),
            "reply": reply[:200],
            "model": cfg["model"],
            "endpoint": endpoint,
        })

    def _text_clean_json(self) -> None:
        """兼容上一版的 JSON 接口（页面已不用，保留给脚本调用）。"""
        length = self._content_length()
        if length > MAX_INPUT:
            self._fail(413, f"请求体过大：{length} 字节，上限 {MAX_INPUT}")
            return
        body = self.rfile.read(length) if length else b"{}"
        try:
            req = json.loads(body)
            raw = base64.b64decode(req["file"])
        except Exception as e:  # noqa: BLE001
            self._fail(400, f"请求格式错误: {e}")
            return
        tmp = Path(tempfile.mkdtemp(prefix="wm-text-", dir=self.tmpdir))
        try:
            src = tmp / "in.txt"
            src.write_bytes(raw)
            report, cleaned = self._clean_text_file(src, req)
        except UpstreamError as e:
            self._fail(e.status, str(e))
            return
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self._json(200, {
            "ok": True,
            "kind": "text",
            "cleaned": base64.b64encode(cleaned).decode("ascii"),
            "report": report,
        })

    # ---------------------------------------------------------------- 日志

    def log_message(self, fmt: str, *args: object) -> None:
        try:
            sys.stderr.write("[wm-web] " + (fmt % args) + "\n")
        except (AttributeError, ValueError, OSError):
            pass

    def handle_one_request(self) -> None:
        try:
            super().handle_one_request()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            self.close_connection = True


# 引擎 report.format 用的是检测出的真实格式，扩展名不一定一致（tiff → .tif）。
_FORMAT_EXT = {"jpeg": "jpg", "tiff": "tif", "mpeg4": "mp4", "quicktime": "mov",
               "heif": "heic", "markdown": "md"}

_MIME_OVERRIDES = {
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".svg": "image/svg+xml",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".odt": "application/vnd.oasis.opendocument.text",
    ".epub": "application/epub+zip",
    ".avif": "image/avif",
    ".heic": "image/heic",
    ".m4a": "audio/mp4",
    ".mov": "video/quicktime",
}


def _looks_binary(data: bytes) -> bool:
    if b"\x00" in data[:4096]:
        return True
    sample = data[:4096]
    if not sample:
        return False
    try:
        sample.decode("utf-8")
        return False
    except UnicodeDecodeError as e:
        # 只有解码失败且不是"截断在多字节中间"才算二进制
        return e.reason != "unexpected end of data"


def _split_clean_response(path: Path, out_path: Path) -> tuple[Path, dict]:
    """从引擎的 JSON 响应里拆出 base64 文件与 report，分块解码。

    引擎的响应键序固定为 ok / kind / cleaned / report，且 base64 里不会出现
    引号，所以按字节扫就够了——比 json.loads 少一份 GB 级的内存峰值。
    """
    import mmap

    with path.open("rb") as fh:
        size = path.stat().st_size
        if size == 0:
            raise UpstreamError("引擎返回了空响应", 502)
        mm = mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            marker = mm.find(b'"cleaned"')
            if marker < 0:
                raise UpstreamError("引擎响应里没有 cleaned 字段", 502)
            colon = mm.find(b":", marker)
            if colon < 0:
                raise UpstreamError("引擎响应格式异常（cleaned 缺冒号）", 502)
            # 跳过冒号后的空白，值必须是字符串（"null"/数字 说明引擎降级了）
            cursor = colon + 1
            while cursor < size and mm[cursor:cursor + 1].isspace():
                cursor += 1
            if mm[cursor:cursor + 1] != b'"':
                raise UpstreamError("引擎响应的 cleaned 不是字符串（可能为 null）", 502)
            cursor += 1
            end = mm.find(b'"', cursor)
            if end < 0:
                raise UpstreamError("引擎响应格式异常（cleaned 未闭合）", 502)
            with out_path.open("wb") as out:
                step = 4 * (CHUNK // 4)
                pos = cursor
                while pos < end:
                    piece = mm[pos:min(end, pos + step)]
                    pos += len(piece)
                    try:
                        out.write(base64.b64decode(piece))
                    except Exception as e:  # noqa: BLE001
                        raise UpstreamError(f"引擎 cleaned 字段无法解码: {e}", 502) from None
            head = bytes(mm[:marker]).rstrip().rstrip(b",").rstrip()
            tail = bytes(mm[end + 1:])
            try:
                meta = json.loads(head + tail)
            except Exception as e:  # noqa: BLE001
                raise UpstreamError(f"引擎 report 解析失败: {e}", 502) from None
        finally:
            mm.close()
    report = meta.get("report") or {}
    if not isinstance(report, dict):
        report = {}
    return out_path, report


def _build_meta() -> dict:
    cached = _meta_cache["value"]
    if cached and time.time() - float(_meta_cache["at"]) < META_TTL:
        return cached  # type: ignore[return-value]
    # 网络 IO 在锁外做：引擎挂掉时 _collect_meta 要等好几个超时，持锁会让
    # 并发来的 /api/meta 全部排队（双检锁：抢到锁后再看一眼缓存）
    value = _collect_meta()
    with _meta_lock:
        _meta_cache.update({"at": time.time(), "value": value})
    return value


def _fetch_json(path: str, timeout: float = 5) -> dict | None:
    try:
        with urllib.request.urlopen(f"{UPSTREAM}{path}", timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except Exception:  # noqa: BLE001
        return None


def _collect_meta() -> dict:
    health = _fetch_json("/health") or {}
    caps = _fetch_json("/capabilities") or {}
    spec = _fetch_json("/openapi.json") or {}

    options: dict[str, str] = {}
    try:
        props = spec["paths"]["/clean"]["post"]["requestBody"]["content"]["application/json"][
            "schema"]["properties"]["options"]["properties"]
        options = {k: v.get("type", "string") for k, v in props.items()}
    except Exception:  # noqa: BLE001
        options = {k: ("boolean" if t is bool else "string") for k, t in FALLBACK_CLEAN_OPTIONS.items()}

    # 纯文本清理在引擎侧要求 Layer B 重写策略；用一次极小的探测问出是否配置了。
    # 引擎本身不可用时别再发探测，省得把首屏拖成十几个超时。
    layer_b = _probe_layer_b() if health.get("ok") else False

    return {
        "ok": bool(health.get("ok")),
        "web_version": WEB_VERSION,
        "core_version": health.get("version") or caps.get("version"),
        "capabilities": {
            "tools": caps.get("tools") or {},
            "pixel_backends": caps.get("pixel_backends") or {},
            "scorers": caps.get("scorers") or {},
            "text_detectors": caps.get("text_detectors") or {},
        },
        "clean_options": options,
        "limits": {
            "max_input": MAX_INPUT,
            "max_batch": MAX_BATCH,
            "deep_image_modes": list(DEEP_IMAGE_MODES),
        },
        "text_layer_b": layer_b,
        "llm": {
            "available": True,
            "tactics": list(LLM_TACTICS),
            "note": "Layer B 文本改写：配置随请求从浏览器传入，服务端不保存密钥",
        },
        "kinds": {
            "image": sorted(e.lstrip(".") for e in IMAGE_EXTS),
            "av": sorted(e.lstrip(".") for e in AV_EXTS),
            "container": sorted(e.lstrip(".") for e in CONTAINER_EXTS),
            "text": sorted(e.lstrip(".") for e in TEXT_EXTS),
        },
    }


def _probe_layer_b() -> bool:
    """引擎未配置重写后端时，纯文本 /clean 会 400 并点名 Layer B。

    配了重写后端时这个探测就是**一次真实的 LLM 调用**，所以结果单独长缓存：
    已配置 30 分钟，未配置 5 分钟（改完配置能较快看到）。
    """
    now = time.time()
    cached = _layer_b_cache["value"]
    if cached is not None and now - float(_layer_b_cache["at"]) < (
            _LAYER_B_TTL_OK if cached else _LAYER_B_TTL_NO):
        return bool(cached)
    payload = json.dumps({
        "file": base64.b64encode(b"probe text\n").decode("ascii"),
        "name": "probe.txt",
    }).encode()
    req = urllib.request.Request(f"{UPSTREAM}/clean", data=payload,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            ok = r.status == 200
            _layer_b_cache.update({"at": time.time(), "value": ok})
            return ok
    except urllib.error.HTTPError:
        # 纯文本没配 Layer B 时引擎会 400 并点名 Layer B；其它错误同样按未配置处理，
        # 免得把一个无关的 400 误报成可用。
        _layer_b_cache.update({"at": time.time(), "value": False})
        return False
    except Exception:  # noqa: BLE001
        return False


def main() -> int:
    global UPSTREAM
    p = argparse.ArgumentParser(description="水印清理工具 WebUI 服务")
    p.add_argument("--port", type=int, default=int(os.environ.get("WATERMARKS_WEB_PORT", "8770")))
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--upstream", default=UPSTREAM)
    args = p.parse_args()
    UPSTREAM = args.upstream.rstrip("/")

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    srv.daemon_threads = True
    try:
        print(f"界面已启动: http://{args.host}:{args.port}  (引擎 {UPSTREAM}, web {WEB_VERSION})", flush=True)
    except (AttributeError, ValueError, OSError):
        pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
