"""ima_client 单元测试 — 主要测试 COS 上传分发逻辑。"""
import sys
from pathlib import Path
from unittest import mock

import pytest  # noqa: F401  # for pytest.raises in v1.5 tests below

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import ima_client  # noqa: E402

CRED = {
    "secret_id": "AKIDxxx",
    "secret_key": "SECRETxxx",
    "token": "TOKENxxx",
    "bucket_name": "example-bucket-12345",
    "region": "ap-guangzhou",
}
COS_KEY = "path/to/file.md"
FILE_DATA = b"hello world"
CT = "text/markdown"
SIZE = len(FILE_DATA)


def test_cos_upload_auto_falls_back_to_legacy_without_sdk():
    """auto 模式：qcloud_cos 没装时走 legacy v1。"""
    with mock.patch.dict(sys.modules, {"qcloud_cos": None}):
        # 强制 ImportError
        original_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__

        def fake_import(name, *args, **kwargs):
            if name == "qcloud_cos":
                raise ImportError("mocked")
            return original_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=fake_import):
            with mock.patch.object(ima_client, "_cos_upload_legacy_v1", return_value=True) as m_legacy:
                with mock.patch.object(ima_client, "_cos_upload_sdk") as m_sdk:
                    ok = ima_client._cos_upload(CRED, FILE_DATA, CT, COS_KEY, SIZE, prefer="auto")
                    assert ok is True
                    m_legacy.assert_called_once()
                    m_sdk.assert_not_called()


def test_cos_upload_auto_uses_sdk_when_available():
    """auto 模式：qcloud_cos 装了走 SDK。"""
    fake_module = mock.MagicMock()
    with mock.patch.dict(sys.modules, {"qcloud_cos": fake_module}):
        with mock.patch.object(ima_client, "_cos_upload_sdk", return_value=True) as m_sdk:
            with mock.patch.object(ima_client, "_cos_upload_legacy_v1") as m_legacy:
                ok = ima_client._cos_upload(CRED, FILE_DATA, CT, COS_KEY, SIZE, prefer="auto")
                assert ok is True
                m_sdk.assert_called_once()
                m_legacy.assert_not_called()


def test_cos_upload_legacy_prefer():
    """prefer=legacy 强制走 legacy，不管 SDK 是否装。"""
    fake_module = mock.MagicMock()
    with mock.patch.dict(sys.modules, {"qcloud_cos": fake_module}):
        with mock.patch.object(ima_client, "_cos_upload_legacy_v1", return_value=True) as m_legacy:
            with mock.patch.object(ima_client, "_cos_upload_sdk") as m_sdk:
                ok = ima_client._cos_upload(CRED, FILE_DATA, CT, COS_KEY, SIZE, prefer="legacy")
                assert ok is True
                m_legacy.assert_called_once()
                m_sdk.assert_not_called()


def test_cos_upload_sdk_prefer_raises_without_install():
    """prefer=sdk 但 SDK 没装 → 报错。"""
    original_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__

    def fake_import(name, *args, **kwargs):
        if name == "qcloud_cos":
            raise ImportError("mocked not installed")
        return original_import(name, *args, **kwargs)

    with mock.patch("builtins.__import__", side_effect=fake_import):
        try:
            ima_client._cos_upload(CRED, FILE_DATA, CT, COS_KEY, SIZE, prefer="sdk")
            assert False, "应该抛 RuntimeError"
        except RuntimeError as e:
            assert "cos-python-sdk-v5" in str(e)


def test_credentials_missing_raises():
    """凭证缺失时 load_credentials 抛 RuntimeError。"""
    with mock.patch.dict("os.environ", {}, clear=True):
        try:
            ima_client.load_credentials()
            assert False, "应该抛 RuntimeError"
        except RuntimeError as e:
            assert "IMA_OPENAPI_CLIENTID" in str(e)


def test_credentials_fallback_legacy_env_names():
    """支持旧版 IMA_CLIENT_ID / IMA_API_KEY 环境变量名。"""
    with mock.patch.dict("os.environ", {
        "IMA_CLIENT_ID": "legacy_id",
        "IMA_API_KEY": "legacy_key",
    }, clear=True):
        cid, key = ima_client.load_credentials()
        assert cid == "legacy_id"
        assert key == "legacy_key"


def test_legacy_cos_upload_emits_deprecation_warning():
    """_cos_upload_legacy_v1 调用时触发 DeprecationWarning。"""
    with mock.patch("urllib.request.urlopen") as m_urlopen:
        # mock urllib.urlopen 返回 200
        m_resp = mock.MagicMock()
        m_resp.status = 200
        m_resp.__enter__ = mock.MagicMock(return_value=m_resp)
        m_resp.__exit__ = mock.MagicMock(return_value=False)
        m_urlopen.return_value = m_resp

        import warnings
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            ok = ima_client._cos_upload_legacy_v1(
                CRED, FILE_DATA, CT, COS_KEY, SIZE,
            )
            assert ok is True
            assert any(
                issubclass(warning.category, DeprecationWarning)
                and "cos-python-sdk-v5" in str(warning.message)
                for warning in w
            ), "应该触发 DeprecationWarning 并提示迁移到 SDK"


# ============================================================
# v1.5 新增接口测试（2026-09-02 升级）
# 覆盖 10 个新函数：KB 读接口（4）+ 笔记 API（6）
# ============================================================


def test_get_knowledge_base_calls_correct_path():
    """get_knowledge_base 转发到 openapi/wiki/v1/get_knowledge_base。"""
    with mock.patch.object(ima_client, "api_call", return_value={"code": 0, "data": {}}) as m_call:
        result = ima_client.get_knowledge_base(["kb_id_1", "kb_id_2"])
        m_call.assert_called_once_with(
            "openapi/wiki/v1/get_knowledge_base",
            {"ids": ["kb_id_1", "kb_id_2"]},
        )
        assert result == {"code": 0, "data": {}}


def test_get_knowledge_base_rejects_invalid_count():
    """get_knowledge_base 限制 1-20 个 ID（空数组和 21 个都拒绝）。"""
    with mock.patch.object(ima_client, "api_call") as m_call:
        with pytest.raises(ValueError, match="1-20"):
            ima_client.get_knowledge_base([])
        with pytest.raises(ValueError, match="1-20"):
            ima_client.get_knowledge_base(["x"] * 21)
        m_call.assert_not_called()


def test_get_knowledge_list_omits_folder_id_when_empty():
    """get_knowledge_list 根目录时省略 folder_id（不传该参数）。"""
    with mock.patch.object(ima_client, "api_call", return_value={"data": {}}) as m_call:
        ima_client.get_knowledge_list("kb_1")
        args = m_call.call_args
        assert args[0][0] == "openapi/wiki/v1/get_knowledge_list"
        body = args[0][1]
        assert body["knowledge_base_id"] == "kb_1"
        assert body["cursor"] == ""
        assert body["limit"] == 50
        assert "folder_id" not in body


def test_get_knowledge_list_includes_folder_id_when_set():
    """get_knowledge_list 指定文件夹时传 folder_id。"""
    with mock.patch.object(ima_client, "api_call", return_value={"data": {}}) as m_call:
        ima_client.get_knowledge_list("kb_1", folder_id="folder_123", cursor="abc=", limit=20)
        body = m_call.call_args[0][1]
        assert body["folder_id"] == "folder_123"
        assert body["cursor"] == "abc="
        assert body["limit"] == 20


def test_get_knowledge_list_validates_limit():
    """get_knowledge_list 限制 limit 1-50。"""
    with mock.patch.object(ima_client, "api_call") as m_call:
        with pytest.raises(ValueError, match="1-50"):
            ima_client.get_knowledge_list("kb_1", limit=0)
        with pytest.raises(ValueError, match="1-50"):
            ima_client.get_knowledge_list("kb_1", limit=51)
        m_call.assert_not_called()


def test_get_media_info_calls_correct_path():
    """get_media_info 转发到 openapi/wiki/v1/get_media_info。"""
    with mock.patch.object(ima_client, "api_call", return_value={"data": {"url_info": {}}}) as m_call:
        result = ima_client.get_media_info("pdf_xxx")
        m_call.assert_called_once_with(
            "openapi/wiki/v1/get_media_info",
            {"media_id": "pdf_xxx"},
        )
        assert result == {"data": {"url_info": {}}}


def test_download_kb_file_uses_url_and_headers():
    """download_kb_file 自动用 url_info.url + url_info.headers GET 文件。"""
    fake_info = {
        "data": {
            "url_info": {
                "url": "https://example.com/file.pdf",
                "headers": {
                    "X-IMA-Sign": "abc123",
                    "X-IMA-Platform": "H5",
                },
            }
        }
    }
    with mock.patch.object(ima_client, "get_media_info", return_value=fake_info):
        with mock.patch("urllib.request.urlopen") as m_urlopen:
            m_resp = mock.MagicMock()
            m_resp.read.return_value = b"%PDF-1.4 fake content"
            m_resp.__enter__ = mock.MagicMock(return_value=m_resp)
            m_resp.__exit__ = mock.MagicMock(return_value=False)
            m_urlopen.return_value = m_resp

            data, url_info = ima_client.download_kb_file("pdf_xxx")

            assert data == b"%PDF-1.4 fake content"
            assert url_info["url"] == "https://example.com/file.pdf"

            # 验证请求带上了 url_info.headers
            req = m_urlopen.call_args[0][0]
            # urllib.Request 把 header name capitalize 化（首字母大写其余小写）：
            # 'X-IMA-Sign' → 'X-ima-sign'
            header_dict = {k.lower(): v for k, v in req.headers.items()}
            assert header_dict.get("x-ima-sign") == "abc123", \
                f"X-IMA-Sign 应被带上，实际 headers: {header_dict}"
            assert header_dict.get("x-ima-platform") == "H5"
            assert req.get_full_url() == "https://example.com/file.pdf"


def test_download_kb_file_raises_when_no_url():
    """download_kb_file 在 url 为空时抛 RuntimeError。"""
    with mock.patch.object(ima_client, "get_media_info", return_value={"data": {"url_info": {}}}):
        with pytest.raises(RuntimeError, match="url_info 为空"):
            ima_client.download_kb_file("pdf_empty")


def test_search_note_title_mode():
    """search_note search_type=0 走 title 查询。"""
    with mock.patch.object(ima_client, "api_call", return_value={"data": {}}) as m_call:
        ima_client.search_note("会议纪要", search_type=0)
        args = m_call.call_args
        assert args[0][0] == "openapi/note/v1/search_note"
        body = args[0][1]
        assert body["search_type"] == 0
        assert body["query_info"] == {"title": "会议纪要"}
        assert body["start"] == 0
        assert body["end"] == 20


def test_search_note_content_mode():
    """search_note search_type=1 走 content 查询，支持分页。"""
    with mock.patch.object(ima_client, "api_call", return_value={"data": {}}) as m_call:
        ima_client.search_note("项目排期", search_type=1, start=20, end=40)
        body = m_call.call_args[0][1]
        assert body["search_type"] == 1
        assert body["query_info"] == {"content": "项目排期"}
        assert body["start"] == 20
        assert body["end"] == 40


def test_search_note_rejects_invalid_type():
    """search_type 只能是 0 或 1。"""
    with mock.patch.object(ima_client, "api_call"):
        with pytest.raises(ValueError, match="0 或 1"):
            ima_client.search_note("x", search_type=2)


def test_list_notebook_default_cursor():
    """list_notebook 默认 cursor='0'（官方明示首次必须传 '0'）。"""
    with mock.patch.object(ima_client, "api_call", return_value={"data": {}}) as m_call:
        ima_client.list_notebook()
        body = m_call.call_args[0][1]
        assert body["cursor"] == "0"
        assert body["limit"] == 20
        assert m_call.call_args[0][0] == "openapi/note/v1/list_notebook"


def test_list_note_default_folder_id_empty():
    """list_note 默认 folder_id=''（全部笔记）。"""
    with mock.patch.object(ima_client, "api_call", return_value={"data": {}}) as m_call:
        ima_client.list_note()
        body = m_call.call_args[0][1]
        assert body["folder_id"] == ""
        assert body["sort_type"] == 0
        assert body["cursor"] == ""
        assert body["limit"] == 20


def test_get_doc_content_default_format():
    """get_doc_content 默认 content_format=0（纯文本，文档明示 Markdown 不支持）。"""
    with mock.patch.object(ima_client, "api_call", return_value={"data": {}}) as m_call:
        ima_client.get_doc_content("note_1")
        body = m_call.call_args[0][1]
        assert body["note_id"] == "note_1"
        assert body["target_content_format"] == 0
        assert m_call.call_args[0][0] == "openapi/note/v1/get_doc_content"


def test_import_doc_accepts_valid_utf8():
    """import_doc 接受合法 UTF-8 内容。"""
    with mock.patch.object(ima_client, "api_call", return_value={"data": {"note_id": "n1"}}) as m_call:
        result = ima_client.import_doc("# 中文笔记\n内容")
        m_call.assert_called_once()
        body = m_call.call_args[0][1]
        assert body["content"] == "# 中文笔记\n内容"
        assert body["content_format"] == 1
        assert result == {"data": {"note_id": "n1"}}


def test_import_doc_validates_utf8():
    """import_doc 拒绝非 UTF-8（surrogate）内容 — 强制安全门。"""
    with mock.patch.object(ima_client, "api_call") as m_call:
        # 含 surrogate half-character 的字符串无法 roundtrip UTF-8
        with pytest.raises(ValueError, match="UTF-8"):
            ima_client.import_doc("bad \udcff text")
        m_call.assert_not_called()


def test_import_doc_includes_folder_id_when_set():
    """import_doc 传 folder_id 时包含在 body。"""
    with mock.patch.object(ima_client, "api_call", return_value={"data": {}}) as m_call:
        ima_client.import_doc("# x", folder_id="folder_1")
        body = m_call.call_args[0][1]
        assert body["folder_id"] == "folder_1"


def test_append_doc_calls_correct_path():
    """append_doc 转发到 openapi/note/v1/append_doc。"""
    with mock.patch.object(ima_client, "api_call", return_value={"data": {}}) as m_call:
        ima_client.append_doc("note_1", "## 追加内容")
        m_call.assert_called_once_with(
            "openapi/note/v1/append_doc",
            {
                "note_id": "note_1",
                "content_format": 1,
                "content": "## 追加内容",
            },
        )


def test_append_doc_validates_utf8():
    """append_doc 同样拒绝非 UTF-8。"""
    with mock.patch.object(ima_client, "api_call") as m_call:
        with pytest.raises(ValueError, match="UTF-8"):
            ima_client.append_doc("note_1", "bad \udcff text")
        m_call.assert_not_called()


def test_existing_functions_still_importable():
    """回归测试 — 现有 v1.4 函数必须仍可调用（防止新代码破坏旧 API）。"""
    expected_v14 = [
        "load_credentials", "api_call", "check_connection",
        "get_addable_knowledge_bases", "search_knowledge_base",
        "find_kb_by_name", "search_knowledge_in_kb", "import_url",
        "check_duplicate", "check_repeated_names", "create_media",
        "_cos_upload_sdk", "_cos_upload_legacy_v1", "_cos_upload",
        "add_knowledge_file", "upload_markdown_to_kb",
    ]
    for fn in expected_v14:
        assert hasattr(ima_client, fn), f"现有函数 {fn} 缺失！"
        assert callable(getattr(ima_client, fn)), f"{fn} 不可调用"
