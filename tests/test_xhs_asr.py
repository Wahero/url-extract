"""XHS ASR backend abstraction tests (v2.6.1)。

覆盖：
- 各 backend 的 available 检测（mock shutil.which）
- AppleSpeechBackend.transcribe 调用 subprocess
- WhisperBackend.transcribe 调用 subprocess + 解析 JSON
- GoogleCloudSpeechBackend.transcribe 调用 urllib
- transcribe_with_fallback 的 fallback 链行为
- XHS_ASR_BACKEND 环境变量优先级
- is_apple_platform 探测
"""
import json
import os
import sys
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import xhs_asr  # noqa: E402


# ============================================================
# backend 可用性探测
# ============================================================

class TestBackendAvailability:
    def test_apple_speech_available_when_binary_present(self):
        """apple-speech 在 PATH 时视为 Apple 平台 + backend 可用。"""
        with mock.patch('xhs_asr.shutil.which', return_value='/usr/local/bin/apple-speech'):
            backend = xhs_asr.AppleSpeechBackend()
            assert backend.available is True
            assert backend.binary == '/usr/local/bin/apple-speech'

    def test_apple_speech_unavailable_records_reason(self):
        with mock.patch('xhs_asr.shutil.which', return_value=None):
            backend = xhs_asr.AppleSpeechBackend()
            assert backend.available is False
            assert 'apple-speech' in backend.reason_unavailable

    def test_whisper_finds_cli_binary(self):
        with mock.patch('xhs_asr.shutil.which', side_effect=lambda b: '/usr/bin/whisper' if b == 'whisper' else None):
            backend = xhs_asr.WhisperBackend()
            assert backend.available is True

    def test_whisper_falls_back_to_whisper_cpp(self):
        with mock.patch('xhs_asr.shutil.which', side_effect=lambda b: '/usr/bin/whisper-cpp' if b == 'whisper-cpp' else None):
            backend = xhs_asr.WhisperBackend()
            assert backend.available is True

    def test_whisper_unavailable(self):
        with mock.patch('xhs_asr.shutil.which', return_value=None):
            backend = xhs_asr.WhisperBackend()
            assert backend.available is False
            assert 'openai-whisper' in backend.reason_unavailable

    def test_google_unavailable_without_creds(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            backend = xhs_asr.GoogleCloudSpeechBackend()
            assert backend.available is False

    def test_google_available_with_api_key(self):
        with mock.patch.dict(os.environ, {'GOOGLE_CLOUD_API_KEY': 'test-key'}, clear=True):
            backend = xhs_asr.GoogleCloudSpeechBackend()
            assert backend.available is True

    def test_google_available_with_credentials_file(self, tmp_path):
        creds = tmp_path / 'creds.json'
        creds.write_text('{}')
        with mock.patch.dict(os.environ, {'GOOGLE_APPLICATION_CREDENTIALS': str(creds)}, clear=True):
            backend = xhs_asr.GoogleCloudSpeechBackend()
            assert backend.available is True

    def test_google_unavailable_with_nonexistent_creds_file(self):
        with mock.patch.dict(os.environ, {'GOOGLE_APPLICATION_CREDENTIALS': '/nonexistent/path'}, clear=True):
            backend = xhs_asr.GoogleCloudSpeechBackend()
            assert backend.available is False


# ============================================================
# AppleSpeechBackend.transcribe
# ============================================================

class TestAppleSpeechTranscribe:
    @mock.patch('xhs_asr.subprocess.run')
    @mock.patch('xhs_asr.shutil.which', return_value='/usr/local/bin/apple-speech')
    def test_transcribe_success(self, mock_which, mock_run, tmp_path):
        audio = tmp_path / 'audio.wav'
        audio.write_bytes(b'fake')
        mock_run.return_value = mock.Mock(
            returncode=0,
            stdout=json.dumps({
                'data': {
                    'text': '转写文本',
                    'segments': [{'substring': '转写', 'timestamp': 0.0}],
                    'duration_seconds': 60.0,
                }
            }).encode('utf-8'),
            stderr=b'',
        )
        backend = xhs_asr.AppleSpeechBackend()
        result = backend.transcribe(str(audio))
        assert result['ok'] is True
        assert result['text'] == '转写文本'
        assert len(result['segments']) == 1

    @mock.patch('xhs_asr.subprocess.run')
    @mock.patch('xhs_asr.shutil.which', return_value='/usr/local/bin/apple-speech')
    def test_transcribe_failure_returns_error(self, mock_which, mock_run, tmp_path):
        audio = tmp_path / 'audio.wav'
        audio.write_bytes(b'fake')
        mock_run.return_value = mock.Mock(returncode=1, stderr=b'error message', stdout=b'')
        backend = xhs_asr.AppleSpeechBackend()
        result = backend.transcribe(str(audio))
        assert result['ok'] is False
        assert 'error' in result

    @mock.patch('xhs_asr.shutil.which', return_value=None)
    def test_transcribe_returns_error_when_unavailable(self, mock_which, tmp_path):
        audio = tmp_path / 'audio.wav'
        audio.write_bytes(b'fake')
        backend = xhs_asr.AppleSpeechBackend()
        result = backend.transcribe(str(audio))
        assert result['ok'] is False

    def test_transcribe_returns_error_when_audio_missing(self):
        with mock.patch('xhs_asr.shutil.which', return_value='/usr/local/bin/apple-speech'):
            backend = xhs_asr.AppleSpeechBackend()
            result = backend.transcribe('/nonexistent/audio.wav')
            assert result['ok'] is False
            assert 'missing' in result['error']

    @mock.patch('xhs_asr.subprocess.run')
    @mock.patch('xhs_asr.shutil.which', return_value='/usr/local/bin/apple-speech')
    def test_on_device_flag_added_when_env_set(self, mock_which, mock_run, tmp_path):
        audio = tmp_path / 'audio.wav'
        audio.write_bytes(b'fake')
        mock_run.return_value = mock.Mock(returncode=0, stdout=b'{"data":{"text":"","segments":[]}}', stderr=b'')
        with mock.patch.dict(os.environ, {'XHS_ASR_ON_DEVICE': '1'}):
            backend = xhs_asr.AppleSpeechBackend()
            backend.transcribe(str(audio))
            args = mock_run.call_args[0][0]
            assert '--on-device' in args


# ============================================================
# WhisperBackend.transcribe
# ============================================================

class TestWhisperTranscribe:
    @mock.patch('xhs_asr.subprocess.run')
    @mock.patch('xhs_asr.shutil.which', return_value='/usr/bin/whisper')
    def test_transcribe_success(self, mock_which, mock_run, tmp_path):
        audio = tmp_path / 'audio.wav'
        audio.write_bytes(b'fake')

        def fake_run(cmd, **kwargs):
            output_dir = cmd[cmd.index('--output_dir') + 1]
            base = os.path.splitext(os.path.basename(str(audio)))[0]
            json_path = os.path.join(output_dir, f'{base}.json')
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump({
                    'text': 'whisper 转写',
                    'segments': [{'text': 'whisper 转写', 'start': 0.0, 'end': 1.0}],
                    'duration': 30.0,
                }, f)
            return mock.Mock(returncode=0, stdout=b'', stderr=b'')

        mock_run.side_effect = fake_run
        backend = xhs_asr.WhisperBackend()
        result = backend.transcribe(str(audio))
        assert result['ok'] is True
        assert result['text'] == 'whisper 转写'

    @mock.patch('xhs_asr.shutil.which', return_value=None)
    def test_transcribe_unavailable_returns_error(self, mock_which, tmp_path):
        audio = tmp_path / 'audio.wav'
        audio.write_bytes(b'fake')
        backend = xhs_asr.WhisperBackend()
        result = backend.transcribe(str(audio))
        assert result['ok'] is False


# ============================================================
# GoogleCloudSpeechBackend
# ============================================================

class TestGoogleCloudTranscribe:
    @mock.patch('xhs_asr.urllib.request.urlopen')
    def test_transcribe_success_with_api_key(self, mock_urlopen, tmp_path):
        audio = tmp_path / 'audio.wav'
        audio.write_bytes(b'fake')

        mock_resp = mock.MagicMock()
        mock_resp.read.return_value = json.dumps({
            'results': [{
                'alternatives': [{
                    'transcript': 'google 转写',
                    'words': [
                        {'word': 'google', 'startTime': '0.0s'},
                        {'word': '转写', 'startTime': '0.5s'},
                    ],
                }],
            }],
        }).encode('utf-8')
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        with mock.patch.dict(os.environ, {'GOOGLE_CLOUD_API_KEY': 'test-key'}, clear=True):
            backend = xhs_asr.GoogleCloudSpeechBackend()
            result = backend.transcribe(str(audio))
            assert result['ok'] is True
            assert result['text'] == 'google 转写'
            assert len(result['segments']) == 2

    def test_transcribe_unavailable_returns_error(self, tmp_path):
        audio = tmp_path / 'audio.wav'
        audio.write_bytes(b'fake')
        with mock.patch.dict(os.environ, {}, clear=True):
            backend = xhs_asr.GoogleCloudSpeechBackend()
            result = backend.transcribe(str(audio))
            assert result['ok'] is False


# ============================================================
# detect_best_backend & transcribe_with_fallback
# ============================================================

class TestDetectionAndFallback:
    def test_detect_picks_apple_speech_when_present(self):
        """Mac/iOS 环境（有 apple-speech）→ 返回 AppleSpeechBackend。"""
        with mock.patch('xhs_asr.shutil.which', side_effect=lambda b: '/usr/local/bin/apple-speech' if b == 'apple-speech' else None):
            with mock.patch.dict(os.environ, {'XHS_ASR_BACKEND': 'auto'}, clear=True):
                result = xhs_asr.detect_best_backend()
                assert result.available is True
                assert result.name == 'apple-speech'

    def test_detect_falls_back_to_whisper_when_no_apple(self):
        """非 Apple 平台 → 返回 WhisperBackend。"""
        with mock.patch('xhs_asr.shutil.which', side_effect=lambda b: '/usr/bin/whisper' if b == 'whisper' else None):
            with mock.patch.dict(os.environ, {'XHS_ASR_BACKEND': 'auto'}, clear=True):
                result = xhs_asr.detect_best_backend()
                assert result.name == 'whisper'
                assert result.available is True

    def test_explicit_backend_request_respected(self):
        """XHS_ASR_BACKEND=whisper 即使有 apple-speech 也会选 whisper。"""
        whisper_inst = xhs_asr.WhisperBackend()
        with mock.patch('xhs_asr.shutil.which', return_value='/usr/bin/whisper'):
            with mock.patch('xhs_asr.WhisperBackend', return_value=whisper_inst):
                with mock.patch.dict(os.environ, {'XHS_ASR_BACKEND': 'whisper'}, clear=True):
                    result = xhs_asr.detect_best_backend()
                    assert result.name == 'whisper'

    @mock.patch('xhs_asr.shutil.which', side_effect=lambda b: '/usr/bin/whisper' if b == 'whisper' else None)
    def test_fallback_chain_skips_unavailable(self, mock_which):
        """auto 模式：跳过 unavailable 的 backend，调用下一个。"""
        whisper_inst = xhs_asr.WhisperBackend()
        whisper_inst.transcribe = mock.Mock(return_value={'ok': True, 'text': 'whisper 输出', 'segments': []})
        with mock.patch('xhs_asr.WhisperBackend', return_value=whisper_inst):
            with mock.patch('xhs_asr.AppleSpeechBackend', return_value=mock.Mock(available=False)):
                with mock.patch('xhs_asr.GoogleCloudSpeechBackend', return_value=mock.Mock(available=False)):
                    with mock.patch.dict(os.environ, {'XHS_ASR_BACKEND': 'auto'}, clear=True):
                        result = xhs_asr.transcribe_with_fallback('/tmp/audio.wav')
                        assert result['ok'] is True
                        assert result['backend'] == 'whisper'
                        assert result['text'] == 'whisper 输出'

    @mock.patch('xhs_asr.shutil.which', return_value='/usr/local/bin/apple-speech')
    def test_explicit_backend_does_not_fallback(self, mock_which):
        """显式指定 backend 失败时，不 fallback 到其他 backend。"""
        with mock.patch.dict(os.environ, {'XHS_ASR_BACKEND': 'apple-speech'}, clear=True):
            with mock.patch.object(xhs_asr.AppleSpeechBackend, 'transcribe',
                                   return_value={'ok': False, 'error': 'apple-speech 失败'}):
                result = xhs_asr.transcribe_with_fallback('/tmp/audio.wav')
                assert result['ok'] is False
                assert result['error'] == 'apple-speech 失败'
                assert result['tried'] == ['apple-speech']

    def test_unknown_backend_name_returns_error(self):
        with mock.patch.dict(os.environ, {'XHS_ASR_BACKEND': 'nonexistent'}, clear=True):
            result = xhs_asr.transcribe_with_fallback('/tmp/audio.wav')
            assert result['ok'] is False
            assert 'unknown backend' in result['error']

    def test_all_unavailable_returns_no_backend_error(self):
        """全部 backend 不可用时，提示用户安装 whisper。"""
        with mock.patch('xhs_asr.shutil.which', return_value=None):
            with mock.patch.dict(os.environ, {'XHS_ASR_BACKEND': 'auto'}, clear=True):
                result = xhs_asr.transcribe_with_fallback('/tmp/audio.wav')
                assert result['ok'] is False
                assert 'no ASR backend' in result['error']
                assert result['tried'] == []


# ============================================================
# is_apple_platform
# ============================================================

class TestIsApplePlatform:
    def test_returns_true_when_apple_speech_binary_exists(self):
        with mock.patch('xhs_asr.shutil.which', return_value='/usr/local/bin/apple-speech'):
            assert xhs_asr.is_apple_platform() is True

    def test_returns_false_when_no_apple_speech(self):
        with mock.patch('xhs_asr.shutil.which', return_value=None):
            assert xhs_asr.is_apple_platform() is False


# ============================================================
# list_backends
# ============================================================

class TestListBackends:
    def test_returns_all_three_backends(self):
        with mock.patch('xhs_asr.shutil.which', side_effect=lambda b: '/usr/bin/whisper' if b == 'whisper' else None):
            with mock.patch.dict(os.environ, {'GOOGLE_CLOUD_API_KEY': 'k'}, clear=True):
                backends = xhs_asr.list_backends()
                assert len(backends) == 3
                names = [b.name for b in backends]
                assert 'apple-speech' in names
                assert 'whisper' in names
                assert 'google-cloud-speech' in names