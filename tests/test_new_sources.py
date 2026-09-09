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
# 小红书 v2.6：CDN → ASR 抽取链路（无需登录）
# ============================================================

class TestXhsDeeplinkParse:
    """测试 _parse_xhs_deeplink：从 oia?deeplink= URL 抽视频 CDN + 封面 + 作者 UID。

    真实 XHS 结构（双重 URL encoding）：
        oia?deeplink=xhsdiscover%3A%2F%2Fvideo_feed%2F<id>%3Fh5VideoPreloadInfo%3D%257B...%257D%26...
        ↓ unquote 1 次
        xhsdiscover://video_feed/<id>?h5VideoPreloadInfo=%7B...%7D&open_url=...&appuid=...
        ↓ parse_qs（自动 unquote）
        {'h5VideoPreloadInfo': '{"title":"","video_info_v2":{...}}', 'open_url': '/...', 'appuid': '...'}
    """

    def _wrap_deeplink_url(self, inner_query: dict) -> str:
        """把内层 query dict 包装成完整的 oia 重定向 URL（两层 URL 编码）。"""
        import urllib.parse
        # 内层 query string（key=value&key=value 形式）
        inner_qs = urllib.parse.urlencode(inner_query)
        # 内层 xhsdiscover URL
        inner_url = f'xhsdiscover://video_feed/test?{inner_qs}'
        # 外层 URL encode（deellink query 参数值）
        outer_encoded = urllib.parse.quote(inner_url, safe='')
        return f'https://oia.xiaohongshu.com/oia?deeplink={outer_encoded}'

    def test_parse_deeplink_with_h264_and_cover(self):
        inner_json = json.dumps({
            'title': '',
            'video_info_v2': {
                'image': {'first_frame': 'http://sns-webpic-qc.xhscdn.com/cover.jpg'},
                'media': {'stream': {
                    'h264': [{'master_url': 'http://sns-video.xhscdn.com/v.mp4?sign=abc',
                              'width': 720, 'height': 1280}],
                    'h265': [],
                }},
            },
        })
        outer = self._wrap_deeplink_url({
            'h5VideoPreloadInfo': inner_json,
            'open_url': '/discovery/item/abc?xsec_token=xyz',
            'appuid': '63496da800000000180287b2',
            'shareContent': 'note',
        })
        result = extract._parse_xhs_deeplink(outer)
        assert result['h264_url'] == 'http://sns-video.xhscdn.com/v.mp4?sign=abc'
        assert result['cover_url'] == 'http://sns-webpic-qc.xhscdn.com/cover.jpg'
        assert result['author_uid'] == '63496da800000000180287b2'
        assert result['width'] == 720
        assert result['height'] == 1280

    def test_parse_deeplink_fallback_to_h265(self):
        """h264 缺失时回退到 h265。"""
        inner_json = json.dumps({
            'video_info_v2': {
                'media': {'stream': {
                    'h264': [],
                    'h265': [{'master_url': 'http://sns-video.xhscdn.com/v265.mp4?sign=xyz',
                              'width': 720, 'height': 1280}],
                }},
            },
        })
        outer = self._wrap_deeplink_url({
            'h5VideoPreloadInfo': inner_json,
            'appuid': 'uid123',
        })
        result = extract._parse_xhs_deeplink(outer)
        assert result['h265_url'] == 'http://sns-video.xhscdn.com/v265.mp4?sign=xyz'
        assert result['h264_url'] == ''  # h264 空
        assert result['author_uid'] == 'uid123'

    def test_parse_deeplink_malformed_returns_empty(self):
        result = extract._parse_xhs_deeplink('not a url at all')
        assert result['h264_url'] == ''
        assert result['cover_url'] == ''

    def test_parse_deeplink_missing_deeplink_param(self):
        result = extract._parse_xhs_deeplink('https://oia.xiaohongshu.com/oia?other=1')
        assert result['h264_url'] == ''

    def test_parse_deeplink_web_spa_html(self):
        """Web 短链 HTML 路径：HTML 含 sns-video-*.mp4?sign= 与 sns-webpic-*.jpg。

        实测（2026-09-09）：xhslink.cn 短链在桌面浏览器打开时返回 SPA 页面，
        window.__INITIAL_STATE__ 里嵌入完整 note JSON，视频 CDN URL 明文，
        / 写成了 \\u002F。
        """
        web_html = '''
        <html><script>window.__INITIAL_STATE__ = {
            "noteData": {
                "video": {
                    "media": {
                        "stream": {
                            "h264": [{"master_url": "http:\\u002F\\u002Fsns-video-v27.xhscdn.com\\u002Fstream\\u002F79\\u002F110\\u002F259\\u002Fabc.mp4?sign=xyz&t=123"}]
                        }
                    }
                }
            }
        };</script>
        <a href="http:\\u002F\\u002Fsns-video-v27.xhscdn.com\\u002Fstream\\u002F79\\u002F110\\u002F309\\u002Fabc.mp4?sign=xyz&t=123">h265</a>
        <img src="http:\\u002F\\u002Fsns-webpic-qc.xhscdn.com\\u002F20260909\\u002Fabc\\u002Fspectrum\\u002Ftest!h5_1080jpg"/>
        "userId":"68db3a0d0000000037009a22"
        </html>
        '''
        result = extract._parse_xhs_deeplink(web_html)
        assert result['h264_url'].endswith('/259/abc.mp4?sign=xyz&t=123')
        assert result['h265_url'].endswith('/309/abc.mp4?sign=xyz&t=123')
        assert result['cover_url'].endswith('test!h5_1080jpg')
        assert result['author_uid'] == '68db3a0d0000000037009a22'


class TestXhsVideoPipeline:
    """测试 _try_xhs_video_cdn_pipeline：CDN→ASR 主流程的 stage 划分。"""

    def _make_html(self, inner_query: dict) -> str:
        """构造模拟的 oia 重定向 HTML。"""
        import urllib.parse
        inner_qs = urllib.parse.urlencode(inner_query)
        inner_url = f'xhsdiscover://video_feed/test?{inner_qs}'
        outer_encoded = urllib.parse.quote(inner_url, safe='')
        return f'<html>oia?deeplink={outer_encoded}</html>'

    @mock.patch('extract._apple_speech_transcribe')
    @mock.patch('extract._ffmpeg_extract_audio')
    @mock.patch('extract._download_xhs_video')
    @mock.patch('extract.safe_request')
    def test_pipeline_success(self, mock_safe_req, mock_dl, mock_ffmpeg, mock_asr):
        # 1. safe_request 返回 HTML（含 deeplink）
        inner_json = json.dumps({
            'title': '',
            'video_info_v2': {
                'image': {'first_frame': 'http://cover.jpg'},
                'media': {'stream': {
                    'h264': [{'master_url': 'http://video.mp4?sign=abc',
                              'width': 720, 'height': 1280}],
                }},
            },
        })
        html = self._make_html({
            'h5VideoPreloadInfo': inner_json,
            'appuid': 'uid_xyz',
            'open_url': '/discovery/item/abc',
        })
        mock_resp = mock.Mock(text=html, url='https://oia.xiaohongshu.com/oia?...')
        mock_safe_req.return_value = mock_resp
        # 2. 下载返回 True（创建临时文件）
        mock_dl.side_effect = [True, True]  # video + cover
        # 3. ffmpeg 返回 True（创建临时文件）
        mock_ffmpeg.return_value = True
        # 4. apple-speech 返回成功
        mock_asr.return_value = {
            'ok': True,
            'text': '转写文本内容',
            'segments': [{'substring': '转写', 'timestamp': 0.0, 'confidence': 0.9}],
            'duration_seconds': 90.0,
        }

        parsed = {'item_id': 'abc123', 'kind': 'video', 'canonical_url': 'http://xhs.com/item/abc'}
        with mock.patch('extract.os.path.exists', return_value=True):
            result = extract._try_xhs_video_cdn_pipeline('http://xhslink.cn/o/abc', parsed)

        assert result['ok'] is True
        assert result['transcript'] == '转写文本内容'
        assert len(result['transcript_segments']) == 1
        assert result['author_uid'] == 'uid_xyz'
        assert result['video_url'] == 'http://video.mp4?sign=abc'
        assert result['cover_url'] == 'http://cover.jpg'

    @mock.patch('extract.safe_request')
    def test_pipeline_no_deeplink_in_html(self, mock_safe_req):
        """HTML 里没有 deeplink 时，stage=parse_deeplink。"""
        mock_resp = mock.Mock(text='<html>no oia link here</html>', url='http://x')
        mock_safe_req.return_value = mock_resp
        result = extract._try_xhs_video_cdn_pipeline(
            'http://xhslink.cn/o/abc',
            {'item_id': 'abc', 'kind': 'video', 'canonical_url': 'http://x'},
        )
        assert result['ok'] is False
        assert result['stage'] == 'parse_deeplink'

    @mock.patch('extract._download_xhs_video')
    @mock.patch('extract.safe_request')
    def test_pipeline_download_failure(self, mock_safe_req, mock_dl):
        """CDN URL 有但下载失败时，stage=download_video。"""
        inner_json = json.dumps({
            'title': '',
            'video_info_v2': {
                'media': {'stream': {'h264': [{'master_url': 'http://video.mp4',
                                                'width': 720, 'height': 1280}]}},
            },
        })
        html = self._make_html({'h5VideoPreloadInfo': inner_json, 'appuid': 'uid'})
        mock_resp = mock.Mock(text=html, url='http://x')
        mock_safe_req.return_value = mock_resp
        mock_dl.return_value = False  # 下载失败
        result = extract._try_xhs_video_cdn_pipeline(
            'http://xhslink.cn/o/abc',
            {'item_id': 'abc', 'kind': 'video', 'canonical_url': 'http://x'},
        )
        assert result['ok'] is False
        assert result['stage'] == 'download_video'

    @mock.patch('extract._ffmpeg_extract_audio')
    @mock.patch('extract._download_xhs_video')
    @mock.patch('extract.safe_request')
    def test_pipeline_ffmpeg_failure(self, mock_safe_req, mock_dl, mock_ffmpeg):
        """下载成功但 ffmpeg 抽音失败时，stage=ffmpeg。"""
        inner_json = json.dumps({
            'video_info_v2': {
                'media': {'stream': {'h264': [{'master_url': 'http://video.mp4',
                                                'width': 720, 'height': 1280}]}},
            },
        })
        html = self._make_html({'h5VideoPreloadInfo': inner_json})
        mock_resp = mock.Mock(text=html, url='http://x')
        mock_safe_req.return_value = mock_resp
        mock_dl.return_value = True  # 下载成功
        mock_ffmpeg.return_value = False  # ffmpeg 失败
        result = extract._try_xhs_video_cdn_pipeline(
            'http://xhslink.cn/o/abc',
            {'item_id': 'abc', 'kind': 'video', 'canonical_url': 'http://x'},
        )
        assert result['ok'] is False
        assert result['stage'] == 'ffmpeg'
        assert 'video_path' in result  # 失败时也保留已下载的视频路径便于排查

    @mock.patch('extract._apple_speech_transcribe')
    @mock.patch('extract._ffmpeg_extract_audio')
    @mock.patch('extract._download_xhs_video')
    @mock.patch('extract.safe_request')
    def test_pipeline_transcribe_failure(self, mock_safe_req, mock_dl, mock_ffmpeg, mock_asr):
        """下载 + ffmpeg 成功但 ASR 失败时，stage=transcribe。"""
        inner_json = json.dumps({
            'video_info_v2': {
                'media': {'stream': {'h264': [{'master_url': 'http://video.mp4',
                                                'width': 720, 'height': 1280}]}},
            },
        })
        html = self._make_html({'h5VideoPreloadInfo': inner_json})
        mock_resp = mock.Mock(text=html, url='http://x')
        mock_safe_req.return_value = mock_resp
        mock_dl.return_value = True
        mock_ffmpeg.return_value = True
        mock_asr.return_value = {'ok': False, 'error': 'apple-speech timeout'}
        result = extract._try_xhs_video_cdn_pipeline(
            'http://xhslink.cn/o/abc',
            {'item_id': 'abc', 'kind': 'video', 'canonical_url': 'http://x'},
        )
        assert result['ok'] is False
        assert result['stage'] == 'transcribe'
        assert result['error'] == 'apple-speech timeout'
        assert 'audio_path' in result  # 失败时也保留 wav 路径

    def test_fill_xhs_result_from_video_dict(self):
        """_fill_xhs_result_from_video_dict 从内层 JSON 填充 result。"""
        result = {
            'h264_url': '', 'h265_url': '', 'cover_url': '',
            'author_uid': '', 'item_url': '',
            'width': 0, 'height': 0,
        }
        data = {
            'video_info_v2': {
                'image': {'first_frame': 'http://cover.jpg'},
                'media': {'stream': {
                    'h264': [{'master_url': 'http://v.mp4', 'width': 720, 'height': 1280}],
                    'h265': [{'master_url': 'http://v265.mp4', 'width': 720, 'height': 1280}],
                }},
            },
            'appuid': 'uid_abc',
            'open_url': '/discovery/item/abc',
        }
        extract._fill_xhs_result_from_video_dict(result, data, qs={})
        assert result['h264_url'] == 'http://v.mp4'
        assert result['h265_url'] == 'http://v265.mp4'
        assert result['cover_url'] == 'http://cover.jpg'
        assert result['author_uid'] == 'uid_abc'
        assert result['width'] == 720
        assert result['height'] == 1280

    def test_fill_xhs_result_falls_back_to_qs(self):
        """appuid 不在 JSON 时从 qs 兜底取。"""
        result = {
            'h264_url': '', 'h265_url': '', 'cover_url': '',
            'author_uid': '', 'item_url': '',
            'width': 0, 'height': 0,
        }
        # JSON 没有 appuid，但 qs query string 里有
        extract._fill_xhs_result_from_video_dict(
            result, {'video_info_v2': {'media': {'stream': {}}}},
            qs={'appuid': ['uid_from_qs'], 'open_url': ['/from/qs']},
        )
        assert result['author_uid'] == 'uid_from_qs'
        assert result['item_url'] == '/from/qs'


class TestXhsExtractV26:
    """测试 extract_xiaohongshu v2.6：视频笔记走 CDN→ASR 链路。"""

    @mock.patch('extract._try_xhs_video_cdn_pipeline')
    @mock.patch('extract.resolve_xhs_url')
    def test_extract_video_calls_pipeline(self, mock_resolve, mock_pipeline):
        mock_resolve.return_value = {
            'item_id': 'abc123', 'kind': 'video', 'canonical_url': 'http://xhs.com/item/abc',
        }
        mock_pipeline.return_value = {
            'ok': True,
            'transcript': '完整转写文本',
            'transcript_segments': [{'substring': '你好', 'timestamp': 0.0, 'confidence': 0.9}],
            'transcript_duration_sec': 60.0,
            'video_url': 'http://video.mp4',
            'cover_url': 'http://cover.jpg',
            'cover_local': '/tmp/cover.jpg',
            'video_local': '/tmp/video.mp4',
            'audio_local': '/tmp/audio.wav',
            'author_uid': 'uid_xyz',
            'item_url_with_token': '/discovery/item/abc?t=1',
            'save_dir': '/tmp/xhs_video_test',
        }
        result = extract.extract_xiaohongshu('http://xhslink.cn/o/abc')
        assert result['partial'] is False
        assert result['transcript'] == '完整转写文本'
        assert result['pipeline_status'] == 'success'
        assert result['cover'] == '/tmp/cover.jpg'
        assert result['video_url'] == 'http://video.mp4'

    @mock.patch('extract._try_xhs_video_cdn_pipeline')
    @mock.patch('extract.resolve_xhs_url')
    def test_extract_video_pipeline_failure_falls_back(self, mock_resolve, mock_pipeline):
        """CDN→ASR 失败时降级到 partial=True。"""
        mock_resolve.return_value = {
            'item_id': 'abc', 'kind': 'video', 'canonical_url': 'http://x',
        }
        mock_pipeline.return_value = {'ok': False, 'stage': 'transcribe', 'error': 'timeout'}
        result = extract.extract_xiaohongshu('http://xhslink.cn/o/abc')
        assert result['partial'] is True
        assert result['pipeline_status'] == 'failed'
        assert result['pipeline_stage'] == 'transcribe'
        assert 'CDN→ASR 链路尝试失败' in result['note']

    @mock.patch('extract.resolve_xhs_url')
    def test_extract_non_video_skips_pipeline(self, mock_resolve):
        """kind != 'video' 不走 CDN 链路（图文笔记无视频流）。"""
        mock_resolve.return_value = {
            'item_id': 'abc', 'kind': 'note', 'canonical_url': 'http://x',
        }
        with mock.patch('extract._try_xhs_video_cdn_pipeline') as mock_pipeline:
            result = extract.extract_xiaohongshu('http://xhslink.cn/o/abc')
            mock_pipeline.assert_not_called()
            assert result['partial'] is True

    @mock.patch('extract.resolve_xhs_url')
    def test_extract_disabled_via_env(self, mock_resolve):
        """XHS_VIDEO_CDN=0 时不走 CDN 链路。"""
        import os
        mock_resolve.return_value = {
            'item_id': 'abc', 'kind': 'video', 'canonical_url': 'http://x',
        }
        with mock.patch.dict(os.environ, {'XHS_VIDEO_CDN': '0'}):
            with mock.patch('extract._try_xhs_video_cdn_pipeline') as mock_pipeline:
                result = extract.extract_xiaohongshu('http://xhslink.cn/o/abc')
                mock_pipeline.assert_not_called()
                assert result['partial'] is True


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
