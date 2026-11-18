"""Project-local model settings. Secrets never appear in public settings responses."""
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit

DEFAULT_BASE_URL = "https://api.openai.com/v1"
ENV_KEYS = {"LLM_API_KEY", "LLM_MODEL", "LLM_BASE_URL", "LLM_API_STYLE", "SHIP24_API_KEY"}
MODEL_ENV_KEYS = {"LLM_API_KEY", "LLM_MODEL", "LLM_BASE_URL", "LLM_API_STYLE"}
SETTING_KEYS = {"api_key", "model", "base_url", "api_style"}


def load_local_config(path, environ=None):
    """Read this project's optional file without replacing explicit process settings."""
    environ = os.environ if environ is None else environ
    path = Path(path)
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key in ENV_KEYS:
            environ.setdefault(key, value.strip().strip('"').strip("'"))


def _base_url(value):
    if not isinstance(value, str) or any(ord(c) < 33 or ord(c) >= 127 for c in value) or any(c in value for c in "?#\\\"'"):
        raise ValueError("接口地址请填写完整的 HTTPS 地址。")
    value = value.rstrip("/")
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme == "https" and bool(parsed.hostname) and
                 parsed.username is None and parsed.password is None and
                 not parsed.query and not parsed.fragment and parsed.port != 0)
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("接口地址应为 HTTPS，且不能包含用户名、密码、查询参数或片段。")
    # Host/scheme spelling should not require entering the same key again.
    return "https://" + parsed.netloc.lower() + parsed.path


def model_settings(environ=None):
    environ = os.environ if environ is None else environ
    base = environ.get("LLM_BASE_URL") or DEFAULT_BASE_URL
    model = environ.get("LLM_MODEL", "")
    key_present = bool(environ.get("LLM_API_KEY", ""))
    try:
        host = urlsplit(base).hostname or "自定义接口"
    except ValueError:
        host = "自定义接口"
    return {"configured": bool(key_present and model), "has_api_key": key_present,
            "model": model, "base_url": base,
            "api_style": environ.get("LLM_API_STYLE") or "responses",
            "provider": "OpenAI" if host == "api.openai.com" else host}


def save_model_settings(path, body, environ=None):
    """Validate, atomically save with owner-only permissions, then apply immediately."""
    environ = os.environ if environ is None else environ
    if not isinstance(body, dict) or set(body) - SETTING_KEYS:
        raise ValueError("模型配置字段无效。")
    for key, value in body.items():
        if not isinstance(value, str) or len(value) > 4096 or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("模型配置请使用单行文本。")
    model = body.get("model", "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/+\-]{0,199}", model):
        raise ValueError("请填写有效的模型名称，例如服务商提供的模型 ID。")
    base = _base_url(body.get("base_url") or DEFAULT_BASE_URL)
    style = body.get("api_style") or "responses"
    if style not in {"responses", "chat_completions"}:
        raise ValueError("接口格式请选择 Responses 或 Chat Completions。")
    key = body.get("api_key", "").strip()
    if key and (len(key) > 2048 or not re.fullmatch(r"[!-~]+", key) or any(c in key for c in "\"'\\")):
        raise ValueError("API Key 格式无效，请重新粘贴。")
    if not key:
        try:
            unchanged_endpoint = _base_url(environ.get("LLM_BASE_URL") or DEFAULT_BASE_URL) == base
        except ValueError:
            unchanged_endpoint = False
        if not unchanged_endpoint and environ.get("LLM_API_KEY"):
            raise ValueError("更换接口地址时，请重新填写该服务商的 API Key。")
        key = environ.get("LLM_API_KEY", "") if unchanged_endpoint else ""
    if not key:
        raise ValueError("请填写语言模型服务商的 API Key。")
    updated = {"LLM_API_KEY": key, "LLM_MODEL": model, "LLM_BASE_URL": base, "LLM_API_STYLE": style}
    path = Path(path)
    existing = path.read_text().splitlines() if path.exists() else []
    retained = [line for line in existing if "=" not in line or
                line.lstrip().startswith("#") or line.split("=", 1)[0].strip() not in MODEL_ENV_KEYS]
    content = "\n".join(retained + [name + "=" + updated[name] for name in
                          ["LLM_API_KEY", "LLM_MODEL", "LLM_BASE_URL", "LLM_API_STYLE"]]) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        # The .env.* ignore rule also protects a temporary file if the process stops.
        fd, temporary = tempfile.mkstemp(prefix=".env.model-settings-", dir=str(path.parent))
        with os.fdopen(fd, "w") as output:
            os.chmod(temporary, 0o600)
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)
    environ.update(updated)
    return model_settings(environ)
