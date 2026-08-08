"""_cos_upload_sdk 修复测试：ContentLength 删了 + 用 ETag 判定成功。"""
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


def _mock_qcloud_cos(success_response=None, side_effect=None):
    """Mock 整个 qcloud_cos 模块，避免真实 SDK 调用。"""
    mock_qcloud = mock.MagicMock()
    mock_qcloud.CosConfig.return_value = mock.MagicMock()
    if side_effect:
        mock_qcloud.CosS3Client.return_value.put_object.side_effect = side_effect
    else:
        mock_qcloud.CosS3Client.return_value.put_object.return_value = success_response
    return mock_qcloud


# -------------------------------------------------------------------
# Bug 1: ContentLength 不传
# -------------------------------------------------------------------

def test_put_object_not_pass_content_length():
    """_cos_upload_sdk 调用 SDK 时不传 ContentLength 参数。"""
    mock_qcloud = _mock_qcloud_cos(success_response={"ETag": '"abc"'})
    with mock.patch.dict(sys.modules, {"qcloud_cos": mock_qcloud}):
        ima_client._cos_upload_sdk(CRED, FILE_DATA, CT, COS_KEY, SIZE)
    call_kwargs = mock_qcloud.CosS3Client.return_value.put_object.call_args.kwargs
    assert "ContentLength" not in call_kwargs, \
        f"不应传 ContentLength，实际传了: {call_kwargs.get('ContentLength')!r}"


# -------------------------------------------------------------------
# Bug 2: 用 ETag 判定成功
# -------------------------------------------------------------------

def test_success_with_etag_dict_returns_true():
    """SDK 返回带 ETag 的 dict（成功）→ 返回 True。"""
    mock_qcloud = _mock_qcloud_cos(success_response={
        "ETag": '"abc123def456"',
        "Last-Modified": "2026-08-08",
        "Location": "cos.ap-guangzhou.myqcloud.com/bucket/key",
    })
    with mock.patch.dict(sys.modules, {"qcloud_cos": mock_qcloud}):
        result = ima_client._cos_upload_sdk(CRED, FILE_DATA, CT, COS_KEY, SIZE)
    assert result is True


def test_success_dict_without_etag_returns_false():
    """SDK 返回 dict 但没有 ETag（边缘 case 失败）→ 返回 False。"""
    mock_qcloud = _mock_qcloud_cos(success_response={
        "Error": {"Code": "AccessDenied", "Message": "forbidden"},
    })
    with mock.patch.dict(sys.modules, {"qcloud_cos": mock_qcloud}):
        result = ima_client._cos_upload_sdk(CRED, FILE_DATA, CT, COS_KEY, SIZE)
    assert result is False


def test_success_empty_etag_returns_false():
    """SDK 返回 dict 含 ETag 但 ETag 为空 → 返回 False。"""
    mock_qcloud = _mock_qcloud_cos(success_response={"ETag": ""})
    with mock.patch.dict(sys.modules, {"qcloud_cos": mock_qcloud}):
        result = ima_client._cos_upload_sdk(CRED, FILE_DATA, CT, COS_KEY, SIZE)
    assert result is False


def test_success_non_dict_response_returns_false():
    """SDK 返回非 dict → 返回 False（保守）。"""
    mock_qcloud = _mock_qcloud_cos(success_response="some string")
    with mock.patch.dict(sys.modules, {"qcloud_cos": mock_qcloud}):
        result = ima_client._cos_upload_sdk(CRED, FILE_DATA, CT, COS_KEY, SIZE)
    assert result is False


def test_sdk_raises_exception_propagates():
    """SDK 抛异常（CosClientError / CosServiceError）→ 让异常往上抛。"""
    mock_qcloud = _mock_qcloud_cos(
        side_effect=Exception("network error")
    )
    with mock.patch.dict(sys.modules, {"qcloud_cos": mock_qcloud}):
        try:
            ima_client._cos_upload_sdk(CRED, FILE_DATA, CT, COS_KEY, SIZE)
            assert False, "应该抛异常"
        except Exception as e:
            assert "network error" in str(e)
