#!/usr/bin/env python3
"""
IMA OpenAPI Python 客户端 v1.4
仅从环境变量读取凭证，不持久化存储。

认证方式：环境变量 IMA_OPENAPI_CLIENTID / IMA_OPENAPI_APIKEY

v1.4 变更：
  - api_call() 加 tenacity 重试（网络错误 / HTTP 5xx 自动重试 3 次，指数退避）
  - 所有公开函数加类型注解
  - ImaAPIRetryableError / ImaAPIBusinessError 异常类区分可重试 / 不可重试错误
  - 通过 IMA_API_RETRY / IMA_API_BACKOFF 环境变量可调重试参数
v1.3 变更：COS 上传「SDK 优先 + Legacy 兜底」双实现
v1.2 变更：移除文件持久化，仅从环境变量读取凭证；新增 Markdown 文件上传（四步流程）
v1.1 新增：find_kb_by_name / search_knowledge_in_kb（知识库内容检索去重）
"""

import os
import json
import warnings
import urllib.request
import urllib.error
from typing import Any

try:
    from tenacity import (
        retry,
        stop_after_attempt,
        wait_exponential,
        retry_if_exception,
    )
    _HAS_TENACITY = True
except ImportError:
    _HAS_TENACITY = False

DEFAULT_BASE_URL = "https://ima.qq.com"


# -------------------------------------------------------------------
# 异常类
# -------------------------------------------------------------------

class ImaAPIRetryableError(Exception):
    """IMA API 可重试错误（网络错误 / 5xx 服务端错误）。"""


class ImaAPIBusinessError(Exception):
    """IMA API 业务错误（4xx / 业务 code != 0）——不重试。"""


# -------------------------------------------------------------------
# 重试逻辑
# -------------------------------------------------------------------

def _is_retryable(exc: BaseException) -> bool:
    """判断异常是否可重试。

    注意：HTTPError 是 URLError 的子类，HTTPError 检查必须放在 URLError 前面，
    否则所有 HTTPError（4xx/5xx）都会被 URLError 分支捕获而全部重试。

    只对以下情况重试：
      - ImaAPIRetryableError（显式标记的可重试错误）
      - HTTPError 5xx（服务端错误，瞬时失败居多）
      - URLError（网络错误：DNS / 连接失败 / 超时）
    不重试：
      - HTTPError 4xx（客户端错误，重试无意义）
      - ImaAPIBusinessError（业务错误，code != 0）
      - 其他 RuntimeError
    """
    if isinstance(exc, ImaAPIRetryableError):
        return True
    if isinstance(exc, urllib.error.HTTPError):
        # HTTPError 是 URLError 子类，必须先于 URLError 检查
        return 500 <= exc.code < 600
    if isinstance(exc, urllib.error.URLError):
        return True
    return False


def _log_retry(info) -> None:
    """重试前的日志回调，打印到 stderr 让用户知道发生了什么。"""
    import sys as _sys
    exc = info.outcome.exception() if info.outcome else None
    exc_name = exc.__class__.__name__ if exc else "Unknown"
    _sys.stderr.write(
        "[IMA] API 失败 (attempt " + str(info.fn.__name__) + " #" + str(info.attempt_number) + "), "
        + str(exc_name) + ", " + str(round(info.idle_for, 1)) + "s 后重试...\n"
    )
    _sys.stderr.flush()


def _api_retry():
    """tenacity 重试装饰器工厂。

    配置：
      - 3 次尝试（默认，可通过 IMA_API_RETRY 环境变量调整）
      - 指数退避 1s/2s/4s（最小 1s，最大 10s）
      - 只对网络/5xx 重试（_is_retryable 判定）
      - 重试前打印提示，让用户知道发生了什么

    通过环境变量调整：
      - IMA_API_RETRY：最大重试次数（默认 3）
      - IMA_API_BACKOFF：基础退避秒数（默认 1）
    """
    max_attempts = int(os.environ.get("IMA_API_RETRY", "3"))
    base = float(os.environ.get("IMA_API_BACKOFF", "1"))
    if not _HAS_TENACITY:
        def decorator(fn):
            return fn
        return decorator
    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=base, min=base, max=10),
        retry=retry_if_exception(_is_retryable),
        reraise=True,
        before_sleep=_log_retry,
    )


# -------------------------------------------------------------------
# 凭证加载
# -------------------------------------------------------------------

def load_credentials() -> tuple[str, str]:
    """
    从环境变量加载 IMA 凭证，返回 (client_id, api_key)。
    不读取文件，不持久化存储。
    """
    client_id = os.environ.get("IMA_OPENAPI_CLIENTID") or os.environ.get("IMA_CLIENT_ID")
    api_key = os.environ.get("IMA_OPENAPI_APIKEY") or os.environ.get("IMA_API_KEY")
    if not client_id or not api_key:
        raise RuntimeError(
            "未找到 IMA 凭证。请设置环境变量：\n"
            "  export IMA_OPENAPI_CLIENTID=\"你的ClientID\"\n"
            "  export IMA_OPENAPI_APIKEY=\"你的APIKey\"\n"
            "获取地址: https://ima.qq.com/agent-interface"
        )
    return client_id, api_key


# -------------------------------------------------------------------
# API 调用（带重试）
# -------------------------------------------------------------------

@_api_retry()
def api_call(api_path: str, body: dict, base_url: str = DEFAULT_BASE_URL) -> dict:
    """调用 IMA OpenAPI，返回解析后的 JSON。

    重试行为：
      - 网络错误（URLError：DNS/连接/超时）→ 自动重试 3 次
      - 服务端 5xx → 自动重试 3 次
      - 业务错误（4xx / 业务 code != 0）→ 抛 ImaAPIBusinessError，不重试
      - 凭证缺失 → 抛 RuntimeError，不重试

    通过环境变量调整：
      - IMA_API_RETRY：最大重试次数（默认 3）
      - IMA_API_BACKOFF：基础退避秒数（默认 1）
    """
    client_id, api_key = load_credentials()

    url = f"{base_url}/{api_path}"
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "ima-openapi-clientid": client_id,
            "ima-openapi-apikey": api_key,
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # HTTPError.read() 在 Python 3 有时不返回 bytes（只返回 str body）。
        # 错误消息对调试有帮助，但不是核心逻辑，只打印到 stderr 方便排查。
        try:
            error_body = e.read().decode("utf-8", errors="replace")
        except Exception:
            error_body = ""
        if 500 <= e.code < 600:
            raise ImaAPIRetryableError(
                f"IMA API 服务端错误 (HTTP {e.code})"
            ) from e
        raise ImaAPIBusinessError(
            f"IMA API 客户端错误 (HTTP {e.code})"
        ) from e
    except urllib.error.URLError as e:
        raise ImaAPIRetryableError(f"IMA API 网络错误: {e.reason}") from e


# ============================================================
# 知识库查询
# ============================================================

def get_addable_knowledge_bases() -> list[dict[str, Any]]:
    """获取可添加内容的知识库列表。"""
    resp = api_call(
        "openapi/wiki/v1/get_addable_knowledge_base_list",
        {"cursor": "", "limit": 20},
    )
    if resp.get("code") != 0:
        raise RuntimeError(f"获取知识库列表失败: {resp.get('msg', '未知错误')}")
    data = resp.get("data", {})
    return data.get("addable_knowledge_base_list") or data.get("knowledge_base_list") or []


def search_knowledge_base(query: str = "") -> list[dict[str, Any]]:
    """按名称搜索知识库。"""
    resp = api_call(
        "openapi/wiki/v1/search_knowledge_base",
        {"query": query, "cursor": "", "limit": 20},
    )
    if resp.get("code") != 0:
        raise RuntimeError(f"搜索知识库失败: {resp.get('msg', '未知错误')}")
    data = resp.get("data", {})
    raw_list = data.get("info_list") or data.get("knowledge_base_list") or []
    result = []
    for kb in raw_list:
        normalized = {
            "id": kb.get("id") or kb.get("kb_id", ""),
            "name": kb.get("name") or kb.get("kb_name", ""),
        }
        normalized.update(kb)
        result.append(normalized)
    return result


def find_kb_by_name(name: str) -> dict[str, Any] | None:
    """按名称精确查找知识库，返回 {id, name, ...} 或 None。"""
    kb_list = search_knowledge_base(name)
    for kb in kb_list:
        if kb.get("name", "") == name:
            return kb
    for kb in get_addable_knowledge_bases():
        if kb.get("name", "") == name:
            return kb
    return None


def search_knowledge_in_kb(kb_id: str, query: str) -> list[dict[str, Any]]:
    """搜索知识库中的内容，返回 knowledge_list。失败时返回空列表不抛异常。"""
    try:
        resp = api_call(
            "openapi/wiki/v1/search_knowledge",
            {"knowledge_base_id": kb_id, "query": query, "cursor": "", "limit": 20},
        )
        if resp.get("code") != 0:
            return []
        return resp.get("data", {}).get("knowledge_list", [])
    except Exception:
        return []


# ============================================================
# URL 导入
# ============================================================

def import_url(kb_id: str, urls: list[str], folder_id: str = "") -> dict[str, Any]:
    """将网页 URL 导入知识库。"""
    body: dict[str, Any] = {"knowledge_base_id": kb_id, "urls": urls}
    if folder_id:
        body["folder_id"] = folder_id
    return api_call("openapi/wiki/v1/import_urls", body)


# ============================================================
# 去重检查
# ============================================================

def _extract_title(item: dict[str, Any]) -> str:
    """从知识库搜索结果项中提取标题。"""
    return (
        item.get("title", "")
        or item.get("media_info", {}).get("title", "")
        or item.get("media_info", {}).get("file_name", "")
        or ""
    )


def check_duplicate(kb_id: str, title: str, url: str = "") -> bool:
    """检查知识库中是否已存在同名或同URL内容。返回 True 表示重复。"""
    items = search_knowledge_in_kb(kb_id, title)
    for item in items:
        item_title = _extract_title(item)
        if item_title and title in item_title:
            return True
        if url:
            item_url = item.get("url", "") or item.get("media_info", {}).get("url", "")
            if item_url and url in item_url:
                return True
    return False


def check_connection() -> bool:
    """检查 IMA API 连接和凭证是否有效。"""
    try:
        resp = api_call(
            "openapi/wiki/v1/get_addable_knowledge_base_list",
            {"cursor": "", "limit": 1},
        )
        return resp.get("code") == 0
    except Exception:
        return False


# ============================================================
# Markdown 文件上传（四步流程）
# check_repeated_names → create_media → COS upload → add_knowledge
# ============================================================

def check_repeated_names(kb_id: str, file_names: list[str]) -> dict[str, Any]:
    """检查知识库中是否已存在同名文件。"""
    return api_call(
        "openapi/wiki/v1/check_repeated_names",
        {
            "knowledge_base_id": kb_id,
            "names": file_names,
            "folder_id": "",
        },
    )


def create_media(
    kb_id: str,
    file_name: str,
    file_size: int,
    content_type: str = "text/markdown",
    file_ext: str = "md",
) -> dict[str, Any]:
    """创建媒体资源，获取 COS 上传凭证。"""
    return api_call(
        "openapi/wiki/v1/create_media",
        {
            "knowledge_base_id": kb_id,
            "file_name": file_name,
            "file_size": file_size,
            "content_type": content_type,
            "file_ext": file_ext,
        },
    )


def _cos_upload_sdk(
    credential: dict[str, Any],
    file_data: bytes,
    content_type: str,
    cos_key: str,
    file_size: int,
) -> bool:
    """使用 cos-python-sdk-v5 上传（推荐）。需要 pip install cos-python-sdk-v5。"""
    try:
        from qcloud_cos import CosConfig, CosS3Client
    except ImportError as e:
        raise RuntimeError(
            "需要 cos-python-sdk-v5: pip install cos-python-sdk-v5"
        ) from e

    secret_id = credential.get("secret_id", "")
    secret_key = credential.get("secret_key", "")
    token = credential.get("token", "")
    bucket = credential.get("bucket_name") or credential.get("bucket", "")
    region = credential.get("region", "")

    config = CosConfig(
        Region=region,
        SecretId=secret_id,
        SecretKey=secret_key,
        Token=token,
        Scheme="https",
    )
    client = CosS3Client(config)

    response = client.put_object(
        Bucket=bucket,
        Key=cos_key,
        Body=file_data,
        ContentType=content_type,
        ContentLength=file_size,
    )
    status = getattr(response, "status_code", None) or response.get("status_code")
    return status in (200, 204)


def _cos_upload_legacy_v1(
    credential: dict[str, Any],
    file_data: bytes,
    content_type: str,
    cos_key: str,
    file_size: int,
) -> bool:
    """手写 COS 签名 v1 算法（无 SDK 依赖的 fallback）。

    .. deprecated::
        请安装 ``cos-python-sdk-v5`` 并改用 ``_cos_upload_sdk``（或
        ``_cos_upload(..., prefer='auto')`` 自动选择）。此函数将在 v2.7 移除。
    """
    warnings.warn(
        "_cos_upload_legacy_v1 已废弃，请安装 cos-python-sdk-v5 走 _cos_upload_sdk。"
        "此函数将在 v2.7 移除。",
        DeprecationWarning,
        stacklevel=2,
    )
    import time
    import hmac
    import hashlib
    import urllib.parse as _urlparse

    secret_id = credential.get("secret_id", "")
    secret_key = credential.get("secret_key", "")
    token = credential.get("token", "")
    bucket = credential.get("bucket_name") or credential.get("bucket", "")
    region = credential.get("region", "")

    cos_host = f"{bucket}.cos.{region}.myqcloud.com"
    upload_url = f"https://{cos_host}/{cos_key}"

    timestamp = int(time.time())
    expired = 600
    key_time = f"{timestamp};{timestamp + expired}"

    sign_key = hmac.new(secret_key.encode(), key_time.encode(), hashlib.sha1).hexdigest()

    http_method = "put"
    http_uri = f"/{cos_key}"
    http_parameters = ""
    encoded_ct = _urlparse.quote(content_type, safe='')
    http_headers = f"content-type={encoded_ct}&host={cos_host.lower()}"
    header_list = "content-type;host"
    format_string = f"{http_method}\n{http_uri}\n{http_parameters}\n{http_headers}\n"

    sha1_format = hashlib.sha1(format_string.encode()).hexdigest()
    string_to_sign = f"sha1\n{key_time}\n{sha1_format}\n"

    signature = hmac.new(sign_key.encode(), string_to_sign.encode(), hashlib.sha1).hexdigest()

    authorization = (
        f"q-sign-algorithm=sha1"
        f"&q-ak={secret_id}"
        f"&q-sign-time={key_time}"
        f"&q-key-time={key_time}"
        f"&q-header-list={header_list}"
        f"&q-url-param-list="
        f"&q-signature={signature}"
    )

    req = urllib.request.Request(
        upload_url,
        data=file_data,
        headers={
            "Content-Type": content_type,
            "Authorization": authorization,
            "x-cos-security-token": token,
            "Content-Length": str(file_size),
        },
        method="PUT",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"COS 上传失败 (HTTP {e.code}): {error_body}")


def _cos_upload(
    credential: dict[str, Any],
    file_data: bytes,
    content_type: str,
    cos_key: str,
    file_size: int,
    prefer: str = "auto",
) -> bool:
    """COS 上传分发（prefer: auto/sdk/legacy）。"""
    if prefer == "legacy":
        return _cos_upload_legacy_v1(credential, file_data, content_type, cos_key, file_size)
    if prefer == "sdk":
        return _cos_upload_sdk(credential, file_data, content_type, cos_key, file_size)
    try:
        import qcloud_cos  # noqa: F401
    except ImportError:
        return _cos_upload_legacy_v1(credential, file_data, content_type, cos_key, file_size)
    return _cos_upload_sdk(credential, file_data, content_type, cos_key, file_size)


def add_knowledge_file(
    kb_id: str,
    media_id: str,
    cos_key: str,
    file_name: str,
    file_size: int,
    title: str = "",
    content_type: str = "text/markdown",
    media_type: int = 7,
) -> dict[str, Any]:
    """将已上传的文件注册为知识库条目。"""
    import time
    return api_call(
        "openapi/wiki/v1/add_knowledge",
        {
            "knowledge_base_id": kb_id,
            "media_type": media_type,
            "media_id": media_id,
            "title": title or file_name,
            "file_info": {
                "cos_key": cos_key,
                "file_size": file_size,
                "file_name": file_name,
                "last_modify_time": int(time.time()),
            },
        },
    )


def upload_markdown_to_kb(
    kb_id: str,
    file_name: str,
    markdown_content: str,
) -> dict[str, Any]:
    """
    将 Markdown 内容上传到 IMA 知识库。
    四步流程：check_repeated → create_media → COS upload → add_knowledge

    Returns:
        dict: add_knowledge 的响应，或 {"skipped": True} 表示重复跳过
    """
    import sys

    file_data = markdown_content.encode("utf-8")
    file_size = len(file_data)
    content_type = "text/markdown"

    print(f"[IMA] 检查重名: {file_name}", file=sys.stderr)
    dup_resp = check_repeated_names(kb_id, [file_name])
    if dup_resp.get("code") == 0:
        dup_list = dup_resp.get("data", {}).get("repeated_name_list", [])
        if dup_list:
            print(f"[IMA] ⏭️ 文件已存在，跳过: {file_name}", file=sys.stderr)
            return {"skipped": True, "reason": "duplicate"}

    print(f"[IMA] 创建媒体资源...", file=sys.stderr)
    media_resp = create_media(kb_id, file_name, file_size, content_type, "md")
    if media_resp.get("code") != 0:
        raise RuntimeError(f"create_media 失败: {media_resp.get('msg', '未知错误')}")

    media_data = media_resp.get("data", {})
    media_id = media_data.get("media_id", "")
    credential = media_data.get("cos_credential", {})
    cos_key = credential.get("cos_key", "")

    if not media_id or not credential or not cos_key:
        raise RuntimeError(
            f"create_media 返回数据不完整: {json.dumps(media_data, ensure_ascii=False)[:300]}"
        )

    print(f"[IMA] 上传到 COS...", file=sys.stderr)
    ok = _cos_upload(credential, file_data, content_type, cos_key, file_size)
    if not ok:
        raise RuntimeError("COS 上传失败")

    print(f"[IMA] 注册到知识库...", file=sys.stderr)
    title = file_name.rsplit(".", 1)[0] if "." in file_name else file_name
    result = add_knowledge_file(
        kb_id, media_id, cos_key, file_name, file_size, title=title, content_type=content_type
    )
    return result


if __name__ == "__main__":
    print("IMA Client 自检...")
    try:
        client_id, api_key = load_credentials()
        cid_display = client_id[:8] + "****" if len(client_id) > 8 else "****"
        print(f"  凭证: client_id={cid_display}, api_key=****")
        if check_connection():
            print("  连接: OK")
            kb_list = search_knowledge_base()
            print(f"  知识库: {len(kb_list)} 个")
        else:
            print("  连接: 失败")
    except RuntimeError as e:
        print(f"  错误: {e}")
