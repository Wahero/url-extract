#!/usr/bin/env python3
"""
通用内容抽取脚本 v2.5.2
支持来源：B站视频、GitHub仓库、一般网页URL、腾讯微视视频（降级方案）
增强：抽取后自动导入 IMA 知识库，支持上传 Markdown 精华文档到「RAW」个人知识库

v2.5.1 变更：修复 --ima-raw 在 B站无字幕时仍上传空壳 Markdown 的 bug，增加安全守卫：无字幕且无 --ima-raw-md 时阻止上传并提示正确流程。
v2.5 变更：修复 --ima-raw 上传 Markdown 不完整 bug（B站无字幕时 _build_markdown_content() 只输出标题+空壳+评论）；
         重写 _build_markdown_content() 为来源感知的完整结构化输出（视频概览表格/字幕全文/标签/评论精选/仓库概览等）；
         新增 --ima-raw-md 参数，支持指定外部 Markdown 文件优先上传 agent 生成的高质量精华文档。
v2.4 变更：IMA 凭证改为仅从环境变量读取，不持久化存储；--ima-raw 上传完整 Markdown 文档而非 URL。
v2.3 变更：新增 --ima-raw 自动导入 IMA「RAW」个人知识库，导入前去重检查。
v2.2 变更：集成 IMA OpenAPI，支持抽取结果一键导入知识库（--upload-ima）。
v2.1 变更：集成 defuddle CLI 替代 WebFetch，实现本地化网页内容提取，
输出更干净、更省 token 的 Markdown/JSON 内容。

用法：
    python3 extract.py "<链接>" --output <json路径>
    python3 extract.py "https://b23.tv/xxx" --output result.json
    python3 extract.py "https://example.com/article" --output result.json --upload-ima --ima-kb "我的知识库"
    python3 extract.py "https://example.com/article" --output result.json --ima-raw

    IMA 凭证通过环境变量提供（不持久化）：
    export IMA_OPENAPI_CLIENTID="你的ClientID"
    export IMA_OPENAPI_APIKEY="你的APIKey"

依赖：requests, beautifulsoup4, defuddle (npm CLI)
"""
import sys
import os
import re
import json
import subprocess
import argparse
import logging
import time
import hashlib
import urllib.parse
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

try:
    from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
    _HAS_TENACITY = True
except ImportError:
    _HAS_TENACITY = False
    # 提供 no-op 占位，让无 tenacity 环境下代码仍可 import（仅失去重试能力）
    def retry(*dargs, **dkwargs):
        if len(dargs) == 1 and callable(dargs[0]) and not dkwargs:
            return dargs[0]
        def decorator(fn):
            return fn
        return decorator
    def stop_after_attempt(_): return None
    def wait_exponential(**_): return None
    def retry_if_exception_type(_): return None

# 必要的核心依赖：直接 import 让 ImportError 自然抛出。
# 库使用者可以 try/except ImportError 捕获，应用使用者也会看到清晰的错误。
import requests
import jinja2

CST = timezone(timedelta(hours=8))

# 版本号（单一来源，与 pyproject.toml 保持同步）
__version__ = '2.5.2'

# 通用 UA（所有请求都用）
_UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

# 通用 headers（不含 Referer，给非 B站请求用，避免被跨源拒）
BASE_HEADERS = {'User-Agent': _UA}

# B站专用 headers（含 Referer，给 B站 API 用）
HEADERS = {**BASE_HEADERS, 'Referer': 'https://www.bilibili.com/'}
BILI_HEADERS = HEADERS  # 别名，更显式


# 非 B站请求的统一重试包装（URLError/ConnectionError/Timeout 自动重试）
_DEFAULT_RETRY = int(os.environ.get('EXTRACT_HTTP_RETRY', '2'))


def safe_request(method: str, url: str, max_retries: int = _DEFAULT_RETRY, backoff: float = 1.0, **kwargs):
    """带重试的 requests 调用。

    重试策略：
      - URLError / ConnectionError / Timeout → 自动重试（瞬时网络问题居多）
      - HTTPError（4xx/5xx）→ 不重试（业务错误，重试无意义）
      - 其它异常 → 透传

    通过环境变量 EXTRACT_HTTP_RETRY 可调整重试次数（默认 2，共 3 次调用）。
    """
    import time as _time
    last_exc: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            r = requests.request(method, url, **kwargs)
            r.raise_for_status()
            return r
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            last_exc = e
            if attempt >= max_retries:
                print(f"[retry] {method} {url} exhausted {max_retries} retries: {e}", file=sys.stderr)
                raise
            print(f"[retry] {method} {url} attempt {attempt}/{max_retries} failed: {e}", file=sys.stderr)
            _time.sleep(backoff * attempt)
        except requests.exceptions.HTTPError:
            raise  # 4xx/5xx 不重试
    # 不会到这里（最后一次失败 raise），但类型检查要 return
    if last_exc:
        raise last_exc
    return None  # type: ignore

# B站 Cookie 全局状态（可选，由 set_bili_cookies() 注入）
# 用途：未登录 IP 容易被 B 站风控（-352/-412/-799/-101），
#      注入 SESSDATA 后可大幅降低风控触发概率。
_BILI_COOKIES = {
    'SESSDATA': None,
    'bili_jct': None,
    'DedeUserID': None,
    'DedeUserID__ckMd5': None,
}

# B站风控响应码（code 字段非 0 时表示风控或鉴权失败）
# 完整列表参考 https://github.com/SocialSisterYi/bilibili-API-collect/blob/master/docs/misc/errcode.md
_BILI_RISK_CODES = {
    -101: '未登录或登录已过期（Cookie 缺失或失效）',
    -352: '风控等级升级（请稍后重试或注入 SESSDATA）',
    -412: '请求被拦截（IP 触发风控）',
    -799: '请求过于频繁（被限流）',
    -509: '请求频率超限（限流）',
    -1200: 'API 调用被风控（需 SESSDATA）',
}

# 模板与来源前缀
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(_SCRIPT_DIR, 'templates')
_SOURCE_PREFIX = {
    'bilibili': 'B站视频精华_',
    'github': 'GitHub精华_',
    'weishi': '视频精华_',
    'webpage': '网页精华_',
    'youtube': 'YouTube精华_',
    'xiaohongshu': '小红书精华_',
    'douyin': '抖音精华_',
}

def set_bili_cookies(sessdata: str = None, bili_jct: str = None, dedeuserid: str = None, dedeuserid_ckmd5: str = None) -> None:
    """注入 B站 Cookie（用于缓解风控）。任一参数为 None 则不更新该项。

    推荐通过命令行参数 --sessdata / --bili-jct / --dedeuserid 间接调用。
    也可通过环境变量 BILIBILI_SESSDATA / BILIBILI_BILI_JCT / BILIBILI_DEDEUSERID 设置。
    """
    if sessdata is not None:
        _BILI_COOKIES['SESSDATA'] = sessdata
    if bili_jct is not None:
        _BILI_COOKIES['bili_jct'] = bili_jct
    if dedeuserid is not None:
        _BILI_COOKIES['DedeUserID'] = dedeuserid
    if dedeuserid_ckmd5 is not None:
        _BILI_COOKIES['DedeUserID__ckMd5'] = dedeuserid_ckmd5


def _bili_cookie_header() -> str:
    """把 _BILI_COOKIES 序列化成 Cookie 请求头字段（只包含非空项）。"""
    parts = []
    for k, v in _BILI_COOKIES.items():
        if v:
            parts.append(f'{k}={v}')
    return '; '.join(parts)


class BilibiliRiskControlError(Exception):
    """B站风控异常。当接口返回 code ∈ _BILI_RISK_CODES 时抛出。"""
    def __init__(self, code: int, message: str, bvid_or_aid: str = ''):
        self.code = code
        self.message = message
        self.bvid_or_aid = bvid_or_aid
        hint = _BILI_RISK_CODES.get(code, '未知风控码')
        super().__init__(f'B站风控触发 (code={code} {hint}): {message} [bvid/aid={bvid_or_aid}]')


def _check_bili_risk(d: dict, bvid_or_aid: str = '') -> None:
    """检查 B站 API 响应是否为风控。是则抛出 BilibiliRiskControlError。"""
    code = d.get('code')
    if code is None or code == 0:
        return
    if code in _BILI_RISK_CODES:
        raise BilibiliRiskControlError(code, d.get('message', ''), bvid_or_aid)
    # 其它非 0 code 仍然静默返回给上层（兼容 tags/replies 等容错场景）


def _bili_retry():
    """tenacity 重试装饰器工厂：3 次，指数退避 1s/2s/4s，仅对 BilibiliRiskControlError 触发重试。"""
    if not _HAS_TENACITY:
        # 无 tenacity 时退化为空装饰器（不重试）
        def decorator(fn):
            return fn
        return decorator
    return retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(BilibiliRiskControlError),
        reraise=True,
    )


def _bili_get(url: str, params: dict, bvid_or_aid: str = '', timeout: int = 15):
    """带 Cookie + 风控检测 + 自动重试的 B站 GET 请求。返回 dict。"""
    headers = dict(HEADERS)
    cookie_str = _bili_cookie_header()
    if cookie_str:
        headers['Cookie'] = cookie_str

    # 如果启用 wbi 签名，先签名（注意：签名后 params 不再可变）
    if _WBI_ENABLED:
        params = _wbi_sign(params)

    @_bili_retry()
    def _do_get():
        r = requests.get(url, params=params, headers=headers, timeout=timeout)
        r.raise_for_status()
        d = r.json()
        _check_bili_risk(d, bvid_or_aid)
        return d
    return _do_get()



# ============================================================
# B站 wbi 签名（参考 socialsisteryi/bilibili-API-collect）
# ============================================================
#
# 用途：view / player / reply 等接口在某些 IP/UA 组合下会被 B 站拦截，
#      即使无 Cookie，加 wbi 签名也能提高成功率。
# 算法：从 nav 接口拿 wbi_img，提取 key，排序 md5 后取前 32 位作 mixin_key，
#      对请求参数按 key 排序 + 编码 + 加 wts + 计算 w_rid。
#
# 启用方式：--wbi-sign on（默认 off，因为 nav 接口本身有调用成本）
#
# 参考：https://github.com/SocialSisterYi/bilibili-API-collect/blob/master/docs/misc/sign/wbi.md

_WBI_MIXIN_KEY_TABLE = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
]

# 模块级缓存：避免每次请求都调 nav 接口
_WBI_MIXIN_KEY_CACHE = {'key': None, 'expires_at': 0}
_WBI_TTL_SEC = 3600  # 1 小时

# 是否启用 wbi 签名的开关（由 --wbi-sign CLI 参数控制）
_WBI_ENABLED = False


def set_wbi_enabled(enabled: bool) -> None:
    """启用/禁用 wbi 签名。"""
    global _WBI_ENABLED
    _WBI_ENABLED = bool(enabled)


def _get_mixin_key() -> str:
    """获取 wbi 签名用的 mixin_key（带 1 小时缓存）。失败时抛 RuntimeError。"""
    now = int(time.time())
    if _WBI_MIXIN_KEY_CACHE['key'] and _WBI_MIXIN_KEY_CACHE['expires_at'] > now:
        return _WBI_MIXIN_KEY_CACHE['key']

    headers = dict(HEADERS)
    cookie_str = _bili_cookie_header()
    if cookie_str:
        headers['Cookie'] = cookie_str
    r = requests.get(
        'https://api.bilibili.com/x/web-interface/nav',
        headers=headers,
        timeout=10,
    )
    r.raise_for_status()
    d = r.json()
    wbi_img = d.get('data', {}).get('wbi_img', {})
    img_url = wbi_img.get('img_url', '')
    sub_url = wbi_img.get('sub_url', '')
    if not img_url or not sub_url:
        raise RuntimeError(f'B站 nav 接口未返回 wbi_img: code={d.get("code")} message={d.get("message")}')

    # 从 URL 末尾提取 32 字符 key（去掉 .png）
    img_key = img_url.rsplit('/', 1)[-1].split('.')[0]
    sub_key = sub_url.rsplit('/', 1)[-1].split('.')[0]
    raw = img_key + sub_key
    mixin = ''.join(raw[i] for i in _WBI_MIXIN_KEY_TABLE)[:32]
    _WBI_MIXIN_KEY_CACHE.update({'key': mixin, 'expires_at': now + _WBI_TTL_SEC})
    return mixin


_SPECIAL_CHARS_RE = re.compile(r"[!'()*]")


def _wbi_sign(params: dict) -> dict:
    """对 params 加 wts + w_rid，返回新 dict（不修改入参）。

    算法：
      1. 加 wts = 当前时间戳
      2. 过滤掉 value 含特殊字符 !'()* 的 key
      3. 按 key 排序
      4. urlencode 后拼接 mixin_key
      5. md5 得到 w_rid
    """
    mixin = _get_mixin_key()
    signed = dict(params)
    signed['wts'] = int(time.time())
    signed = {k: v for k, v in signed.items() if not _SPECIAL_CHARS_RE.search(str(v))}
    signed = dict(sorted(signed.items()))
    query = urllib.parse.urlencode(signed)
    w_rid = hashlib.md5((mixin + query).encode('utf-8')).hexdigest()
    signed['w_rid'] = w_rid
    return signed


# ============================================================
# defuddle CLI 集成（跨平台自动探测）
# ============================================================
#
# 探测顺序：
#   1. 环境变量 DEFUDDLE_BIN（指向 defuddle/npx 可执行文件）
#   2. PATH 中的 defuddle
#   3. PATH 中的 npx / npx.cmd（用 npx defuddle ...）
#   4. 都没找到且 DEFUDDLE_AUTO_INSTALL != 0：尝试 `npm i -g defuddle`
#
# Windows 下 .cmd 文件需 shell=True；通过扩展名自动识别。

import shutil
from pathlib import Path


def _resolve_defuddle() -> tuple[str, bool, str | None]:
    """
    解析 defuddle 入口，返回 (command, needs_shell, workspace_dir)。

    command:
        - 'defuddle ...' 或 'npx defuddle ...' 或绝对路径
    needs_shell:
        - True 表示该命令是 .cmd / .bat（Windows），需要 shell=True
    workspace_dir:
        - 可选的 cwd；找不到时返回 None（让 subprocess.run 用当前目录）
    """
    # 1. 显式覆盖
    override = os.environ.get('DEFUDDLE_BIN')
    if override and os.path.isfile(override):
        return (override, override.lower().endswith(('.cmd', '.bat')), None)

    # 2. PATH 中的 defuddle
    dfd = shutil.which('defuddle')
    if dfd:
        return (dfd, dfd.lower().endswith(('.cmd', '.bat')), None)

    # 3. PATH 中的 npx
    npx = shutil.which('npx') or shutil.which('npx.cmd')
    if npx:
        return (npx, npx.lower().endswith(('.cmd', '.bat')), None)

    # 4. 自动安装（除非显式禁用）
    if os.environ.get('DEFUDDLE_AUTO_INSTALL', '1') != '0':
        npm = shutil.which('npm') or shutil.which('npm.cmd')
        if npm:
            print('[defuddle] 未找到，尝试 npm i -g defuddle ...', file=sys.stderr)
            try:
                subprocess.run(
                    [npm, 'install', '-g', 'defuddle'],
                    timeout=120, check=False,
                )
            except Exception as e:
                print(f'[defuddle] 自动安装失败: {e}', file=sys.stderr)
            dfd = shutil.which('defuddle')
            if dfd:
                return (dfd, dfd.lower().endswith(('.cmd', '.bat')), None)

    return ('', False, None)


def _find_local_node_modules() -> str | None:
    """查找本地 node_modules（含 defuddle 的目录）。用于 NODE_PATH 兜底。"""
    candidates = [
        os.environ.get('DEFUDDLE_NODE_PATH'),
        os.path.join(os.getcwd(), 'node_modules'),
        os.path.expanduser('~/.npm-global/lib/node_modules'),
        # 兼容旧版 workbuddy 布局
        os.path.join(
            os.environ.get('USERPROFILE', os.environ.get('HOME', '/tmp')),
            '.workbuddy', 'binaries', 'node', 'workspace', 'node_modules',
        ),
    ]
    for c in candidates:
        if c and os.path.isdir(os.path.join(c, 'defuddle')):
            return c
    return None


# Lazy init：首次调用时再解析（避免 import 触发 npm install / pip install）
_DEFUDDLE_CACHE = {}


def _get_defuddle_cmd():
    """获取 defuddle CLI 路径（首次调用时解析并缓存）。"""
    if 'cmd' not in _DEFUDDLE_CACHE:
        cmd, shell, cwd = _resolve_defuddle()
        _DEFUDDLE_CACHE['cmd'] = cmd
        _DEFUDDLE_CACHE['shell'] = shell
        _DEFUDDLE_CACHE['cwd'] = cwd
    return _DEFUDDLE_CACHE['cmd'], _DEFUDDLE_CACHE['shell'], _DEFUDDLE_CACHE['cwd']

# ============================================================
# yt-dlp CLI 集成（跨平台自动探测，YouTube 视频抽取）
# ============================================================
#
# 探测顺序：
#   1. 环境变量 YTDLP_BIN（指向 yt-dlp 可执行文件）
#   2. PATH 中的 yt-dlp / yt-dlp.exe
#   3. python -m yt_dlp（fallback，需要 yt_dlp Python 包）
#   4. 都没找到且 YTDLP_AUTO_INSTALL != 0：尝试 pip install yt-dlp
#      (走阿里源 -i https://mirrors.aliyun.com/pypi/simple/ 避免 timeout)
#   5. 都没有 → 返回空字符串，调用方应走 noembed 降级路径

def _resolve_ytdlp() -> str:
    """解析 yt-dlp 入口，返回命令字符串（含路径）。返回空表示未找到。"""
    # 1. 显式覆盖
    override = os.environ.get('YTDLP_BIN')
    if override and os.path.isfile(override):
        return override

    # 2. PATH 中的 yt-dlp
    ytdlp = shutil.which('yt-dlp') or shutil.which('yt-dlp.exe')
    if ytdlp:
        return ytdlp

    # 3. python -m yt_dlp
    try:
        import yt_dlp
        # python -m yt_dlp 走 -m，需要 sys.executable
        return f'"{sys.executable}" -m yt_dlp'
    except ImportError:
        pass

    # 4. 自动安装（除非显式禁用）
    if os.environ.get('YTDLP_AUTO_INSTALL', '1') != '0':
        print('[yt-dlp] 未找到，尝试 pip install yt-dlp ...', file=sys.stderr)
        mirror = 'https://mirrors.aliyun.com/pypi/simple/'
        try:
            subprocess.run(
                [sys.executable, '-m', 'pip', 'install', '--break-system-packages', '-i', mirror, 'yt-dlp'],
                timeout=180, check=False,
            )
        except Exception as e:
            print(f'[yt-dlp] 自动安装失败: {e}', file=sys.stderr)
        # 5. 装完再试
        ytdlp = shutil.which('yt-dlp') or shutil.which('yt-dlp.exe')
        if ytdlp:
            return ytdlp

    return ''


# Lazy init：首次调用时再解析
_YTDLP_CACHE = {}


def _get_ytdlp_cmd():
    """获取 yt-dlp CLI 路径（首次调用时解析并缓存）。"""
    if 'cmd' not in _YTDLP_CACHE:
        _YTDLP_CACHE['cmd'] = _resolve_ytdlp()
    return _YTDLP_CACHE['cmd']


def _run_ytdlp_combined(url: str, timeout: int = 60) -> dict | None:
    """单次 yt-dlp 调用同时拿元数据和字幕。

    优势：单进程 spawn，节省 3-5s 启动开销。
    总超时 60s（之前 dump-json 12s + subtitle 90s = 102s）。

    Returns:
        dict: {'data': <元数据 dict>, 'subtitle': <字幕 dict|None>} 或 None
    """
    if not _get_ytdlp_cmd():
        return None
    import tempfile
    import shlex
    try:
        with tempfile.TemporaryDirectory() as tmp:
            out_template = os.path.join(tmp, '%(id)s.%(ext)s')
            cmd = shlex.split(_get_ytdlp_cmd()) + [
                '--dump-json',           # metadata → stdout
                '--write-info-json',     # 也写 info.json 到 tmp（调试用）
                '--write-auto-sub',      # 拿自动生成字幕
                '--write-subs',          # 也拿手动上传字幕
                '--sub-langs', 'zh-Hans,zh-Hant,zh-CN,zh-TW,en,en-US,en-GB',
                '--sub-format', 'vtt',
                '--no-warnings',
                '--no-playlist',
                '--skip-download',
                '-o', out_template,
                url,
            ]
            # stdout/stderr 用临时文件，避免 PIPE 阻塞
            with tempfile.NamedTemporaryFile(mode='w+', suffix='.json', delete=False) as stdout_f:
                stdout_path = stdout_f.name
            with tempfile.NamedTemporaryFile(mode='w+', suffix='.log', delete=False) as stderr_f:
                stderr_path = stderr_f.name
            try:
                with open(stdout_path, 'w') as out_f, open(stderr_path, 'w') as err_f:
                    proc = subprocess.Popen(cmd, stdout=out_f, stderr=err_f, text=True)
                    try:
                        proc.wait(timeout=timeout)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        try:
                            proc.wait(timeout=1)
                        except subprocess.TimeoutExpired:
                            pass
                        print(f'[yt-dlp] combined 超时 ({timeout}s)', file=sys.stderr)
                        return None
                with open(stdout_path, 'r', encoding='utf-8', errors='ignore') as f:
                    stdout = f.read()
                with open(stderr_path, 'r', encoding='utf-8', errors='ignore') as f:
                    stderr = f.read()
            finally:
                for tp in [stdout_path, stderr_path]:
                    try:
                        os.unlink(tp)
                    except OSError:
                        pass
            if proc.returncode != 0:
                print(f'[yt-dlp] combined 失败 rc={proc.returncode}: {stderr[:200]}', file=sys.stderr)
                return None
            try:
                data = json.loads(stdout)
            except json.JSONDecodeError as e:
                print(f'[yt-dlp] JSON 解析失败: {e}', file=sys.stderr)
                return None

            # 在 tmp 里找 vtt 文件
            subtitle = None
            try:
                vtt_files = [f for f in os.listdir(tmp) if f.endswith('.vtt')]
                if vtt_files:
                    vtt_path = os.path.join(tmp, vtt_files[0])
                    with open(vtt_path, 'r', encoding='utf-8', errors='ignore') as vf:
                        vtt_content = vf.read()
                    parts = vtt_files[0].rsplit('.', 2)
                    lan = parts[1] if len(parts) >= 2 else 'unknown'
                    text = _parse_vtt_to_text(vtt_content)
                    if text:
                        subtitle = {'lan': lan, 'text': text}
            except Exception as e:
                print(f'[yt-dlp] 字幕解析失败: {e}', file=sys.stderr)
            return {'data': data, 'subtitle': subtitle}
    except Exception as e:
        print(f'[yt-dlp] combined 异常: {e}', file=sys.stderr)
        return None


def _parse_vtt_to_text(vtt_content: str) -> str:
    """轻量 WebVTT → 纯文本 parser。
    
    去除 WEBVTT header / 时间戳行 / cue 编号，保留 cue 文本并去重。
    """
    lines = vtt_content.splitlines()
    out = []
    in_cue = False
    for line in lines:
        s = line.strip()
        if not s:
            in_cue = False
            continue
        if s.startswith('WEBVTT') or s.startswith('NOTE'):
            continue
        if '-->' in s and '\n' not in s:  # 时间戳行
            in_cue = True
            continue
        if s.isdigit():  # cue 编号
            continue
        if in_cue:
            # 去除 <c.classname>...</c> 等样式标签
            import re as _re
            clean = re.sub(r'<[^>]+>', '', s)
            if clean and (not out or out[-1] != clean):  # 简单去重
                out.append(clean)
    return '\n'.join(out)


def fetch_youtube_noembed(url: str) -> dict | None:
    """noembed.com 公开代理拿 YouTube 基础元数据（无 yt-dlp 时的降级路径）。
    
    返回 {'title', 'author_name', 'author_url', 'thumbnail_url', 'provider_name'} 或 None。
    """
    try:
        r = safe_request(
            'GET', 'https://noembed.com/embed',
            params={'url': url},
            headers={'User-Agent': 'Mozilla/5.0 (compatible; url-extract/2.6)'},
            timeout=15,
        )
        d = r.json()
        if 'error' in d:
            return None
        return d
    except Exception as e:
        print(f'[noembed] 请求失败: {e}', file=sys.stderr)
        return None



def run_defuddle(url: str, format: str = 'json') -> dict | str | None:
    """
    调用 defuddle CLI 提取网页内容。

    Args:
        url: 目标网页 URL
        format: 输出格式，'json' 返回完整元数据+内容，'markdown' 返回纯 Markdown

    Returns:
        dict (format='json') 或 str (format='markdown')，失败返回 None
    """
    if not _get_defuddle_cmd()[0]:
        print(
            'WARN: defuddle 不可用（未安装且 auto-install 关闭）。'
            '安装方式: npm i -g defuddle',
            file=sys.stderr,
        )
        return None

    # 决定调用方式：npx defuddle / 直接 defuddle / 绝对路径
    cmd_basename = os.path.basename(_get_defuddle_cmd()[0]).lower()
    if cmd_basename == 'npx' or cmd_basename == 'npx.cmd':
        cmd_args = [_get_defuddle_cmd()[0], 'defuddle', 'parse', url]
    else:
        cmd_args = [_get_defuddle_cmd()[0], 'parse', url]

    if format == 'json':
        cmd_args.append('--json')
    elif format == 'markdown':
        cmd_args.append('--markdown')

    env = os.environ.copy()
    local_nm = _find_local_node_modules()
    if local_nm:
        env['NODE_PATH'] = local_nm

    # 修复：_DEFUDDLE_CWD/_DEFUDDLE_SHELL 未定义导致 NameError，
    # 改为从 _get_defuddle_cmd() 缓存解包
    _cmd, _shell, _cwd = _get_defuddle_cmd()

    try:
        result = subprocess.run(
            cmd_args,
            capture_output=True, text=True, timeout=30,
            cwd=_cwd,
            env=env,
            shell=_shell,
        )
        if result.returncode != 0:
            print(
                f"WARN: defuddle CLI 失败 (exit={result.returncode}): "
                f"{result.stderr[:200]}",
                file=sys.stderr,
            )
            return None

        output = result.stdout.strip()
        if not output:
            return None

        if format == 'json':
            return json.loads(output)
        return output

    except subprocess.TimeoutExpired:
        print(f"WARN: defuddle CLI 超时 (URL: {url})", file=sys.stderr)
        return None
    except json.JSONDecodeError as e:
        print(f"WARN: defuddle JSON 解析失败: {e}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"WARN: defuddle CLI 异常: {e}", file=sys.stderr)
        return None


# ============================================================
# URL 验证（防 SSRF + 协议白名单）
# ============================================================

# 禁止访问的地址（防止 SSRF 攻击云元数据 / 内网）
_BLOCKED_HOSTS = {
    '127.0.0.1', 'localhost', '0.0.0.0',
    '169.254.169.254',  # AWS / GCP / Azure 云元数据服务
    '::1', '[::1]',
    'metadata.google.internal',  # GCP
}
_ALLOWED_SCHEMES = {'http', 'https'}


class URLError(Exception):
    """URL 解析/验证失败。"""
    pass


def validate_url(url: str) -> str:
    """验证 URL 的协议和主机名，返回原 URL。

    规则：
      - 协议必须是 http/https（拒绝 file://、ftp:// 等）
      - 主机名必须存在
      - 主机名不能在 _BLOCKED_HOSTS 名单中（防 SSRF）

    Raises:
        URLError: URL 不合法时
    """
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise URLError(f"不支持的协议: {parsed.scheme} (仅支持 http/https)")
    if not parsed.hostname:
        raise URLError(f"URL 缺少主机名: {url}")
    if parsed.hostname.lower() in _BLOCKED_HOSTS:
        raise URLError(f"禁止访问的地址: {parsed.hostname}")
    return url


# ============================================================
# 来源检测
# ============================================================

def detect_source(link: str) -> str:
    """检测链接类型：bilibili / github / weishi / webpage"""
    s = link.strip().lower()
    if 'bilibili.com' in s or 'b23.tv' in s or re.search(r'BV[0-9A-Za-z]{10}', link):
        return 'bilibili'
    if 'github.com' in s:
        return 'github'
    if 'weishi.qq.com' in s or ('v.qq.com' in s and 'wx_tvplugin' in s):
        return 'weishi'
    # YouTube
    if 'youtube.com' in s or 'youtu.be' in s:
        return 'youtube'
    # 小红书 (短链 xhslink.com / 长链 xiaohongshu.com)
    if 'xiaohongshu.com' in s or 'xhslink.com' in s or 'xhslink.cn' in s:
        return 'xiaohongshu'
    # 抖音 (短链 v.douyin.com / 长链 douyin.com / iesdouyin.com)
    if 'douyin.com' in s or 'iesdouyin.com' in s:
        return 'douyin'
    return 'webpage'

# ============================================================
# B站 抽取
# ============================================================

def extract_bilibili(link: str) -> dict:
    """B站视频完整抽取。

    性能优化：tags / subtitle / replies 三个独立请求并行执行（ThreadPoolExecutor）。
    - 串行: 3×平均响应时间 = ~1.5-3s
    - 并行: max(3个响应时间) = ~0.5-1s
    """
    from concurrent.futures import ThreadPoolExecutor
    bvid = resolve_bvid(link)
    info = fetch_bili_video_info(bvid)
    aid = info.get('aid')
    cid = info.get('cid')

    # 三个独立请求并行（subtitle 需要 cid, replies 需要 aid, tags 只要 bvid）
    with ThreadPoolExecutor(max_workers=3) as pool:
        f_tags = pool.submit(fetch_bili_tags, bvid)
        f_subtitle = pool.submit(fetch_bili_subtitle, bvid, cid)
        f_replies = pool.submit(fetch_bili_top_replies, aid)
        tags = f_tags.result()
        subtitle = f_subtitle.result()
        replies = f_replies.result()

    stat = info.get('stat', {})

    return {
        'source': 'bilibili',
        'bvid': bvid,
        'aid': info.get('aid'),
        'cid': info.get('cid'),
        'title': info.get('title', ''),
        'desc': info.get('desc', ''),
        'owner': {
            'name': info.get('owner', {}).get('name', ''),
            'mid': info.get('owner', {}).get('mid', ''),
        },
        'pubdate': fmt_ts(info.get('pubdate', 0)),
        'duration_sec': info.get('duration', 0),
        'tags': tags,
        'stat': {
            'view': stat.get('view', 0),
            'like': stat.get('like', 0),
            'coin': stat.get('coin', 0),
            'favorite': stat.get('favorite', 0),
            'share': stat.get('share', 0),
            'reply': stat.get('reply', 0),
        },
        'pic': info.get('pic', ''),
        'url': f'https://www.bilibili.com/video/{bvid}',
        'subtitle': subtitle,
        'top_replies': replies,
    }

def resolve_bvid(link_or_bvid: str) -> str:
    s = link_or_bvid.strip()
    m = re.search(r'(BV[0-9A-Za-z]{10})', s)
    if m:
        return m.group(1)
    if 'b23.tv' in s or 'bilibili.com' in s:
        r = requests.get(s, headers=HEADERS, allow_redirects=True, timeout=15)
        m = re.search(r'(BV[0-9A-Za-z]{10})', r.url)
        if m:
            return m.group(1)
    raise URLError(f"无法解析BV号: {s}")

def fetch_bili_video_info(bvid: str) -> dict:
    """获取B站视频基本信息。失败时抛 BilibiliRiskControlError 或其它异常。"""
    d = _bili_get(
        'https://api.bilibili.com/x/web-interface/view',
        params={'bvid': bvid},
        bvid_or_aid=bvid,
    )
    if d.get('code') != 0:
        # 走到这里说明不是风控码（_bili_get 已处理风控），是其它业务错误
        raise BilibiliRiskControlError(d.get('code'), d.get('message', ''), bvid)
    return d['data']

def fetch_bili_tags(bvid: str) -> list:
    """获取B站视频标签。失败容错返回空列表。"""
    try:
        d = _bili_get(
            'https://api.bilibili.com/x/tag/archive/tags',
            params={'bvid': bvid},
            bvid_or_aid=bvid,
        )
        if d.get('code') == 0:
            return [t.get('tag_name') for t in d.get('data', [])]
    except Exception:
        # tags 是辅助信息，失败不影响主流程
        pass
    return []

def fetch_bili_subtitle(bvid: str, cid: int) -> dict:
    """获取B站视频字幕。失败容错返回 {'available': False, 'note': ...}。"""
    try:
        d = _bili_get(
            'https://api.bilibili.com/x/player/wbi/v2',
            params={'bvid': bvid, 'cid': cid},
            bvid_or_aid=bvid,
        )
        subs = d.get('data', {}).get('subtitle', {}).get('subtitles', [])
        if subs:
            sub_url = subs[0].get('subtitle_url', '')
            if sub_url.startswith('//'):
                sub_url = 'https:' + sub_url
            elif not sub_url.startswith('http'):
                sub_url = 'https://' + sub_url
            # 字幕内容文件是 B站 CDN，普通 GET 即可（不需要 wbi 签名也不需要风控检测）
            sr = requests.get(sub_url, headers=HEADERS, timeout=15)
            sdata = sr.json()
            lines = [item.get('content', '') for item in sdata.get('body', [])]
            return {
                'available': True,
                'lan': subs[0].get('lan_doc', ''),
                'full_text': '\n'.join(lines),
                'note': '字幕来自B站CC字幕接口',
            }
        return {'available': False, 'note': '该视频UP主未上传字幕，建议结合视频简介、标签及社区资料生成精华内容'}
    except Exception as e:
        return {'available': False, 'note': f'字幕接口请求异常: {e}'}

def fetch_bili_top_replies(aid: int, top_n: int = 3) -> list:
    """获取B站视频热门评论。失败容错返回空列表。"""
    try:
        d = _bili_get(
            'https://api.bilibili.com/x/v2/reply/main',
            params={'type': 1, 'oid': aid, 'mode': 3, 'next': 0, 'ps': 30},
            bvid_or_aid=str(aid),
        )
        if d.get('code') != 0:
            return []
        replies = d.get('data', {}).get('replies') or []
        replies.sort(key=lambda x: x.get('like', 0), reverse=True)
        result = []
        for rp in replies[:top_n]:
            item = {
                'uname': rp.get('member', {}).get('uname', ''),
                'mid': rp.get('member', {}).get('mid', ''),
                'like': rp.get('like', 0),
                'content': rp.get('content', {}).get('message', ''),
                'rcount': rp.get('rcount', 0),
                'ctime': rp.get('ctime', 0),
            }
            sub_replies = rp.get('replies') or []
            if sub_replies:
                sub_top = max(sub_replies, key=lambda x: x.get('like', 0))
                item['top_sub_reply'] = {
                    'uname': sub_top.get('member', {}).get('uname', ''),
                    'like': sub_top.get('like', 0),
                    'content': sub_top.get('content', {}).get('message', ''),
                }
            result.append(item)
        return result
    except Exception as e:
        print(f"WARN: 获取评论失败: {e}", file=sys.stderr)
        return []

# ============================================================
# GitHub 抽取
# ============================================================

def extract_github(link: str) -> dict:
    """GitHub仓库信息抽取（优先gh CLI → REST API → defuddle 三级降级）。"""
    parsed = parse_repo(link)
    owner, repo = parsed['owner'], parsed['repo']

    # 优先尝试 gh CLI
    try:
        result = subprocess.run(
            ['gh', 'repo', 'view', f'{owner}/{repo}',
             '--json', 'name,description,stargazerCount,forkCount,primaryLanguage,licenseInfo,repositoryTopics,createdAt,updatedAt,homepageUrl'],
            capture_output=True, text=True, timeout=20,
        )
        if result.returncode == 0:
            d = json.loads(result.stdout)
            return {
                'source': 'github',
                'owner': owner,
                'repo': repo,
                'full_name': f'{owner}/{repo}',
                'title': f'{owner}/{repo}',
                'desc': d.get('description', ''),
                'stars': d.get('stargazerCount', 0),
                'forks': d.get('forkCount', 0),
                'language': d.get('primaryLanguage', {}).get('name', '') if isinstance(d.get('primaryLanguage'), dict) else '',
                'license': d.get('licenseInfo', {}).get('spdxId', '') if isinstance(d.get('licenseInfo'), dict) else '',
                'topics': [t.get('name', '') for t in d.get('repositoryTopics', [])] if isinstance(d.get('repositoryTopics'), list) else [],
                'created_at': d.get('createdAt', ''),
                'updated_at': d.get('updatedAt', ''),
                'url': link,
                'homepage': d.get('homepageUrl', ''),
                'note': '数据来源：gh CLI',
            }
    except Exception:
        pass

    # 降级到 GitHub REST API
    try:
        r = requests.get(
            f'https://api.github.com/repos/{owner}/{repo}',
            headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'WorkBuddy/2.0'},
            timeout=15,
        )
        if r.status_code == 404:
            return {'source': 'github', 'owner': owner, 'repo': repo, 'full_name': f'{owner}/{repo}', 'title': f'{owner}/{repo}', 'error': '仓库不存在或为私有仓库', 'url': link}
        if r.status_code == 403:
            # API限流 → 降级到 defuddle
            dd_result = run_defuddle(link, 'json')
            if dd_result:
                return {
                    'source': 'github',
                    'owner': owner,
                    'repo': repo,
                    'full_name': f'{owner}/{repo}',
                    'title': dd_result.get('title', f'{owner}/{repo}'),
                    'desc': dd_result.get('description', ''),
                    'content_markdown': dd_result.get('contentMarkdown', ''),
                    'domain': dd_result.get('domain', 'github.com'),
                    'url': link,
                    'note': '数据来源：defuddle（GitHub API限流降级）',
                }
            return {'source': 'github', 'owner': owner, 'repo': repo, 'full_name': f'{owner}/{repo}', 'title': f'{owner}/{repo}', 'error': 'API限流，且 defuddle 也失败', 'url': link}
        d = r.json()
        return {
            'source': 'github',
            'owner': owner,
            'repo': repo,
            'full_name': d.get('full_name', f'{owner}/{repo}'),
            'title': d.get('full_name', f'{owner}/{repo}'),
            'desc': d.get('description', ''),
            'stars': d.get('stargazers_count', 0),
            'forks': d.get('forks_count', 0),
            'open_issues': d.get('open_issues_count', 0),
            'language': d.get('language', ''),
            'license': d.get('license', {}).get('spdx_id', '') if d.get('license') else '',
            'topics': d.get('topics', []),
            'created_at': d.get('created_at', ''),
            'updated_at': d.get('updated_at', ''),
            'pushed_at': d.get('pushed_at', ''),
            'url': d.get('html_url', link),
            'homepage': d.get('homepage', ''),
            'note': '数据来源：GitHub REST API',
        }
    except Exception as e:
        # REST API 也失败 → defuddle 最后兜底
        dd_result = run_defuddle(link, 'json')
        if dd_result:
            return {
                'source': 'github',
                'owner': owner,
                'repo': repo,
                'full_name': f'{owner}/{repo}',
                'title': dd_result.get('title', f'{owner}/{repo}'),
                'desc': dd_result.get('description', ''),
                'content_markdown': dd_result.get('contentMarkdown', ''),
                'domain': dd_result.get('domain', 'github.com'),
                'url': link,
                'note': '数据来源：defuddle（API异常降级）',
            }
        return {'source': 'github', 'owner': owner, 'repo': repo, 'full_name': f'{owner}/{repo}', 'title': f'{owner}/{repo}', 'error': str(e), 'url': link, 'note': 'gh CLI/API/defuddle 全部失败，需人工补充'}

def parse_repo(url: str) -> dict:
    """从GitHub URL解析 owner/repo。"""
    m = re.search(r'github\.com/([^/]+)/([^/?#]+)', url)
    if m:
        return {'owner': m.group(1), 'repo': m.group(2).rstrip('.git')}
    raise URLError(f"无法解析GitHub仓库地址: {url}")

# ============================================================
# 腾讯微视 抽取
# ============================================================

def extract_weishi(link: str) -> dict:
    """腾讯微视/腾讯视频微信插件视频抽取（降级方案——依赖WebSearch+defuddle补充）。"""
    vid = extract_weishi_vid(link)
    WX_HEADERS = {
        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.42(0x18002a2f) NetType/WIFI Language/zh_CN',
        'Referer': 'https://mp.weixin.qq.com/',
    }

    title = ''
    author = ''
    share_count = 0
    note = ''

    try:
        r = requests.get(link, headers=WX_HEADERS, allow_redirects=True, timeout=20)
        html = r.text

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
        page_text = soup.get_text()
        text_lines = [l.strip() for l in page_text.splitlines() if l.strip()]

        # 找 @发布者
        author_m = re.search(r'@(\S{2,20})', page_text)
        if author_m:
            author = author_m.group(1)

        # 找分享数
        share_m = re.search(r'(\d{2,6})\s*分享', page_text)
        if share_m:
            share_count = int(share_m.group(1))

        # 找视频标题（过滤腾讯视频框架文本）
        bad_words = ['腾讯视频', '微信扫码', '客户端', '下载', '立即体验', '当前网络', '重试', 'VIP', '会员', '首页', '电视剧', '电影', '综艺']
        candidates = [l for l in text_lines if len(l) > 8 and not any(b in l for b in bad_words)]
        if candidates:
            title = max(candidates, key=len)[:200]

        if title:
            note = '数据从页面HTML解析，可能不完整。请结合 WebSearch 搜索 + defuddle 抓取公开报道补充内容。'
        else:
            note = '页面无法解析视频内容。必须通过 WebSearch 搜索同话题报道，再用 defuddle 抓取报道正文。'

    except Exception as e:
        note = f'页面抓取异常: {e}。必须通过 WebSearch 搜索 + defuddle 抓取补充内容。'

    return {
        'source': 'weishi',
        'vid': vid,
        'title': title,
        'author': author,
        'share_count': share_count,
        'url': link,
        'subtitle': {'available': False, 'note': '微视平台不支持字幕接口。'},
        'note': note,
    }

def extract_weishi_vid(link: str) -> str:
    m = re.search(r'/([a-z]\d{8,12}[a-z]{2})', link)
    if m:
        return m.group(1)
    return ''

# ============================================================
# YouTube 抽取
# ============================================================

def resolve_youtube_id(link: str) -> str:
    """从 YouTube URL 解析 video_id。"""
    m = re.search(r'(?:v=|youtu\.be/)([0-9A-Za-z_-]{11})', link)
    if m:
        return m.group(1)
    return ''


def extract_youtube(link: str) -> dict:
    """YouTube 视频抽取。

    优先级：
      1. yt-dlp (--dump-json) → 拿 title/channel/upload_date/view_count/like_count/description
      2. yt-dlp (--write-auto-sub) → 拿字幕 (zh-Hans > zh-Hant > en)
      3. yt-dlp 失败 → noembed.com 降级（仅 title/author/thumbnail）
    """
    video_id = resolve_youtube_id(link)
    if not video_id:
        return {'source': 'youtube', 'url': link, 'error': '无法解析 YouTube video_id', 'note': '请检查 URL 格式'}

    title = ''
    author = ''
    author_url = ''
    thumbnail = ''
    upload_date = ''
    view_count = 0
    like_count = 0
    duration_sec = 0
    description = ''
    source_note = ''

    # 路径 A: yt-dlp 合并调用（单进程同时拿元数据 + 字幕）
    combined = _run_ytdlp_combined(link)
    ytdlp_data = combined['data'] if combined else None
    subtitle_from_yt = combined['subtitle'] if combined else None
    ytdlp_available = bool(ytdlp_data)
    if ytdlp_data:
        title = ytdlp_data.get('title', '') or title
        author = ytdlp_data.get('channel', '') or ytdlp_data.get('uploader', '') or author
        author_url = ytdlp_data.get('channel_url', '') or author_url
        thumbnail = ytdlp_data.get('thumbnail', '') or thumbnail
        upload_date = ytdlp_data.get('upload_date', '') or upload_date
        view_count = ytdlp_data.get('view_count', 0) or 0
        like_count = ytdlp_data.get('like_count', 0) or 0
        duration_sec = ytdlp_data.get('duration', 0) or 0
        description = ytdlp_data.get('description', '') or description
        source_note = '数据来源：yt-dlp (--dump-json + --write-auto-sub 合并调用)'
    else:
        # 路径 B: noembed 降级
        noembed_data = fetch_youtube_noembed(link)
        if noembed_data:
            title = noembed_data.get('title', '') or title
            author = noembed_data.get('author_name', '') or author
            author_url = noembed_data.get('author_url', '') or author_url
            thumbnail = noembed_data.get('thumbnail_url', '') or thumbnail
            source_note = '数据来源：noembed.com（yt-dlp 不可用时的降级路径，无播放量/点赞/描述/字幕）'
        else:
            return {
                'source': 'youtube', 'url': link, 'video_id': video_id,
                'error': 'yt-dlp 不可用且 noembed.com 也失败',
                'note': '请检查网络或安装 yt-dlp（pip install yt-dlp）',
            }

    # 字幕（仅 yt-dlp 路径才有，noembed 不提供字幕）
    # _run_ytdlp_combined 已经在同一次进程内拿字幕了，不需要再次调用
    if subtitle_from_yt:
        subtitle = subtitle_from_yt
    elif ytdlp_available:
        subtitle = {'available': False, 'note': 'yt-dlp 抽取成功但未发现字幕轨道'}
    else:
        subtitle = {'available': False, 'note': '未尝试获取字幕（noembed 路径无字幕）'}

    return {
        'source': 'youtube',
        'video_id': video_id,
        'title': title,
        'url': f'https://www.youtube.com/watch?v={video_id}',
        'owner': {'name': author, 'url': author_url, 'mid': ''},
        'author': author,
        'channel_url': author_url,
        'thumbnail': thumbnail,
        'pic': thumbnail,
        'pubdate': _fmt_youtube_date(upload_date),
        'duration_sec': duration_sec,
        'view_count': view_count,
        'like_count': like_count,
        'stat': {'view': view_count, 'like': like_count},
        'desc': description,
        'description': description,
        'subtitle': subtitle,
        'note': source_note,
    }


def _fmt_youtube_date(upload_date: str) -> str:
    """yt-dlp upload_date 格式 YYYYMMDD → 'YYYY-MM-DD HH:MM:SS'."""
    if not upload_date or len(upload_date) != 8:
        return upload_date
    try:
        return f'{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:8]} 00:00:00'
    except Exception:
        return upload_date


# ============================================================
# 小红书 抽取（降级方案：defuddle 抓公开页 + 强 note 提示）
# ============================================================

def resolve_xhs_url(link: str) -> dict:
    """从 xhslink.com 短链 / xiaohongshu.com 长链 解析 item_id + 类型。

    xhslink.com 走微信 OAuth 中转，redirect URL 含 xiaohongshu.com item path。
    返回 {'item_id': str, 'kind': 'video'|'note'|'unknown', 'canonical_url': str}。
    """
    item_id = ''
    kind = 'unknown'
    canonical_url = link

    def _extract_from_url(u: str):
        """从单个 URL 提取 (item_id, kind)，找到就返回 (id, kind) 否则 (None, None)。"""
        if not u:
            return None, None
        m = re.search(r'/(?:discovery|exploration)/item/([0-9a-f]{20,32})', u, re.I)
        if not m:
            return None, None
        iid = m.group(1)
        kind = 'unknown'
        m2 = re.search(r'[?&]type=(\w+)', u)
        if m2:
            kind = m2.group(1)
        return iid, kind

    # 1) 长链：直接匹配 link
    item_id, kind = _extract_from_url(link)
    if item_id:
        canonical_url = link
    else:
        # 2) 短链：xhslink.cn/o/xxx → 重定向链 → 找 xhs URL
        try:
            r = safe_request(
                'GET', link,
                headers={'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.42(0x18002a2f) NetType/WIFI Language/zh_CN'},
                allow_redirects=True,
                timeout=10,
            )
            # 遍历所有 redirect URLs + final URL
            all_urls = [h.url for h in r.history] + [r.url]
            # 优先 Location header（如果存在）
            loc = r.headers.get('Location', '') or r.headers.get('location', '') or ''
            if loc:
                all_urls.insert(0, loc)
            for u in all_urls:
                # 处理 wechat 中转 URL：从 query string 的 redirect_uri 解码后再试
                if 'weixin.qq.com' in u and 'redirect_uri=' in u:
                    parsed = urllib.parse.urlparse(u)
                    qs = urllib.parse.parse_qs(parsed.query)
                    if 'redirect_uri' in qs:
                        decoded = urllib.parse.unquote(qs['redirect_uri'][0])
                        iid2, kind2 = _extract_from_url(decoded)
                        if iid2:
                            item_id, kind = iid2, kind2 or kind
                            canonical_url = decoded
                            break
                iid2, kind2 = _extract_from_url(u)
                if iid2:
                    item_id, kind = iid2, kind2 or kind
                    canonical_url = u
                    break
        except Exception:
            pass

    return {'item_id': item_id or '', 'kind': kind or 'unknown', 'canonical_url': canonical_url or link}


def extract_xiaohongshu(link: str) -> dict:
    """小红书笔记/视频抽取（降级方案）。

    现实：小红书页面是 client-side rendered，未登录/沙箱访问拿到的是空壳 HTML。
    defuddle 同样拿不到内容（只能拿到 og:title/description，但沙箱甚至连 og meta 都没有）。
    所以：本函数主要返回 item_id + 强 note 提示用户用 WebSearch 搜索同标题补充。
    """
    parsed = resolve_xhs_url(link)
    item_id = parsed['item_id']
    canonical_url = parsed['canonical_url']
    kind = parsed['kind']

    note = (
        '⚠️ 小红书需要登录态才能获取内容。沙箱 / 无 cookie 环境只能拿到 item_id，'
        '无法获取笔记文字/图片/视频元数据。'
        '**建议：复制笔记标题到 WebSearch 搜索，用 defuddle 抓取第三方报道补充内容。**'
    )
    if not item_id:
        note = '⚠️ 无法解析小红书 item_id（短链可能需要先在微信内打开一次）。' + note

    return {
        'source': 'xiaohongshu',
        'item_id': item_id,
        'kind': kind,
        'url': canonical_url or link,
        'title': '',
        'desc': '',
        'note': note,
        'partial': True,  # 标记为部分成功（issue #4 验收要求）
    }


# ============================================================
# 抖音 抽取（降级方案）
# ============================================================

def resolve_douyin_url(link: str) -> dict:
    """从 v.douyin.com 短链 / douyin.com / iesdouyin.com 长链解析 video_id。"""
    video_id = ''
    canonical_url = link

    # 长链: douyin.com/video/<id> 或 modal_id=<id>
    m = re.search(r'/video/(\d{15,20})', link)
    if m:
        video_id = m.group(1)
    else:
        m2 = re.search(r'modal_id=(\d{15,20})', link)
        if m2:
            video_id = m2.group(1)

    if not video_id:
        # 短链: v.douyin.com/<hashcode> → 302 重定向拿 video_id
        try:
            r = requests.head(
                link,
                headers={'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148'},
                allow_redirects=True,
                timeout=10,
            )
            final = r.url
            m3 = re.search(r'/video/(\d{15,20})', final)
            if m3:
                video_id = m3.group(1)
                canonical_url = final
            else:
                m4 = re.search(r'modal_id=(\d{15,20})', final)
                if m4:
                    video_id = m4.group(1)
                    canonical_url = final
        except Exception:
            pass

    return {'video_id': video_id, 'canonical_url': canonical_url}


def extract_douyin(link: str) -> dict:
    """抖音视频抽取（降级方案）。

    现实：抖音同样需要 App 内置 UA / X-Sign 签名才能拿到内容。
    沙箱/无 cookie 只能拿到 video_id，无标题/描述/视频流。
    """
    parsed = resolve_douyin_url(link)
    video_id = parsed['video_id']
    canonical_url = parsed['canonical_url']

    note = (
        '⚠️ 抖音需要 App 内置 UA + X-Sign 签名才能获取内容。沙箱/无签名环境只能拿到 video_id，'
        '无法获取视频元数据。'
        '**建议：复制视频标题到 WebSearch 搜索，用 defuddle 抓取第三方报道补充内容。**'
    )
    if not video_id:
        note = '⚠️ 无法解析抖音 video_id（短链可能需要先在抖音 App 内打开一次）。' + note

    return {
        'source': 'douyin',
        'video_id': video_id,
        'url': canonical_url or link,
        'title': '',
        'desc': '',
        'note': note,
        'partial': True,
    }



# ============================================================
# 通用网页 抽取（defuddle 替代 WebFetch）
# ============================================================

def extract_webpage(link: str) -> dict:
    """
    通用网页完整抽取——优先使用 defuddle CLI 一步提取元数据+正文+Markdown，
    defuddle 失败时降级到 requests+正则提取 meta 信息。
    
    defuddle 优势：
    - 本地算法提取，无 AI 模型开销，速度更快
    - 自动去除侧栏/广告/页脚/导航等噪音，输出更干净
    - 同时返回 contentMarkdown 和元数据，一步到位
    - 节省 ~50-70% token（相比 WebFetch 返回的含噪音 markdown）
    """
    # 优先 defuddle CLI（一步提取完整内容）
    dd_result = run_defuddle(link, 'json')
    if dd_result and dd_result.get('contentMarkdown'):
        return {
            'source': 'webpage',
            'title': dd_result.get('title', ''),
            'desc': dd_result.get('description', ''),
            'author': dd_result.get('author', ''),
            'domain': dd_result.get('domain', urlparse(link).netloc),
            'language': dd_result.get('language', ''),
            'published': dd_result.get('published', ''),
            'site': dd_result.get('site', ''),
            'word_count': dd_result.get('wordCount', 0),
            'content_markdown': dd_result.get('contentMarkdown', ''),
            'url': link,
            'subtitle': {'available': False, 'note': '网页内容由 defuddle 提取，已清洗为干净 Markdown。'},
            'note': '数据来源：defuddle CLI（本地提取，含完整正文+元数据）',
        }

    # defuddle 失败 → 降级到 requests+正则（仅提取 meta）
    print("WARN: defuddle 提取失败，降级到 requests meta 提取", file=sys.stderr)
    try:
        # 通用网页请求用 BASE_HEADERS（不带 B站 Referer，避免被跨源拒）
        r = safe_request('GET', link, headers=BASE_HEADERS, allow_redirects=True, timeout=15)
        html = r.text

        title = ''
        title_m = re.search(r'<title>([^<]+)</title>', html, re.IGNORECASE)
        if title_m:
            title = title_m.group(1).strip()

        desc = ''
        desc_m = re.search(r'<meta\s+name=["\']description["\']\s+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
        if not desc_m:
            desc_m = re.search(r'<meta\s+property=["\']og:description["\']\s+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
        if desc_m:
            desc = desc_m.group(1)

        domain = urlparse(r.url).netloc

        return {
            'source': 'webpage',
            'title': title,
            'desc': desc,
            'domain': domain,
            'url': r.url,
            'subtitle': {'available': False, 'note': 'defuddle 和 requests 均未能提取正文，需手动补充。'},
            'note': 'defuddle 提取失败，仅提取了页面 meta 信息。建议检查链接有效性或手动补充内容。',
        }
    except Exception as e:
        return {
            'source': 'webpage',
            'url': link,
            'error': str(e),
            'note': 'defuddle 和 requests 均失败。请检查链接是否有效。',
        }

# ============================================================
# 工具函数
# ============================================================

def fmt_ts(ts: int) -> str:
    try:
        return datetime.fromtimestamp(ts, tz=CST).strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        return str(ts)

# ============================================================
# 主入口
# ============================================================

def extract(link: str) -> dict:
    """自动检测来源并抽取。"""
    source = detect_source(link)
    print(f"[检测] 来源类型: {source}", file=sys.stderr)

    if source == 'bilibili':
        return extract_bilibili(link)
    elif source == 'github':
        return extract_github(link)
    elif source == 'weishi':
        return extract_weishi(link)
    elif source == 'youtube':
        return extract_youtube(link)
    elif source == 'xiaohongshu':
        return extract_xiaohongshu(link)
    elif source == 'douyin':
        return extract_douyin(link)
    else:
        return extract_webpage(link)

_IMA_CLIENT = None


def _get_ima_client():
    """获取 ima_client 模块（首次调用时加载并缓存）。

    直接 import ima_client（同目录），避免 importlib.util 动态加载绕开 Python 模块系统。
    之前用 importlib.util.spec_from_file_location 每次都重新 exec_module，慢且无法 mock。
    """
    global _IMA_CLIENT
    if _IMA_CLIENT is None:
        import ima_client
        _IMA_CLIENT = ima_client
    return _IMA_CLIENT


def _upload_to_ima(data: dict, kb_name: str, source_url: str):
    """将抽取结果作为 URL 导入 IMA 知识库。"""
    ima = _get_ima_client()

    # 查找目标知识库
    print(f"[IMA] 正在查找知识库「{kb_name}」...", file=sys.stderr)
    kb = ima.find_kb_by_name(kb_name)
    if not kb:
        print(f"[IMA] 错误：未找到知识库「{kb_name}」，请检查名称是否正确。", file=sys.stderr)
        return False

    kb_id = kb["id"]

    # 导入 URL
    print(f"[IMA] 正在导入到知识库「{kb_name}」...", file=sys.stderr)
    try:
        resp = ima.import_url(kb_id, [source_url])
        if resp.get("code") == 0:
            results = resp.get("data", {}).get("results", {})
            for url, r in results.items():
                if r.get("ret_code") == 0:
                    print(f"[IMA] ✅ 已导入: {url}", file=sys.stderr)
                else:
                    print(f"[IMA] ⚠️ 导入失败: {url} — {r.get('msg', '未知错误')}", file=sys.stderr)
            return True
        else:
            print(f"[IMA] 错误: {resp.get('msg', '未知错误')}", file=sys.stderr)
            return False
    except Exception as e:
        print(f"[IMA] 错误: {e}", file=sys.stderr)
        return False


def _build_context_for_source(data: dict) -> dict:
    """
    把抽取结果按来源归整为模板可直接用的 context。
    模板在 templates/<source>.md.j2，渲染时仅关心模板里出现的字段。
    """
    source = data.get('source', '')
    title = data.get('title', '') or data.get('full_name', '') or '未命名'
    duration_sec = int(data.get('duration_sec', 0) or 0)
    return {
        'source': source,
        'title': title,
        'url': data.get('url', ''),
        'version': data.get('version', __version__),
        'owner': data.get('owner', {}) or {},
        'bvid': data.get('bvid', ''),
        'pubdate': data.get('pubdate', ''),
        'duration_min': duration_sec // 60,
        'duration_sec': duration_sec % 60,
        'tags': data.get('tags', []) or [],
        'stat': data.get('stat', {}) or {},
        'desc': data.get('desc', '') or data.get('description', ''),
        'subtitle': data.get('subtitle', {}) or {'available': False},
        'top_replies': data.get('top_replies', []) or [],
        'full_name': data.get('full_name', ''),
        'homepage': data.get('homepage', ''),
        'stars': data.get('stars'),
        'forks': data.get('forks'),
        'language': data.get('language', ''),
        'license': data.get('license', ''),
        'topics': data.get('topics', []) or [],
        'created_at': data.get('created_at', ''),
        'updated_at': data.get('updated_at', ''),
        'author': data.get('author', ''),
        'domain': data.get('domain', ''),
        'published': data.get('published', ''),
        'word_count': data.get('word_count', 0),
        'content_markdown': data.get('content_markdown', ''),
        'note': data.get('note', ''),
        'share_count': data.get('share_count', 0),
        # issue #4 新增: xhs / douyin / youtube 专用字段
        'item_id': data.get('item_id', '') or '',
        'kind': data.get('kind', 'unknown') or 'unknown',
        'video_id': data.get('video_id', '') or '',
        'channel_url': data.get('channel_url', '') or '',
        'thumbnail': data.get('thumbnail', '') or data.get('pic', '') or '',
        'view_count': data.get('view_count', 0) or 0,
        'like_count': data.get('like_count', 0) or 0,
        'description': data.get('description', '') or data.get('desc', '') or '',
        'partial': data.get('partial', False),
    }


_JINJA_ENV = jinja2.Environment(
    loader=jinja2.FileSystemLoader(TEMPLATES_DIR),
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
)


def _render_template(source: str, context: dict) -> str:
    """按 source 选择模板渲染；找不到则走通用 fallback（拼装 desc+content）。"""
    template_name = f"{source}.md.j2"
    try:
        tpl = _JINJA_ENV.get_template(template_name)
        return tpl.render(**context)
    except jinja2.TemplateNotFound:
        # 通用 fallback：标题 + desc + 正文 + 参考资料
        lines = [f"# {context['title']}", "",
                 f"> 来源：{source} · 链接：{context['url']}", ""]
        if context.get('desc'):
            lines += ["## 简介", "", context['desc'], ""]
        if context.get('content_markdown'):
            lines += ["## 内容", "", context['content_markdown'], ""]
        lines += ["## 参考资料", "", f"- 原始链接：{context['url']}", "",
                  "---", "",
                  f"*本文档由 url-extract v{context['version']} 自动生成。*"]
        return "\n".join(lines)


def _build_markdown_content(data: dict) -> str:
    """
    将抽取结果组装成完整的结构化 Markdown 文档（v2.5.2：模板拆分为 templates/*.md.j2）。

    - bilibili / github / webpage / weishi → 各自模板
    - 未知 source → 通用 fallback
    """
    ctx = _build_context_for_source(data)
    return _render_template(ctx['source'], ctx)


def _sanitize_filename(title: str) -> str:
    """将标题转换为合法文件名。"""
    safe = re.sub(r'[^\w\u4e00-\u9fff\-]', '_', title)
    safe = re.sub(r'_+', '_', safe).strip('_')
    if len(safe) > 60:
        safe = safe[:60]
    return safe or 'extract'


def _upload_to_ima_raw(data: dict, source_url: str, external_md_path: str = ""):
    """将抽取结果作为 Markdown 文件上传到 IMA「RAW」个人知识库。

    v2.5 新增：若 external_md_path 指定了外部 Markdown 文件，优先上传该文件内容
    （用于 agent 生成的高质量精华文档），否则使用脚本自动生成的 Markdown。
    """
    ima = _get_ima_client()
    kb_name = "RAW"
    title = data.get("title", "") or data.get("full_name", "")

    # 查找 RAW 知识库
    print(f"[IMA] 正在查找知识库「{kb_name}」...", file=sys.stderr)
    kb = ima.find_kb_by_name(kb_name)
    if not kb:
        print(f"[IMA] 错误：未找到知识库「{kb_name}」。请确认 IMA 中已创建该知识库且有写入权限。", file=sys.stderr)
        return False

    kb_id = kb["id"]

    # 构建 Markdown 文件名和内容
    safe_title = _sanitize_filename(title)
    file_name = f"{safe_title}.md"

    # v2.5: 优先使用外部 Markdown 文件（agent 生成的高质量精华）
    if external_md_path and os.path.isfile(external_md_path):
        with open(external_md_path, "r", encoding="utf-8") as f:
            md_content = f.read()
        print(f"[IMA] 使用外部 Markdown 文件: {external_md_path} ({len(md_content)} chars)", file=sys.stderr)
    else:
        # v2.5.1: B站无字幕且无外部 MD 文件时，阻止上传空壳内容
        if data.get('source') == 'bilibili':
            subtitle = data.get('subtitle', {})
            if not subtitle.get('available'):
                print("[IMA] ⚠️ B站视频无字幕，Markdown 内容不完整，跳过上传。", file=sys.stderr)
                print("[IMA]    请先用 WebSearch + defuddle 补充内容，生成完整 Markdown 后通过 --ima-raw-md 上传。", file=sys.stderr)
                return False
        md_content = _build_markdown_content(data)

    # 上传 Markdown 文件（check_repeated_names 在 upload_markdown_to_kb 内部执行）
    print(f"[IMA] 正在上传 Markdown 到知识库「{kb_name}」: {file_name}", file=sys.stderr)
    try:
        resp = ima.upload_markdown_to_kb(kb_id, file_name, md_content)
        if resp.get("skipped"):
            print(f"[IMA] ⏭️ 文件已存在，跳过: {file_name}", file=sys.stderr)
            return True
        if resp.get("code") == 0:
            print(f"[IMA] ✅ Markdown 已上传: {file_name}", file=sys.stderr)
            return True
        else:
            print(f"[IMA] ⚠️ 上传失败: {resp.get('msg', '未知错误')}，降级为 URL 导入", file=sys.stderr)
            resp = ima.import_url(kb_id, [source_url])
            if resp.get("code") == 0:
                print(f"[IMA] ✅ URL 已导入: {source_url}", file=sys.stderr)
                return True
            return False
    except Exception as e:
        print(f"[IMA] ⚠️ Markdown 上传失败: {e}，降级为 URL 导入", file=sys.stderr)
        try:
            resp = ima.import_url(kb_id, [source_url])
            if resp.get("code") == 0:
                print(f"[IMA] ✅ URL 已导入: {source_url}", file=sys.stderr)
                return True
        except Exception as e2:
            print(f"[IMA] ❌ URL 导入也失败: {e2}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description=f'通用内容精华抽取 v{__version__} (defuddle + IMA 集成)')
    parser.add_argument('link', help='链接（B站/GitHub/网页/微视）')
    parser.add_argument('--output', '-o', default='extract_result.json', help='输出JSON路径')
    parser.add_argument('--upload-ima', action='store_true', help='抽取后导入 URL 到 IMA 知识库')
    parser.add_argument('--ima-kb', type=str, default='', help='目标 IMA 知识库名称（需配合 --upload-ima）')
    parser.add_argument('--ima-raw', action='store_true', help='上传 Markdown 文档到 IMA「RAW」个人知识库')
    parser.add_argument('--ima-raw-md', type=str, default='', help='指定外部 Markdown 文件路径，优先上传该文件（配合 --ima-raw 使用，用于 agent 生成的高质量精华文档）')
    # B站 风控缓解参数（任一缺失则从对应环境变量读取，都缺失则不注入 Cookie）
    parser.add_argument('--sessdata', type=str, default=os.environ.get('BILIBILI_SESSDATA', ''), help='B站 SESSDATA Cookie，用于缓解风控（也可设环境变量 BILIBILI_SESSDATA）')
    parser.add_argument('--bili-jct', type=str, default=os.environ.get('BILIBILI_BILI_JCT', ''), help='B站 bili_jct Cookie（也可设环境变量 BILIBILI_BILI_JCT）')
    parser.add_argument('--dedeuserid', type=str, default=os.environ.get('BILIBILI_DEDEUSERID', ''), help='B站 DedeUserID Cookie（也可设环境变量 BILIBILI_DEDEUSERID）')
    parser.add_argument('--wbi-sign', choices=['on', 'off'], default='off', help='是否对 B站 API 请求加 wbi 签名（默认 off。开启会增加一次 nav 接口调用，但能提高 view/player/reply 接口在风控 IP 上的成功率）')
    args = parser.parse_args()

    # 注入 B站 Cookie + wbi 开关（如果提供了 SESSDATA 或 wbi-sign on）
    if args.sessdata:
        set_bili_cookies(sessdata=args.sessdata, bili_jct=args.bili_jct or None, dedeuserid=args.dedeuserid or None)
    if args.wbi_sign == 'on':
        set_wbi_enabled(True)

    # 1) 验证 URL（防 SSRF）
    # 2) 捕获 URLError（URL 解析失败）和其它异常
    try:
        validate_url(args.link)
    except URLError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        data = extract(args.link)
    except URLError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as e:
        # 其它未捕获异常：打印堆栈 + 退出码 1
        import traceback
        print(f"ERROR: 抽取失败 ({type(e).__name__}): {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
    data['extracted_at'] = datetime.now(tz=CST).strftime('%Y-%m-%d %H:%M:%S')
    data['version'] = __version__

    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 抽取完成 -> {args.output}", file=sys.stderr)
    print(f"   来源: {data.get('source')}", file=sys.stderr)
    print(f"   标题: {data.get('title', data.get('full_name', 'N/A'))}", file=sys.stderr)
    engine = data.get('note', '')
    if 'defuddle' in engine:
        print(f"   引擎: defuddle CLI (本地提取)", file=sys.stderr)

    # IMA 导入 (--ima-raw 优先)
    if args.ima_raw:
        source_url = data.get('url', args.link)
        _upload_to_ima_raw(data, source_url, args.ima_raw_md)
    elif args.upload_ima:
        if not args.ima_kb:
            print("[IMA] 错误: 请用 --ima-kb 指定目标知识库名称。", file=sys.stderr)
        else:
            source_url = data.get('url', args.link)
            _upload_to_ima(data, args.ima_kb.strip(), source_url)

if __name__ == '__main__':
    main()
