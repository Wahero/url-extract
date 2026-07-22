#!/usr/bin/env python3
"""
IMA OpenAPI Python 客户端 v1.2
仅从环境变量读取凭证，不持久化存储。

认证方式：环境变量 IMA_OPENAPI_CLIENTID / IMA_OPENAPI_APIKEY

v1.2 变更：移除文件持久化，仅从环境变量读取凭证；新增 Markdown 文件上传（四步流程）。
v1.1 新增：find_kb_by_name / search_knowledge_in_kb（知识库内容检索去重）
"""

import os
import json
import urllib.request
import urllib.error

DEFAULT_BASE_URL = "https://ima.qq.com"


def load_credentials() -> tuple:
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


def api_call(api_path: str, body: dict, base_url: str = DEFAULT_BASE_URL) -> dict:
    """调用 IMA OpenAPI，返回解析后的 JSON。"""
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
            raw = resp.read().decode("utf-8")
            result = json.loads(raw)
            return result
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"IMA API 请求失败 (HTTP {e.code}): {error_body}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"IMA API 网络错误: {e.reason}")


# ============================================================
# 知识库查询
# ============================================================

def get_addable_knowledge_bases() -> list:
    """获取可添加内容的知识库列表。"""
    resp = api_call(
        "openapi/wiki/v1/get_addable_knowledge_base_list",
        {"cursor": "", "limit": 20},
    )
    if resp.get("code") != 0:
        raise RuntimeError(f"获取知识库列表失败: {resp.get('msg', '未知错误')}")
    data = resp.get("data", {})
    return data.get("addable_knowledge_base_list") or data.get("knowledge_base_list") or []


def search_knowledge_base(query: str = "") -> list:
    """按名称搜索知识库。"""
    resp = api_call(
        "openapi/wiki/v1/search_knowledge_base",
        {"query": query, "cursor": "", "limit": 20},
    )
    if resp.get("code") != 0:
        raise RuntimeError(f"搜索知识库失败: {resp.get('msg', '未知错误')}")
    data = resp.get("data", {})
    raw_list = data.get("info_list") or data.get("knowledge_base_list") or []
    # 统一字段名：kb_id→id, kb_name→name
    result = []
    for kb in raw_list:
        normalized = {
            "id": kb.get("id") or kb.get("kb_id", ""),
            "name": kb.get("name") or kb.get("kb_name", ""),
        }
        normalized.update(kb)
        result.append(normalized)
    return result


def find_kb_by_name(name: str) -> dict | None:
    """按名称精确查找知识库，返回 {id, name, ...} 或 None。"""
    kb_list = search_knowledge_base(name)
    for kb in kb_list:
        if kb.get("name", "") == name:
            return kb
    for kb in get_addable_knowledge_bases():
        if kb.get("name", "") == name:
            return kb
    return None


def search_knowledge_in_kb(kb_id: str, query: str) -> list:
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

def import_url(kb_id: str, urls: list, folder_id: str = "") -> dict:
    """将网页 URL 导入知识库。"""
    body = {"knowledge_base_id": kb_id, "urls": urls}
    if folder_id:
        body["folder_id"] = folder_id
    return api_call("openapi/wiki/v1/import_urls", body)


# ============================================================
# 去重检查
# ============================================================

def _extract_title(item: dict) -> str:
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

def check_repeated_names(kb_id: str, file_names: list) -> dict:
    """检查知识库中是否已存在同名文件。"""
    return api_call(
        "openapi/wiki/v1/check_repeated_names",
        {
            "knowledge_base_id": kb_id,
            "names": file_names,
            "folder_id": "",
        },
    )


def create_media(kb_id: str, file_name: str, file_size: int,
                 content_type: str = "text/markdown",
                 file_ext: str = "md") -> dict:
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


def _cos_upload(credential: dict, file_data: bytes, content_type: str,
                cos_key: str, file_size: int) -> bool:
    """使用 COS 临时凭证上传文件到腾讯云对象存储。"""
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

    # COS 签名 v1
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


def add_knowledge_file(kb_id: str, media_id: str, cos_key: str,
                       file_name: str, file_size: int, title: str = "",
                       content_type: str = "text/markdown",
                       media_type: int = 7) -> dict:
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


def upload_markdown_to_kb(kb_id: str, file_name: str,
                          markdown_content: str) -> dict:
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

    # 步骤1：检查重名
    print(f"[IMA] 检查重名: {file_name}", file=sys.stderr)
    dup_resp = check_repeated_names(kb_id, [file_name])
    if dup_resp.get("code") == 0:
        dup_list = dup_resp.get("data", {}).get("repeated_name_list", [])
        if dup_list:
            print(f"[IMA] ⏭️ 文件已存在，跳过: {file_name}", file=sys.stderr)
            return {"skipped": True, "reason": "duplicate"}

    # 步骤2：创建媒体，获取 COS 凭证
    print(f"[IMA] 创建媒体资源...", file=sys.stderr)
    media_resp = create_media(kb_id, file_name, file_size, content_type, "md")
    if media_resp.get("code") != 0:
        raise RuntimeError(f"create_media 失败: {media_resp.get('msg', '未知错误')}")

    media_data = media_resp.get("data", {})
    media_id = media_data.get("media_id", "")
    credential = media_data.get("cos_credential", {})
    cos_key = credential.get("cos_key", "")

    if not media_id or not credential or not cos_key:
        raise RuntimeError(f"create_media 返回数据不完整: {json.dumps(media_data, ensure_ascii=False)[:300]}")

    # 步骤3：上传到 COS
    print(f"[IMA] 上传到 COS...", file=sys.stderr)
    ok = _cos_upload(credential, file_data, content_type, cos_key, file_size)
    if not ok:
        raise RuntimeError("COS 上传失败")

    # 步骤4：注册为知识库条目
    print(f"[IMA] 注册到知识库...", file=sys.stderr)
    title = file_name.rsplit(".", 1)[0] if "." in file_name else file_name
    result = add_knowledge_file(kb_id, media_id, cos_key, file_name, file_size, title=title, content_type=content_type)
    return result


if __name__ == "__main__":
    # 自检模式
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
