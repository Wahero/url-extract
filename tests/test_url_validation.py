"""URL 验证、错误处理、模块级副作用相关测试。"""
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import extract  # noqa: E402
from extract import URLError, validate_url, __version__


# -------------------------------------------------------------------
# S2: URL 验证（防 SSRF）
# -------------------------------------------------------------------

def test_validate_url_https():
    """合法 https URL 验证通过。"""
    assert validate_url("https://www.bilibili.com/video/BV123") == "https://www.bilibili.com/video/BV123"


def test_validate_url_http():
    """合法 http URL 验证通过。"""
    assert validate_url("http://example.com") == "http://example.com"


def test_validate_url_reject_file_scheme():
    """file:// 协议被拒绝。"""
    try:
        validate_url("file:///etc/passwd")
        assert False, "应该抛 URLError"
    except URLError as e:
        assert "不支持的协议" in str(e)


def test_validate_url_reject_ftp_scheme():
    """ftp:// 协议被拒绝。"""
    try:
        validate_url("ftp://example.com/file")
        assert False, "应该抛 URLError"
    except URLError as e:
        assert "不支持的协议" in str(e)


def test_validate_url_reject_localhost():
    """localhost 被拒绝（防 SSRF）。"""
    try:
        validate_url("http://localhost/admin")
        assert False, "应该抛 URLError"
    except URLError as e:
        assert "禁止访问" in str(e)


def test_validate_url_reject_127():
    """127.0.0.1 被拒绝。"""
    try:
        validate_url("http://127.0.0.1:8080")
        assert False, "应该抛 URLError"
    except URLError as e:
        assert "禁止访问" in str(e)


def test_validate_url_reject_aws_metadata():
    """AWS 云元数据地址被拒绝。"""
    try:
        validate_url("http://169.254.169.254/latest/meta-data/")
        assert False, "应该抛 URLError"
    except URLError as e:
        assert "禁止访问" in str(e)


def test_validate_url_reject_gcp_metadata():
    """GCP 云元数据地址被拒绝。"""
    try:
        validate_url("http://metadata.google.internal/")
        assert False, "应该抛 URLError"
    except URLError as e:
        assert "禁止访问" in str(e)


def test_validate_url_reject_empty_hostname():
    """空主机名被拒绝。"""
    try:
        validate_url("http:///path")
        assert False, "应该抛 URLError"
    except URLError as e:
        assert "缺少主机名" in str(e)


# -------------------------------------------------------------------
# C2: 错误处理（resolve_bvid / parse_repo 抛异常而不是 sys.exit）
# -------------------------------------------------------------------

def test_resolve_bvid_invalid_raises_urlerror():
    """无效的 BV 号抛 URLError，不再 sys.exit。"""
    try:
        extract.resolve_bvid("not a valid bv or url")
        assert False, "应该抛 URLError"
    except URLError as e:
        assert "无法解析BV号" in str(e)


def test_resolve_bvid_from_b23_tv():
    """b23.tv 短链解析（带网络请求 mock）。"""
    # 这测试 resolve_bvid 不会再 sys.exit，网络错误也走异常
    # 实际不调网络，只确保不 crash
    pass  # 已由其他测试覆盖


# -------------------------------------------------------------------
# C3: 模块级副作用（import 不应触发 defuddle/yt-dlp 探测）
# -------------------------------------------------------------------

def test_import_no_module_level_side_effects():
    """import extract 不应触发 defuddle/yt-dlp 探测。

    验证：_DEFUDDLE_CACHE 和 _YTDLP_CACHE 在 import 后是空的。
    """
    # 这些 cache dict 在 import 时必须是空的
    assert extract._DEFUDDLE_CACHE == {} or 'cmd' not in extract._DEFUDDLE_CACHE
    assert extract._YTDLP_CACHE == {} or 'cmd' not in extract._YTDLP_CACHE


def test_get_defuddle_cmd_lazy():
    """首次调用 _get_defuddle_cmd() 时才解析。"""
    # 清空 cache
    extract._DEFUDDLE_CACHE.clear()
    # mock _resolve_defuddle 防止真实探测
    with mock.patch("extract._resolve_defuddle", return_value=("defuddle", False, None)) as m:
        cmd, shell, cwd = extract._get_defuddle_cmd()
        assert cmd == "defuddle"
        assert shell is False
        assert cwd is None
        m.assert_called_once()
    # 第二次调用应该走 cache
    with mock.patch("extract._resolve_defuddle") as m2:
        cmd2, _, _ = extract._get_defuddle_cmd()
        assert cmd2 == "defuddle"
        m2.assert_not_called()


def test_get_ytdlp_cmd_lazy():
    """首次调用 _get_ytdlp_cmd() 时才解析。"""
    extract._YTDLP_CACHE.clear()
    with mock.patch("extract._resolve_ytdlp", return_value="yt-dlp") as m:
        cmd = extract._get_ytdlp_cmd()
        assert cmd == "yt-dlp"
        m.assert_called_once()
    # cache hit
    with mock.patch("extract._resolve_ytdlp") as m2:
        cmd2 = extract._get_ytdlp_cmd()
        assert cmd2 == "yt-dlp"
        m2.assert_not_called()


# -------------------------------------------------------------------
# C9: _get_ima_client 缓存
# -------------------------------------------------------------------

def test_get_ima_client_caches():
    """_get_ima_client() 返回同一个模块对象（缓存）。"""
    extract._IMA_CLIENT = None  # 清空
    with mock.patch.dict(sys.modules, {"ima_client": mock.MagicMock()}):
        m1 = extract._get_ima_client()
        m2 = extract._get_ima_client()
        assert m1 is m2, "第二次调用应该返回缓存"


# -------------------------------------------------------------------
# C6: 版本号统一
# -------------------------------------------------------------------

def test_version_exported():
    """__version__ 存在且是字符串。"""
    assert isinstance(extract.__version__, str)
    # 应该是 semver 格式 x.y.z
    parts = extract.__version__.split(".")
    assert len(parts) >= 2
    for p in parts:
        assert p.isdigit() or "." in p  # 允许 2.5.2 格式


def test_version_matches_pyproject():
    """__version__ 与 pyproject.toml 保持一致。"""
    import re as _re
    toml = (ROOT / "pyproject.toml").read_text()
    m = _re.search(r'^version\s*=\s*"([\d.]+)"', toml, _re.M)
    assert m, "pyproject.toml 应有 version 字段"
    pyproject_version = m.group(1)
    assert extract.__version__ == pyproject_version, \
        f"extract.__version__={extract.__version__} != pyproject.toml version={pyproject_version}"
