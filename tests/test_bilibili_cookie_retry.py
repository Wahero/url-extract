"""B站 Cookie / 重试 / wbi 签名 / 风控检测 单元测试。

不联网（用 unittest.mock 拦截 requests.get）。所有测试都是确定性的。
"""
import sys
import json
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import extract  # noqa: E402


# ============================================================
# Cookie 注入测试
# ============================================================

class TestBiliCookieInjection:
    """验证 Cookie 注入到 HEADERS['Cookie'] 字段。"""

    def setup_method(self):
        """每个测试前清空 cookie 状态。"""
        extract.set_bili_cookies(
            sessdata=None, bili_jct=None, dedeuserid=None, dedeuserid_ckmd5=None
        )
        # 同时清空 wbi 缓存
        extract._WBI_MIXIN_KEY_CACHE.update({'key': None, 'expires_at': 0})
        extract.set_wbi_enabled(False)

    def test_no_cookie_when_all_none(self):
        """不注入任何 cookie 时，_bili_cookie_header 返回空字符串。"""
        result = extract._bili_cookie_header()
        assert result == ''

    def test_only_sessdata(self):
        """只注入 SESSDATA。"""
        extract.set_bili_cookies(sessdata='abc123')
        result = extract._bili_cookie_header()
        assert 'SESSDATA=abc123' in result
        assert 'bili_jct' not in result

    def test_full_cookies(self):
        """注入完整 cookie 套件。"""
        extract.set_bili_cookies(
            sessdata='sess_val',
            bili_jct='jct_val',
            dedeuserid='12345',
            dedeuserid_ckmd5='md5hash',
        )
        result = extract._bili_cookie_header()
        assert 'SESSDATA=sess_val' in result
        assert 'bili_jct=jct_val' in result
        assert 'DedeUserID=12345' in result
        assert 'DebiUserID__ckMd5=md5hash' in result or 'DedeUserID__ckMd5=md5hash' in result

    def test_partial_update_preserves_existing(self):
        """只更新 SESSDATA，bili_jct 仍保留。"""
        extract.set_bili_cookies(sessdata='old', bili_jct='keep_me')
        extract.set_bili_cookies(sessdata='new')
        result = extract._bili_cookie_header()
        assert 'SESSDATA=new' in result
        assert 'bili_jct=keep_me' in result

    @mock.patch('extract.requests.get')
    def test_cookie_sent_in_request(self, mock_get):
        """_bili_get 调用时，Cookie header 应被设置。"""
        mock_get.return_value = mock.Mock(
            json=lambda: {'code': 0, 'data': {'bvid': 'BV1'}},
            raise_for_status=lambda: None,
        )
        extract.set_bili_cookies(sessdata='my_sessdata')
        extract._bili_get('https://api.bilibili.com/x/web-interface/view', params={'bvid': 'BV1'})
        call_kwargs = mock_get.call_args.kwargs
        assert 'Cookie' in call_kwargs['headers']
        assert 'SESSDATA=my_sessdata' in call_kwargs['headers']['Cookie']


# ============================================================
# 风控检测测试
# ============================================================

class TestBiliRiskDetection:
    """验证 _check_bili_risk 正确识别风控响应。"""

    def test_code_zero_passes(self):
        """code=0 不触发风控。"""
        extract._check_bili_risk({'code': 0, 'message': 'OK', 'data': {}})

    def test_minus_101_unauthorized(self):
        """code=-101 触发 BilibiliRiskControlError。"""
        with pytest.raises(extract.BilibiliRiskControlError) as exc:
            extract._check_bili_risk({'code': -101, 'message': '账号未登录'}, bvid_or_aid='BV1')
        assert exc.value.code == -101
        assert 'BV1' in str(exc.value)

    def test_minus_352_risk(self):
        """code=-352 触发。"""
        with pytest.raises(extract.BilibiliRiskControlError):
            extract._check_bili_risk({'code': -352, 'message': '风控等级'})

    def test_minus_412_firewall(self):
        """code=-412 触发。"""
        with pytest.raises(extract.BilibiliRiskControlError):
            extract._check_bili_risk({'code': -412, 'message': '请求被拦截'})

    def test_minus_799_rate_limit(self):
        """code=-799 触发。"""
        with pytest.raises(extract.BilibiliRiskControlError):
            extract._check_bili_risk({'code': -799, 'message': '请求过于频繁'})

    def test_other_nonzero_code_silent(self):
        """code != 0 且不在风控列表中：不抛异常（给上层业务逻辑处理）。"""
        extract._check_bili_risk({'code': -403, 'message': '视频不存在'})


# ============================================================
# 重试机制测试
# ============================================================

class TestBiliRetry:
    """验证 _bili_get 在风控时自动重试 3 次。"""

    def setup_method(self):
        extract.set_bili_cookies(
            sessdata=None, bili_jct=None, dedeuserid=None, dedeuserid_ckmd5=None
        )
        extract._WBI_MIXIN_KEY_CACHE.update({'key': None, 'expires_at': 0})
        extract.set_wbi_enabled(False)

    @mock.patch('extract.requests.get')
    def test_retry_three_times_on_risk(self, mock_get):
        """风控时连续 3 次请求后放弃。"""
        mock_get.return_value = mock.Mock(
            json=lambda: {'code': -412, 'message': '请求被拦截'},
            raise_for_status=lambda: None,
        )
        with pytest.raises(extract.BilibiliRiskControlError):
            extract._bili_get('https://api.bilibili.com/x/web-interface/view', params={'bvid': 'BV1'})
        # 验证调用了 3 次（默认 stop_after_attempt(3)）
        assert mock_get.call_count == 3

    @mock.patch('extract.requests.get')
    def test_recover_on_second_attempt(self, mock_get):
        """第一次风控，第二次成功。"""
        mock_get.side_effect = [
            mock.Mock(json=lambda: {'code': -412, 'message': '拦截'}, raise_for_status=lambda: None),
            mock.Mock(json=lambda: {'code': 0, 'data': {'bvid': 'BV1'}}, raise_for_status=lambda: None),
        ]
        result = extract._bili_get('https://api.bilibili.com/x/web-interface/view', params={'bvid': 'BV1'})
        assert result['code'] == 0
        assert mock_get.call_count == 2

    @mock.patch('extract.requests.get')
    def test_no_retry_on_success(self, mock_get):
        """成功时只调 1 次。"""
        mock_get.return_value = mock.Mock(
            json=lambda: {'code': 0, 'data': {}},
            raise_for_status=lambda: None,
        )
        extract._bili_get('https://api.bilibili.com/x/test', params={'a': 1})
        assert mock_get.call_count == 1


# ============================================================
# wbi 签名测试
# ============================================================

class TestWbiSign:
    """验证 wbi 签名算法正确性（用 mock nav 接口）。"""

    def setup_method(self):
        extract._WBI_MIXIN_KEY_CACHE.update({'key': None, 'expires_at': 0})
        extract.set_wbi_enabled(False)

    NAV_FIXTURE = {
        'code': 0,
        'data': {
            'wbi_img': {
                'img_url': 'https://i0.hdslb.com/bfs/wbi/7cd084941338484aae1ad9425b84077c.png',
                'sub_url': 'https://i0.hdslb.com/bfs/wbi/4932caff0ff746eab6f01bf08b70ac45.png',
            }
        }
    }

    @mock.patch('extract.requests.get')
    def test_wbi_sign_computes_w_rid(self, mock_get):
        """签名结果应包含 wts + w_rid。"""
        mock_get.return_value = mock.Mock(
            json=lambda: self.NAV_FIXTURE,
            raise_for_status=lambda: None,
        )
        result = extract._wbi_sign({'bvid': 'BV1DHuJ6wELy'})
        assert 'wts' in result
        assert 'w_rid' in result
        assert 'bvid' in result
        assert len(result['w_rid']) == 32  # md5 hex

    @mock.patch('extract.requests.get')
    def test_wbi_sign_filters_special_chars(self, mock_get):
        """value 含特殊字符的 key 应被过滤。"""
        mock_get.return_value = mock.Mock(
            json=lambda: self.NAV_FIXTURE, raise_for_status=lambda: None
        )
        # key 含特殊字符的会被过滤（socialsisteryi 算法是过滤 value 含 !'()* 的 key）
        result = extract._wbi_sign({'bvid': 'BV1DHuJ6wELy', 'badkey': 'has!special'})
        assert 'bvid' in result
        # badkey 因 value 含 ! 被过滤
        assert 'badkey' not in result

    @mock.patch('extract.requests.get')
    def test_mixin_key_cache(self, mock_get):
        """nav 接口应被缓存，1h 内只调 1 次。"""
        mock_get.return_value = mock.Mock(
            json=lambda: self.NAV_FIXTURE, raise_for_status=lambda: None
        )
        extract._wbi_sign({'a': 1})
        extract._wbi_sign({'a': 2})
        extract._wbi_sign({'a': 3})
        assert mock_get.call_count == 1

    @mock.patch('extract.requests.get')
    def test_wbi_enabled_sends_to_bili_get(self, mock_get):
        """开启 wbi 签名时，_bili_get 应先调 nav + 签名。"""
        view_resp = {'code': 0, 'data': {'bvid': 'BV1'}}
        mock_get.side_effect = [
            mock.Mock(json=lambda: self.NAV_FIXTURE, raise_for_status=lambda: None),
            mock.Mock(json=lambda: view_resp, raise_for_status=lambda: None),
        ]
        extract.set_wbi_enabled(True)
        try:
            result = extract._bili_get(
                'https://api.bilibili.com/x/web-interface/view',
                params={'bvid': 'BV1'},
            )
            assert result['code'] == 0
            # 第一次调用是 nav, 第二次是 view
            assert mock_get.call_count == 2
        finally:
            extract.set_wbi_enabled(False)


# ============================================================
# 端到端 fetch_bili_* 集成测试
# ============================================================

class TestBiliFetchersIntegration:
    """验证 fetch_bili_* 全部走 _bili_get 包装器。"""

    def setup_method(self):
        extract.set_bili_cookies(
            sessdata=None, bili_jct=None, dedeuserid=None, dedeuserid_ckmd5=None
        )
        extract._WBI_MIXIN_KEY_CACHE.update({'key': None, 'expires_at': 0})
        extract.set_wbi_enabled(False)

    @mock.patch('extract.requests.get')
    def test_fetch_bili_video_info_success(self, mock_get):
        """成功获取视频信息。"""
        mock_get.return_value = mock.Mock(
            json=lambda: {
                'code': 0,
                'data': {
                    'bvid': 'BV1',
                    'aid': 12345,
                    'cid': 67890,
                    'title': 'test',
                    'desc': '',
                    'owner': {'name': 'up', 'mid': 1},
                    'pubdate': 0,
                    'duration': 0,
                    'stat': {'view': 0, 'like': 0, 'coin': 0, 'favorite': 0, 'share': 0, 'reply': 0},
                    'pic': '',
                }
            },
            raise_for_status=lambda: None,
        )
        data = extract.fetch_bili_video_info('BV1')
        assert data['bvid'] == 'BV1'
        assert data['aid'] == 12345

    @mock.patch('extract.requests.get')
    def test_fetch_bili_video_info_raises_on_risk(self, mock_get):
        """风控时 fetch_bili_video_info 重试 3 次后抛 BilibiliRiskControlError。"""
        mock_get.return_value = mock.Mock(
            json=lambda: {'code': -352, 'message': '风控升级'},
            raise_for_status=lambda: None,
        )
        with pytest.raises(extract.BilibiliRiskControlError):
            extract.fetch_bili_video_info('BV1')
        assert mock_get.call_count == 3

    @mock.patch('extract.requests.get')
    def test_fetch_bili_tags_returns_empty_on_risk(self, mock_get):
        """tags 接口风控时容错返回空列表。"""
        mock_get.return_value = mock.Mock(
            json=lambda: {'code': -412, 'message': '拦截'},
            raise_for_status=lambda: None,
        )
        result = extract.fetch_bili_tags('BV1')
        # tags 走 try/except, 风控时 3 次重试后 raise, 但被 except 捕获 → 返回 []
        assert result == []
        assert mock_get.call_count == 3

    @mock.patch('extract.requests.get')
    def test_fetch_bili_subtitle_no_subs(self, mock_get):
        """无字幕时返回 available=False（不抛异常）。"""
        mock_get.return_value = mock.Mock(
            json=lambda: {'code': 0, 'data': {'subtitle': {'subtitles': []}}},
            raise_for_status=lambda: None,
        )
        result = extract.fetch_bili_subtitle('BV1', 123)
        assert result['available'] is False
        assert '未上传字幕' in result['note']


# ============================================================
# 边界场景
# ============================================================

class TestBiliEdgeCases:
    """边界场景测试。"""

    def test_bilibili_risk_control_error_contains_bvid(self):
        """异常消息应包含 bvid/aid 便于诊断。"""
        err = extract.BilibiliRiskControlError(-101, '未登录', 'BV1DHuJ6wELy')
        msg = str(err)
        assert '-101' in msg
        assert '未登录' in msg
        assert 'BV1DHuJ6wELy' in msg

    def test_module_import_without_tenacity(self):
        """即使 tenacity 没装,模块 import 不应失败。"""
        assert hasattr(extract, '_HAS_TENACITY')
        # retry 装饰器在无 tenacity 时是 no-op
        @extract.retry
        def fn():
            return 42
        assert fn() == 42
