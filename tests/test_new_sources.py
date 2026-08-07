"""issue #4 新来源测试：YouTube / 小红书 / 抖音。

覆盖：
- detect_source 3 个新平台的多种 URL 格式
- resolve_youtube_id / resolve_xhs_url / resolve_douyin_url
- _run_ytdlp_dump_json 走 noembed 降级
- fetch_youtube_noembed mock
- _parse_vtt_to_text 字幕解析
- extract_youtube / _xiaohongshu / _douyin 返回结构
- 3 个模板渲染
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
# detect_source 测试
# ============================================================

class TestDetectSourceNewSources:
    def test_youtube_long_url(self):
        assert extract.detect_source('https://www.youtube.com/watch?v=atqcAb7MFAM') == 'youtube'

    def test_youtube_short_url(self):
        assert extract.detect_source('https://youtu.be/atqcAb7MFAM') == 'youtube'

    def test_youtube_with_query(self):
        assert extract.detect_source('https://youtu.be/atqcAb7MFAM?si=abc') == 'youtube'

    def test_xhs_long_url(self):
        assert extract.detect_source('https://www.xiaohongshu.com/discovery/item/6a539362000000000702ed65') == 'xiaohongshu'

    def test_xhs_short_link_com(self):
        assert extract.detect_source('https://xhslink.com/o/abc') == 'xiaohongshu'

    def test_xhs_short_link_cn(self):
        assert extract.detect_source('http://xhslink.cn/o/abc') == 'xiaohongshu'

    def test_douyin_long_url(self):
        assert extract.detect_source('https://www.douyin.com/video/7123456789012345678') == 'douyin'

    def test_douyin_short_url(self):
        assert extract.detect_source('https://v.douyin.com/abc/') == 'douyin'

    def test_douyin_iesdouyin(self):
        assert extract.detect_source('https://www.iesdouyin.com/share/video/7123456789012345678') == 'douyin'

    def test_existing_sources_still_work(self):
        """旧来源不应被新逻辑误判。"""
        assert extract.detect_source('https://www.bilibili.com/video/BV1xxx') == 'bilibili'
        assert extract.detect_source('https://github.com/foo/bar') == 'github'
        assert extract.detect_source('https://example.com') == 'webpage'


# ============================================================
# YouTube resolve + extract 测试
# ============================================================

class TestYouTubeResolve:
    def test_resolve_youtube_id_watch(self):
        assert extract.resolve_youtube_id('https://www.youtube.com/watch?v=atqcAb7MFAM') == 'atqcAb7MFAM'

    def test_resolve_youtube_id_short(self):
        assert extract.resolve_youtube_id('https://youtu.be/atqcAb7MFAM') == 'atqcAb7MFAM'

    def test_resolve_youtube_id_with_query(self):
        assert extract.resolve_youtube_id('https://youtu.be/atqcAb7MFAM?si=abc') == 'atqcAb7MFAM'

    def test_resolve_youtube_id_invalid(self):
        assert extract.resolve_youtube_id('https://example.com') == ''


class TestYouTubeExtract:
    def setup_method(self):
        # 重置模块级状态
        extract._WBI_MIXIN_KEY_CACHE.update({'key': None, 'expires_at': 0})  # 兼容旧接口

    @mock.patch('extract.requests.request')
    def test_extract_youtube_noembed_fallback(self, mock_get):
        """yt-dlp 不可用时(noembed 替代)能正常返回。"""
        # _run_ytdlp_dump_json 第一次调 ytdlp (没装好/timeout) → 返回 None
        # 然后 fetch_youtube_noembed 成功
        noembed_resp = {
            'title': 'Test YouTube Video',
            'author_name': 'Test Channel',
            'author_url': 'https://www.youtube.com/@test',
            'thumbnail_url': 'https://i.ytimg.com/vi/abc/hqdefault.jpg',
            'provider_name': 'YouTube',
        }
        mock_get.return_value = mock.Mock(json=lambda: noembed_resp, raise_for_status=lambda: None)

        # 直接覆盖 _run_ytdlp_combined 返回 None（不调用 yt-dlp）
        with mock.patch.object(extract, '_run_ytdlp_combined', return_value=None):
            r = extract.extract_youtube('https://youtu.be/atqcAb7MFAM')
        assert r['source'] == 'youtube'
        assert r['video_id'] == 'atqcAb7MFAM'
        assert r['title'] == 'Test YouTube Video'
        assert r['author'] == 'Test Channel'
        assert 'noembed' in r['note']
        assert r['view_count'] == 0  # noembed 不提供
        assert r['like_count'] == 0
        assert r['subtitle']['available'] is False

    @mock.patch('extract.requests.get')
    def test_extract_youtube_ytdlp_path(self, mock_get):
        """yt-dlp 成功时拿到完整数据。"""
        ytdlp_data = {
            'title': 'Real Video',
            'channel': 'Real Channel',
            'channel_url': 'https://www.youtube.com/@real',
            'thumbnail': 'https://i.ytimg.com/vi/xyz/maxres.jpg',
            'upload_date': '20240115',
            'view_count': 12345,
            'like_count': 678,
            'duration': 600,
            'description': 'A real video description',
        }
        # _run_ytdlp_combined 返回 {'data': ..., 'subtitle': ...} 格式
        with mock.patch.object(extract, '_run_ytdlp_combined', return_value={
            'data': ytdlp_data,
            'subtitle': {
                'available': True, 'lan': 'zh-Hant', 'text': 'line1\nline2',
                'note': '字幕来自 yt-dlp (zh-Hant)',
            },
        }):
            r = extract.extract_youtube('https://youtu.be/atqcAb7MFAM')
        assert r['title'] == 'Real Video'
        assert r['author'] == 'Real Channel'
        assert r['view_count'] == 12345
        assert r['like_count'] == 678
        assert r['duration_sec'] == 600
        assert r['pubdate'] == '2024-01-15 00:00:00'
        assert r['subtitle']['available'] is True
        assert r['subtitle']['lan'] == 'zh-Hant'
        assert 'yt-dlp' in r['note']

    def test_extract_youtube_invalid_url(self):
        r = extract.extract_youtube('https://example.com/not-youtube')
        assert r['error'] == '无法解析 YouTube video_id'


# ============================================================
# noembed 测试
# ============================================================

class TestNoembed:
    @mock.patch('extract.requests.request')
    def test_noembed_success(self, mock_get):
        mock_get.return_value = mock.Mock(
            json=lambda: {
                'title': 't', 'author_name': 'a', 'thumbnail_url': 'http://img',
            },
            raise_for_status=lambda: None,
        )
        r = extract.fetch_youtube_noembed('https://youtu.be/abc')
        assert r is not None
        assert r['title'] == 't'

    @mock.patch('extract.requests.request')
    def test_noembed_error(self, mock_get):
        mock_get.return_value = mock.Mock(
            json=lambda: {'error': 'Not found'},
            raise_for_status=lambda: None,
        )
        assert extract.fetch_youtube_noembed('https://youtu.be/abc') is None


# ============================================================
# VTT 字幕解析测试
# ============================================================

class TestVttParse:
    def test_basic_vtt(self):
        vtt = '''WEBVTT

00:00:01.000 --> 00:00:03.000
第一句

00:00:04.000 --> 00:00:06.000
第二句

00:00:07.000 --> 00:00:09.000
第二句
'''
        text = extract._parse_vtt_to_text(vtt)
        # 第二句应该被去重
        assert '第一句' in text
        assert '第二句' in text
        # 验证去重（应该只有 1 个"第二句"）
        assert text.count('第二句') == 1

    def test_vtt_with_cue_numbers(self):
        vtt = '''WEBVTT

1
00:00:01.000 --> 00:00:03.000
hello

2
00:00:04.000 --> 00:00:06.000
world
'''
        text = extract._parse_vtt_to_text(vtt)
        assert 'hello' in text
        assert 'world' in text
        assert '00:00' not in text  # 时间戳应被去除

    def test_vtt_with_styling(self):
        vtt = '''WEBVTT

00:00:01.000 --> 00:00:03.000
<c.color00FFFF>styled</c> text
'''
        text = extract._parse_vtt_to_text(vtt)
        assert 'styled' in text
        assert '<c' not in text  # HTML 标签应被去除

    def test_vtt_with_note(self):
        vtt = '''WEBVTT

NOTE
this is a comment

00:00:01.000 --> 00:00:03.000
actual cue
'''
        text = extract._parse_vtt_to_text(vtt)
        assert 'actual cue' in text
        assert 'comment' not in text  # NOTE 块应被跳过


# ============================================================
# 小红书测试
# ============================================================

class TestXiaohongshuExtract:
    @mock.patch('extract.requests.get')
    def test_extract_xhs_from_long_url(self, mock_get):
        """从 xiaohongshu.com 长链直接拿 item_id。"""
        r = extract.extract_xiaohongshu('https://www.xiaohongshu.com/discovery/item/6a539362000000000702ed65')
        assert r['source'] == 'xiaohongshu'
        assert r['item_id'] == '6a539362000000000702ed65'
        assert r['partial'] is True
        assert '登录态' in r['note']

    @mock.patch('extract.requests.request')
    def test_extract_xhs_from_short_url(self, mock_get):
        """从 xhslink.cn 短链走重定向链找 item_id。"""
        # mock 3 跳重定向: xhslink.cn → xhs → wechat
        r1 = mock.Mock()
        r1.status_code = 302
        r1.headers = {}
        r1.url = 'https://www.xiaohongshu.com/discovery/item/6a539362000000000702ed65?type=video'
        r2 = mock.Mock()
        r2.status_code = 200
        r2.headers = {}
        r2.url = 'https://open.weixin.qq.com/...'
        r3 = mock.Mock()
        r3.status_code = 200
        r3.headers = {}
        # requests.get() 一次返回最终响应, history 在 r.history
        r3.history = [r1, r2]
        r3.url = 'https://open.weixin.qq.com/...'
        mock_get.return_value = r3
        r = extract.extract_xiaohongshu('http://xhslink.cn/o/6a539362000000000702ed65')
        assert r['item_id'] == '6a539362000000000702ed65'
        assert r['kind'] == 'video'

    def test_extract_xhs_invalid_url(self):
        r = extract.extract_xiaohongshu('https://example.com')
        # 应该 item_id 为空 + note 说明
        assert r['item_id'] == '' or r.get('error')


# ============================================================
# 抖音测试
# ============================================================

class TestDouyinExtract:
    def test_resolve_douyin_long_url(self):
        r = extract.resolve_douyin_url('https://www.douyin.com/video/7123456789012345678')
        assert r['video_id'] == '7123456789012345678'

    def test_resolve_douyin_modal_id(self):
        r = extract.resolve_douyin_url('https://www.douyin.com/discover?modal_id=7123456789012345678')
        assert r['video_id'] == '7123456789012345678'

    def test_extract_douyin_returns_partial(self):
        r = extract.extract_douyin('https://www.douyin.com/video/7123456789012345678')
        assert r['source'] == 'douyin'
        assert r['video_id'] == '7123456789012345678'
        assert r['partial'] is True
        assert 'X-Sign' in r['note'] or '签名' in r['note']


# ============================================================
# 模板渲染测试
# ============================================================

class TestNewSourceTemplates:
    def test_youtube_template_with_subtitle(self):
        d = {
            'source': 'youtube', 'video_id': 'abc', 'title': 'Test',
            'url': 'https://www.youtube.com/watch?v=abc',
            'owner': {'name': 'Gary'}, 'author': 'Gary', 'channel_url': 'https://yt/@gary',
            'thumbnail': 'http://img', 'pubdate': '2024-01-15 00:00:00', 'duration_sec': 365,
            'view_count': 100, 'like_count': 5,
            'stat': {'view': 100, 'like': 5},
            'desc': 'desc', 'description': 'desc',
            'subtitle': {'available': True, 'lan': 'zh-Hant', 'full_text': '字幕文本', 'note': 'ok'},
            'note': 'yt-dlp 路径', 'version': '2.6.0',
        }
        ctx = extract._build_context_for_source(d)
        md = extract._render_template('youtube', ctx)
        assert 'Test' in md
        assert 'Gary' in md
        assert '字幕文本' in md
        assert '100' in md  # view_count
        assert '视频时长' in md

    def test_xiaohongshu_template(self):
        d = {
            'source': 'xiaohongshu', 'item_id': '6a539362000000000702ed65',
            'kind': 'video',
            'url': 'https://www.xiaohongshu.com/discovery/item/6a539362000000000702ed65',
            'title': '', 'desc': '', 'note': '需要登录态',
            'version': '2.6.0',
        }
        ctx = extract._build_context_for_source(d)
        md = extract._render_template('xiaohongshu', ctx)
        assert '小红书' in md
        assert '6a539362000000000702ed65' in md
        assert '需要登录态' in md
        assert '部分抽取' in md

    def test_douyin_template(self):
        d = {
            'source': 'douyin', 'video_id': '7123456789012345678',
            'url': 'https://www.douyin.com/video/7123456789012345678',
            'title': '', 'desc': '', 'note': '需要 X-Sign 签名',
            'version': '2.6.0',
        }
        ctx = extract._build_context_for_source(d)
        md = extract._render_template('douyin', ctx)
        assert '抖音' in md
        assert '7123456789012345678' in md
        assert '需要 X-Sign 签名' in md
