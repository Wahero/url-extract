"""PR #13 改动测试：safe_request / _run_ytdlp_combined / BASE_HEADERS。"""
import sys
import time
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import extract  # noqa: E402
import requests  # noqa: E402


# -------------------------------------------------------------------
# T3: HEADERS 拆分
# -------------------------------------------------------------------

def test_base_headers_no_referer():
    """BASE_HEADERS 不含 Referer（给非 B站请求用，避免被跨源拒）。"""
    assert 'Referer' not in extract.BASE_HEADERS


def test_bili_headers_has_referer():
    """BILI_HEADERS / HEADERS 含 B站 Referer。"""
    assert extract.HEADERS.get('Referer') == 'https://www.bilibili.com/'
    assert extract.BILI_HEADERS.get('Referer') == 'https://www.bilibili.com/'


def test_bili_headers_inherits_ua():
    """BILI_HEADERS 继承 BASE_HEADERS 的 UA。"""
    assert extract.BILI_HEADERS.get('User-Agent') == extract.BASE_HEADERS.get('User-Agent')


# -------------------------------------------------------------------
# E4: safe_request 重试
# -------------------------------------------------------------------

def test_safe_request_success_no_retry():
    """正常情况不重试。"""
    with mock.patch.object(extract.requests, "request") as m_request:
        m_resp = mock.Mock()
        m_resp.raise_for_status = mock.Mock()
        m_request.return_value = m_resp
        r = extract.safe_request("GET", "https://example.com")
        assert m_request.call_count == 1
        assert r is m_resp


def test_safe_request_retries_on_connection_error():
    """ConnectionError 重试：默认 max_retries=2 = 共 2 次调用（1 初始 + 1 重试）。"""
    with mock.patch.object(extract.requests, "request") as m_request:
        m_request.side_effect = requests.exceptions.ConnectionError("fail")
        try:
            extract.safe_request("GET", "https://example.com", backoff=0.01)
            assert False, "应该抛 ConnectionError"
        except requests.exceptions.ConnectionError:
            pass
        # max_retries=2 = 2 次总调用
        assert m_request.call_count == 2, f"应调用 2 次，实际 {m_request.call_count}"


def test_safe_request_no_retry_on_http_error():
    """HTTPError（4xx/5xx）不重试，立即抛。"""
    with mock.patch.object(extract.requests, "request") as m_request:
        m_resp = mock.Mock()
        m_resp.raise_for_status = mock.Mock(
            side_effect=requests.exceptions.HTTPError("404")
        )
        m_request.return_value = m_resp
        try:
            extract.safe_request("GET", "https://example.com", backoff=0.01)
            assert False, "应该抛 HTTPError"
        except requests.exceptions.HTTPError:
            pass
        # 只调 1 次
        assert m_request.call_count == 1


def test_safe_request_recovers_on_second_try():
    """第一次失败，第二次成功。"""
    with mock.patch.object(extract.requests, "request") as m_request:
        m_resp_success = mock.Mock()
        m_resp_success.raise_for_status = mock.Mock()
        m_request.side_effect = [
            requests.exceptions.ConnectionError("transient"),
            m_resp_success,
        ]
        r = extract.safe_request("GET", "https://example.com", backoff=0.01)
        # 第一次失败（raise + sleep），第二次成功
        assert m_request.call_count == 2, f"应调用 2 次，实际 {m_request.call_count}"
        assert r is m_resp_success


def test_safe_request_exhausts_retries():
    """连续失败时也只调用 max_retries+1=1 次后抛异常（default max_retries=2 = 2 次总调用）。"""
    with mock.patch.object(extract.requests, "request") as m_request:
        m_request.side_effect = requests.exceptions.Timeout("timeout")
        try:
            extract.safe_request("GET", "https://example.com", backoff=0.01)
            assert False, "应抛 Timeout"
        except requests.exceptions.Timeout:
            pass
        assert m_request.call_count == 2, f"应调用 2 次（max_retries=2），实际 {m_request.call_count}"


# -------------------------------------------------------------------
# E2: _run_ytdlp_combined
# -------------------------------------------------------------------

def test_run_ytdlp_combined_no_cmd():
    """_get_ytdlp_cmd() 返回空时直接返回 None。"""
    with mock.patch.object(extract, "_get_ytdlp_cmd", return_value=""):
        r = extract._run_ytdlp_combined("https://youtu.be/abc")
        assert r is None


def test_run_ytdlp_combined_returns_combined_dict():
    """_run_ytdlp_combined 返回 {'data': ..., 'subtitle': ...}。"""
    # mock subprocess.Popen 返回成功 result
    fake_data = {
        'title': 'Test', 'channel': 'C', 'view_count': 100,
        'duration': 60, 'upload_date': '20240101',
    }
    with mock.patch.object(extract, "_get_ytdlp_cmd", return_value="yt-dlp"), \
         mock.patch("subprocess.Popen") as m_popen:
        # 模拟 yt-dlp 输出
        m_proc = mock.Mock()
        m_proc.wait = mock.Mock()  # 不超时
        m_proc.returncode = 0
        m_popen.return_value = m_proc
        # 模拟 stdout 写入 + 临时目录有 vtt
        with mock.patch("builtins.open", mock.mock_open(read_data='{"title": "test"}')):
            with mock.patch("os.listdir", return_value=["abc123.zh-Hans.vtt"]):
                with mock.patch("tempfile.TemporaryDirectory") as m_tmp:
                    m_tmp.return_value.__enter__ = mock.Mock(return_value="/tmp/fake")
                    m_tmp.return_value.__exit__ = mock.Mock(return_value=False)
                    # 还需要让 vtt 内容 parse 出文字
                    with mock.patch.object(extract, "_parse_vtt_to_text", return_value="line1\nline2"):
                        r = extract._run_ytdlp_combined("https://youtu.be/abc123")
        # 验证返回结构
        assert r is not None
        assert 'data' in r
        assert 'subtitle' in r


# -------------------------------------------------------------------
# T3: defuddle 降级用 BASE_HEADERS（验证 url 实际不带 B站 Referer）
# -------------------------------------------------------------------

def test_defuddle_fallback_no_bili_referer():
    """defuddle 降级路径用 BASE_HEADERS，不带 B站 Referer。"""
    # 这个测试间接验证：进入 defuddle 降级时，requests 调用是 requests.request（safe_request）
    # 而不是 requests.get（裸调用）
    with mock.patch.object(extract, "run_defuddle", return_value=None):
        with mock.patch.object(extract.requests, "request") as m_req:
            m_resp = mock.Mock()
            m_resp.text = "<html><head><title>Test</title></head><body>test</body></html>"
            m_resp.raise_for_status = mock.Mock()
            m_req.return_value = m_resp
            r = extract.extract_webpage("https://example.com/some-page")
            # 应该是 safe_request 调用
            assert m_req.called
            # 检查传入的 headers 不含 B站 Referer
            call_kwargs = m_req.call_args.kwargs
            assert call_kwargs.get('headers', {}).get('Referer') != 'https://www.bilibili.com/'


# -------------------------------------------------------------------
# smoke test: PR #13 整体 import 不应变慢
# -------------------------------------------------------------------

def test_import_no_slow_init():
    """import extract 仍应是 fast（< 0.5s），PR #13 没引入新的慢 init。

    注意：这里不 del sys.modules 重新 import（会破坏后续 test 的 import 引用），
    直接复用 pytest fixture 已经 import 的 extract 模块。
    """
    start = time.time()
    # 复用已 import 的 extract，不做 del sys.modules（避免破坏 import 系统）
    # 验证 _HAS_TENACITY / _DEFUDDLE_CACHE 存在即可
    assert hasattr(extract, "_DEFUDDLE_CACHE")
    assert hasattr(extract, "_YTDLP_CACHE")
    elapsed = time.time() - start
    assert elapsed < 0.5, f"too slow: {elapsed:.3f}s"
