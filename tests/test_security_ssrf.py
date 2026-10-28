"""安全相关测试：SSRF 防护（validate_url + safe_request 重定向）与 detect_source 修正。

Security tests: SSRF protection (validate_url + safe_request redirect re-validation)
and the detect_source substring-mismatch fix.
"""
import sys
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import extract  # noqa: E402


# ============================================================
# validate_url — SSRF 绕过用例
# ============================================================

class TestValidateUrlSSRF:
    def test_rejects_shorthand_loopback(self):
        # 127.1 -> 127.0.0.1
        with pytest.raises(extract.URLError):
            extract.validate_url("http://127.1/")

    def test_rejects_decimal_ip(self):
        # 十进制 IP 2130706433 -> 127.0.0.1
        with pytest.raises(extract.URLError):
            extract.validate_url("http://2130706433/")

    def test_rejects_private_ranges(self):
        for u in ("http://192.168.1.1/", "http://10.0.0.1/", "http://172.16.0.1/"):
            with pytest.raises(extract.URLError):
                extract.validate_url(u)

    def test_rejects_ipv6_loopback(self):
        with pytest.raises(extract.URLError):
            extract.validate_url("http://[::1]/")

    def test_rejects_internal_domain_suffix(self):
        with pytest.raises(extract.URLError):
            extract.validate_url("http://secret.internal/")
        with pytest.raises(extract.URLError):
            extract.validate_url("http://host.local/")

    def test_allows_public_host(self):
        assert extract.validate_url("http://example.com") == "http://example.com"
        assert (
            extract.validate_url("https://www.bilibili.com/video/BV1xx")
            == "https://www.bilibili.com/video/BV1xx"
        )


# ============================================================
# safe_request — 重定向 SSRF 防护
# ============================================================

class TestSafeRequestRedirectSSRF:
    def test_safe_request_blocks_redirect_to_internal(self):
        redirect = mock.Mock()
        redirect.is_redirect = True
        redirect.status_code = 302
        redirect.headers = {"Location": "http://169.254.169.254/latest/meta-data/"}

        with mock.patch.object(extract.requests, "request", return_value=redirect):
            # 手动跟随时逐跳校验到内网 -> 抛 URLError
            with pytest.raises(extract.URLError):
                extract.safe_request("GET", "http://example.com/")

    def test_safe_request_follows_public_redirect(self):
        redirect = mock.Mock()
        redirect.is_redirect = True
        redirect.status_code = 302
        redirect.headers = {"Location": "https://www.bilibili.com/video/BV1xx"}
        final = mock.Mock()
        final.is_redirect = False
        final.status_code = 200
        final.headers = {}

        with mock.patch.object(
            extract.requests, "request", side_effect=[redirect, final]
        ):
            r = extract.safe_request("GET", "http://example.com/")
            assert r is final


# ============================================================
# detect_source — 子串误判修正
# ============================================================

class TestDetectSource:
    def test_youtube_not_misrouted_to_github(self):
        # 之前 'github.com' in s 会先命中，导致误判
        assert (
            extract.detect_source("https://youtube.com/watch?v=abc&ref=github.com")
            == "youtube"
        )

    def test_github_still_detected(self):
        assert extract.detect_source("https://github.com/foo/bar") == "github"

    def test_webpage_fallback(self):
        assert extract.detect_source("https://example.com/article") == "webpage"

    def test_known_hosts_regression(self):
        assert (
            extract.detect_source("https://www.youtube.com/watch?v=atqcAb7MFAM")
            == "youtube"
        )
        assert extract.detect_source("https://youtu.be/atqcAb7MFAM") == "youtube"
        assert (
            extract.detect_source("https://www.xiaohongshu.com/discovery/item/6a539")
            == "xiaohongshu"
        )
        assert (
            extract.detect_source("https://www.douyin.com/video/7123456789012345678")
            == "douyin"
        )
        assert extract.detect_source("https://www.bilibili.com/video/BV1xxx") == "bilibili"
        assert extract.detect_source("https://b23.tv/xxx") == "bilibili"
