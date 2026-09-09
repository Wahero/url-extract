"""ASR backend abstraction (v2.6.1) — 跨平台 STT 调度器。

设计原则：
  - 全平台是基础，不能用某个 agent 限死项目整体功能
  - apple-speech 是 Mac/iOS 检测到时的优选路径（本地、低延迟、无 API key）
  - 其他平台用 whisper（pip install openai-whisper，跨平台）
  - Google Cloud Speech 是可选云端 backend（需 API key）

backend 接口约定：每个 backend 必须返回 dict：
  - 成功：{'ok': True, 'text': str, 'segments': list, 'duration_seconds': float}
  - 失败：{'ok': False, 'error': str}

backend 检测优先级（XHS_ASR_BACKEND=auto 时）：
  1. apple-speech（二进制存在即视为 Mac/iOS）
  2. whisper（whisper / whisper-cpp / main 任一二进制）
  3. google-cloud-speech（GOOGLE_CLOUD_API_KEY 或 GOOGLE_APPLICATION_CREDENTIALS）
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import urllib.error
from typing import Any

# 默认 ASR 超时（秒）
_ASR_DEFAULT_TIMEOUT = 150


class ASRBackend:
    """ASR backend 抽象基类。

    子类需设置 name 属性，并实现 transcribe() 方法。
    available 属性应在 __init__ 中根据环境探测设置。
    """

    name = 'unknown'

    def __init__(self):
        self.available = False
        self.reason_unavailable = ''

    def transcribe(self, audio_path: str, language: str = 'zh-CN') -> dict:
        """转写音频，返回 dict。失败时 ok=False, error=str。"""
        raise NotImplementedError


class AppleSpeechBackend(ASRBackend):
    """Apple Speech.framework via apple-speech CLI（Mac/iOS only）。

    在 Minis iOS 沙箱里：/usr/local/bin/apple-speech 是 0 字节 stub，
    Minis 客户端拦截 exec 调用并路由到 iOS Speech.framework。
    在普通 Mac 上：需要安装 Minis 或类似的 Apple Speech 包装工具。

    平台检测：只要 apple-speech 二进制存在即视为 Apple 平台。
    """

    name = 'apple-speech'

    def __init__(self):
        self.binary = shutil.which('apple-speech')
        self.available = self.binary is not None
        if not self.available:
            self.reason_unavailable = 'apple-speech binary not in PATH'

    def transcribe(self, audio_path: str, language: str = 'zh-CN') -> dict:
        if not self.available:
            return {'ok': False, 'error': self.reason_unavailable}
        if not os.path.exists(audio_path):
            return {'ok': False, 'error': f'audio file missing: {audio_path}'}

        cmd = ['apple-speech', 'transcribe',
               '--source', audio_path,
               '--language', language]
        # 默认不开 --on-device（实测该模式有截断），用 env var 显式开启
        if os.environ.get('XHS_ASR_ON_DEVICE') == '1':
            cmd.append('--on-device')

        try:
            result = subprocess.run(cmd, capture_output=True, timeout=_ASR_DEFAULT_TIMEOUT)
            if result.returncode != 0:
                return {'ok': False, 'error': result.stderr.decode('utf-8', errors='ignore')[:200]}
            out = result.stdout.decode('utf-8', errors='ignore').strip()
            data = json.loads(out)
            payload = data.get('data', data)
            return {
                'ok': True,
                'text': payload.get('text', '') or '',
                'segments': payload.get('segments', []) or [],
                'duration_seconds': payload.get('duration_seconds', 0) or 0,
            }
        except subprocess.TimeoutExpired:
            return {'ok': False, 'error': 'apple-speech timeout'}
        except Exception as e:
            return {'ok': False, 'error': str(e)[:200]}


class WhisperBackend(ASRBackend):
    """OpenAI Whisper via whisper CLI（跨平台：Linux / macOS / Windows）。

    安装：
      - Python:  pip install openai-whisper（提供 `whisper` 命令）
      - Binary:  whisper.cpp（提供 `whisper-cpp` 或 `main` 二进制）

    模型选择（env var WHISPER_MODEL，默认 'base'）：
      tiny / base / small / medium / large
      模型越大越准越慢，首次运行会自动下载
    """

    name = 'whisper'

    def __init__(self):
        # 按优先级探测 whisper 二进制
        self.binary = (
            shutil.which('whisper')
            or shutil.which('whisper-cpp')
            or shutil.which('main')  # whisper.cpp 默认二进制名
        )
        self.available = self.binary is not None
        if not self.available:
            self.reason_unavailable = (
                'whisper binary not found. Install: pip install openai-whisper'
                ' (or download whisper.cpp binary)'
            )

    def transcribe(self, audio_path: str, language: str = 'zh-CN') -> dict:
        if not self.available:
            return {'ok': False, 'error': self.reason_unavailable}
        if not os.path.exists(audio_path):
            return {'ok': False, 'error': f'audio file missing: {audio_path}'}

        model = os.environ.get('WHISPER_MODEL', 'base')
        # whisper CLI 期望 zh 不是 zh-CN
        whisper_lang = language.split('-')[0]

        tmp_out = tempfile.mkdtemp(prefix='whisper_out_')

        try:
            # whisper CLI 输出 {basename}.{ext}.json / .txt / .vtt 到 output_dir
            cmd = [
                self.binary,
                audio_path,
                '--model', model,
                '--language', whisper_lang,
                '--output_format', 'json',
                '--output_dir', tmp_out,
            ]
            # quiet 模式（whisper 旧版用 --quiet，新版用 --verbose False）
            if self._supports_flag('--quiet'):
                cmd.append('--quiet')
            elif self._supports_flag('--verbose'):
                cmd += ['--verbose', 'False']

            result = subprocess.run(cmd, capture_output=True, timeout=_ASR_DEFAULT_TIMEOUT * 2)
            if result.returncode != 0:
                return {'ok': False,
                        'error': result.stderr.decode('utf-8', errors='ignore')[:200]}

            # 解析输出 JSON（whisper CLI 输出 {basename}.json）
            base = os.path.splitext(os.path.basename(audio_path))[0]
            json_path = os.path.join(tmp_out, f'{base}.json')
            if not os.path.exists(json_path):
                return {'ok': False,
                        'error': f'whisper output not found: {json_path}'}

            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            return {
                'ok': True,
                'text': data.get('text', '') or '',
                'segments': data.get('segments', []) or [],
                'duration_seconds': data.get('duration', 0) or 0,
            }
        except subprocess.TimeoutExpired:
            return {'ok': False, 'error': 'whisper timeout'}
        except Exception as e:
            return {'ok': False, 'error': str(e)[:200]}

    def _supports_flag(self, flag: str) -> bool:
        """快速探测 whisper CLI 是否支持某个 flag（避免传错导致失败）。"""
        try:
            result = subprocess.run(
                [self.binary, '--help'],
                capture_output=True, timeout=5, text=True,
            )
            return flag in result.stdout
        except Exception:
            return False


class GoogleCloudSpeechBackend(ASRBackend):
    """Google Cloud Speech-to-Text via REST API（跨平台云端）。

    需要环境变量：
      - GOOGLE_CLOUD_API_KEY（API key 认证）
      - 或 GOOGLE_APPLICATION_CREDENTIALS（service account JSON 文件路径）

    走 REST API 而非 SDK，避免引入 google-cloud-speech 重型依赖。
    """

    name = 'google-cloud-speech'
    API_URL = 'https://speech.googleapis.com/v1/speech:recognize'

    def __init__(self):
        self.api_key = os.environ.get('GOOGLE_CLOUD_API_KEY')
        self.creds_file = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
        self.available = bool(
            self.api_key
            or (self.creds_file and os.path.exists(self.creds_file))
        )
        if not self.available:
            self.reason_unavailable = (
                'GOOGLE_CLOUD_API_KEY or GOOGLE_APPLICATION_CREDENTIALS not set'
            )

    def transcribe(self, audio_path: str, language: str = 'zh-CN') -> dict:
        if not self.available:
            return {'ok': False, 'error': self.reason_unavailable}
        if not os.path.exists(audio_path):
            return {'ok': False, 'error': f'audio file missing: {audio_path}'}

        try:
            import base64
        except ImportError:
            return {'ok': False, 'error': 'urllib not available'}

        try:
            with open(audio_path, 'rb') as f:
                audio_b64 = base64.b64encode(f.read()).decode('ascii')

            # Google STT language: 'zh-CN' 直接用
            payload = {
                'config': {
                    'encoding': 'LINEAR16',  # wav 默认 16-bit PCM
                    'sampleRateHertz': 16000,
                    'languageCode': language,
                    'enableWordTimeOffsets': True,
                },
                'audio': {'content': audio_b64},
            }

            url = f'{self.API_URL}?key={self.api_key}' if self.api_key else self.API_URL
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode('utf-8'),
                headers={'Content-Type': 'application/json'},
                method='POST',
            )
            with urllib.request.urlopen(req, timeout=_ASR_DEFAULT_TIMEOUT) as resp:
                result = json.loads(resp.read())

            # 解析 Google STT 响应
            results = result.get('results', [])
            full_text = ''.join(r.get('alternatives', [{}])[0].get('transcript', '') for r in results)
            segments = []
            for r in results:
                alt = r.get('alternatives', [{}])[0]
                for w in alt.get('words', []):
                    segments.append({
                        'substring': w.get('word', ''),
                        # Google 返回 startTime/endTime 含 's' 后缀（如 "0.5s"）
                        'timestamp': float(w.get('startTime', '0s').rstrip('s') or 0),
                    })
            return {
                'ok': True,
                'text': full_text,
                'segments': segments,
                'duration_seconds': 0,
            }
        except Exception as e:
            return {'ok': False, 'error': str(e)[:200]}


# Backend 注册表（按优先级）
_DEFAULT_BACKEND_ORDER = [
    AppleSpeechBackend,
    WhisperBackend,
    GoogleCloudSpeechBackend,
]


def list_backends() -> list:
    """列出所有 backend 实例（含 available 状态）。"""
    return [cls() for cls in _DEFAULT_BACKEND_ORDER]


def detect_best_backend() -> ASRBackend:
    """自动检测最佳 backend。

    策略（XHS_ASR_BACKEND=auto 时）：
      1. 优先 apple-speech（Mac/iOS 标识——只要二进制存在就视为 Apple 平台）
      2. 其次 whisper（全平台可用，装了 pip openai-whisper 即可）
      3. 最后 google-cloud-speech（云端，需 API key）

    XHS_ASR_BACKEND 可强制指定：'apple-speech' / 'whisper' / 'google-cloud-speech'
    指定后如果 backend 不可用，返回该 backend 实例（available=False），
    让调用方决定是 fallback 还是报错。
    """
    requested = os.environ.get('XHS_ASR_BACKEND', 'auto').lower().strip()

    if requested != 'auto':
        # 用户显式指定
        for cls in _DEFAULT_BACKEND_ORDER:
            if cls.name == requested:
                return cls()
        # 未知 backend 名 → fallthrough to auto

    # auto 模式：按优先级返回第一个 available
    for cls in _DEFAULT_BACKEND_ORDER:
        backend = cls()
        if backend.available:
            return backend

    # 全部不可用，返回第一个（让调用方看到 available=False + reason）
    return _DEFAULT_BACKEND_ORDER[0]()


def transcribe_with_fallback(audio_path: str, language: str = 'zh-CN') -> dict:
    """按优先级尝试所有可用 backend，失败时 fallback 到下一个。

    返回 dict：
      - 成功：{'ok': True, 'text': ..., 'segments': [...], 'backend': 'whisper', ...}
      - 全部失败：{'ok': False, 'error': '...', 'tried': [...]}
    """
    requested = os.environ.get('XHS_ASR_BACKEND', 'auto').lower().strip()

    # 每次调用现取 backend 类（方便测试时 mock.patch 替换类引用）
    backend_classes = [AppleSpeechBackend, WhisperBackend, GoogleCloudSpeechBackend]

    if requested != 'auto':
        # 显式指定：只试该 backend，不 fallback
        for cls in backend_classes:
            if cls.name == requested:
                backend = cls()
                if not backend.available:
                    return {'ok': False,
                            'error': backend.reason_unavailable,
                            'tried': [backend.name]}
                result = backend.transcribe(audio_path, language)
                if result.get('ok'):
                    result['backend'] = backend.name
                else:
                    result.setdefault('tried', [backend.name])
                return result
        return {'ok': False,
                'error': f'unknown backend: {requested}',
                'tried': []}

    # auto 模式：按顺序 fallback
    tried = []
    for cls in backend_classes:
        backend = cls()
        if not backend.available:
            continue
        result = backend.transcribe(audio_path, language)
        tried.append(backend.name)
        if result.get('ok'):
            result['backend'] = backend.name
            return result
        # 失败就继续 fallback（仅 auto 模式下）

    return {
        'ok': False,
        'error': 'no ASR backend available',
        'tried': tried,
        'hint': 'install whisper (pip install openai-whisper) or set XHS_ASR_BACKEND',
    }


def is_apple_platform() -> bool:
    """是否运行在 Apple 平台（Mac/iOS）。

    判断依据：apple-speech 二进制存在。这是 Minis iOS 沙箱 / 装有 Minis 的 Mac
    的最强信号。其他 Mac 用户需自己装 Apple Speech 包装。
    """
    return shutil.which('apple-speech') is not None