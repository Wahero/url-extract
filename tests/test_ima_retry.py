"""ima_client tenacity 重试逻辑单元测试。"""
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import ima_client  # noqa: E402
from ima_client import (
    ImaAPIRetryableError,
    ImaAPIBusinessError,
    _is_retryable,
)


# -------------------------------------------------------------------
# _is_retryable 判定逻辑
# -------------------------------------------------------------------

def _make_http_error(code: int) -> ima_client.urllib.error.HTTPError:
    """用真实的 urllib.error.HTTPError，避免 MagicMock 的比较陷阱。"""
    return ima_client.urllib.error.HTTPError(
        url="http://ima.qq.com/test",
        hdrs={},
        code=code,
        msg="Test Error",
        fp=None,
    )


def test_is_retryable_urlerror():
    exc = ima_client.urllib.error.URLError("Connection refused")
    assert _is_retryable(exc) is True


def test_is_retryable_urlerror_timeout():
    exc = ima_client.urllib.error.URLError("timed out")
    assert _is_retryable(exc) is True


def test_is_retryable_http_500():
    assert _is_retryable(_make_http_error(500)) is True


def test_is_retryable_http_502():
    assert _is_retryable(_make_http_error(502)) is True


def test_is_retryable_http_503():
    assert _is_retryable(_make_http_error(503)) is True


def test_is_retryable_http_599():
    assert _is_retryable(_make_http_error(599)) is True


def test_not_retryable_http_400():
    assert _is_retryable(_make_http_error(400)) is False


def test_not_retryable_http_401():
    assert _is_retryable(_make_http_error(401)) is False


def test_not_retryable_http_404():
    assert _is_retryable(_make_http_error(404)) is False


def test_not_retryable_http_429():
    assert _is_retryable(_make_http_error(429)) is False


def test_is_retryable_ima_api_retryable_error():
    exc = ImaAPIRetryableError("timeout")
    assert _is_retryable(exc) is True


def test_not_retryable_ima_api_business_error():
    exc = ImaAPIBusinessError("code=-101")
    assert _is_retryable(exc) is False


def test_not_retryable_runtime_error():
    exc = RuntimeError("some other error")
    assert _is_retryable(exc) is False


def test_not_retryable_value_error():
    exc = ValueError("bad value")
    assert _is_retryable(exc) is False


# -------------------------------------------------------------------
# api_call 实际重试行为
# -------------------------------------------------------------------

def _mock_urlopen_factory(responses: list):
    """生成 urlopen mock，responses 是按顺序的返回值列表。

    Exception → raise
    dict      → json.dumps 后作为响应 body 返回
    """
    call_idx = [0]

    def fake_urlopen(req, **kwargs):
        idx = call_idx[0]
        call_idx[0] += 1
        val = responses[idx]

        if isinstance(val, Exception):
            raise val

        import json
        body_bytes = json.dumps(val).encode("utf-8")

        m_resp = mock.MagicMock()
        m_resp.read.return_value = body_bytes
        m_resp.__enter__ = mock.MagicMock(return_value=m_resp)
        m_resp.__exit__ = mock.MagicMock(return_value=False)
        return m_resp

    return fake_urlopen


def test_api_call_retries_on_urlerror():
    """URLError → api_call 重试，最终成功返回。"""
    fake = _mock_urlopen_factory([
        ima_client.urllib.error.URLError("connection reset"),
        {"code": 0, "data": {}},
    ])
    with mock.patch.object(ima_client.urllib.request, "urlopen", side_effect=fake):
        with mock.patch.dict("os.environ", {
            "IMA_OPENAPI_CLIENTID": "test_id",
            "IMA_OPENAPI_APIKEY": "test_key",
        }, clear=True):
            result = ima_client.api_call("test/path", {})
            assert result == {"code": 0, "data": {}}


def test_api_call_retries_on_500():
    """HTTP 500 → api_call 重试，最终成功返回。"""
    fake = _mock_urlopen_factory([
        _make_http_error(500),
        {"code": 0, "data": {}},
    ])
    with mock.patch.object(ima_client.urllib.request, "urlopen", side_effect=fake):
        with mock.patch.dict("os.environ", {
            "IMA_OPENAPI_CLIENTID": "test_id",
            "IMA_OPENAPI_APIKEY": "test_key",
        }, clear=True):
            result = ima_client.api_call("test/path", {})
            assert result == {"code": 0, "data": {}}


def test_api_call_no_retry_on_400():
    """HTTP 400 → api_call 不重试，直接抛 ImaAPIBusinessError。"""
    fake = _mock_urlopen_factory([
        _make_http_error(400),
    ])
    with mock.patch.object(ima_client.urllib.request, "urlopen", side_effect=fake):
        with mock.patch.dict("os.environ", {
            "IMA_OPENAPI_CLIENTID": "test_id",
            "IMA_OPENAPI_APIKEY": "test_key",
        }, clear=True):
            try:
                ima_client.api_call("test/path", {})
                assert False, "应该抛 ImaAPIBusinessError"
            except ImaAPIBusinessError:
                pass


def test_api_call_business_error_no_retry():
    """IMA 业务 code != 0（但 HTTP 200）→ 不走重试，正常返回给调用方。"""
    fake = _mock_urlopen_factory([
        {"code": -101, "msg": "风控"},
    ])
    with mock.patch.object(ima_client.urllib.request, "urlopen", side_effect=fake):
        with mock.patch.dict("os.environ", {
            "IMA_OPENAPI_CLIENTID": "test_id",
            "IMA_OPENAPI_APIKEY": "test_key",
        }, clear=True):
            result = ima_client.api_call("test/path", {})
            assert result == {"code": -101, "msg": "风控"}


def test_api_call_immediate_success():
    """正常成功场景：无需重试，直接返回。"""
    fake = _mock_urlopen_factory([
        {"code": 0, "data": {"list": []}},
    ])
    with mock.patch.object(ima_client.urllib.request, "urlopen", side_effect=fake):
        with mock.patch.dict("os.environ", {
            "IMA_OPENAPI_CLIENTID": "test_id",
            "IMA_OPENAPI_APIKEY": "test_key",
        }, clear=True):
            result = ima_client.api_call("test/path", {})
            assert result == {"code": 0, "data": {"list": []}}


def test_has_tenacity_flag():
    assert isinstance(ima_client._HAS_TENACITY, bool)


def test_ima_api_retryable_error_is_exception():
    exc = ImaAPIRetryableError("test")
    assert isinstance(exc, Exception)


def test_ima_api_business_error_is_exception():
    exc = ImaAPIBusinessError("test")
    assert isinstance(exc, Exception)
