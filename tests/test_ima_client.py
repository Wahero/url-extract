"""ima_client 单元测试 — 主要测试 COS 上传分发逻辑。"""
import sys
from pathlib import Path
from unittest import mock

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
