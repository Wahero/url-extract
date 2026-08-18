"""run_defuddle() NameError 修复回归测试。

v2.5.2 及之前版本中 run_defuddle() 引用了未定义的模块级变量
_DEFUDDLE_CWD / _DEFUDDLE_SHELL，导致每次 defuddle 调用都抛
NameError 并被静默吞掉，网页正文提取永远降级到 requests meta 路径。

本测试确保 subprocess.run 的 cwd/shell 来自 _get_defuddle_cmd() 缓存。
"""
import json
import subprocess
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import extract  # noqa: E402


def _fake_completed(stdout: str, returncode: int = 0):
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=''
    )


def test_run_defuddle_no_nameerror_json():
    """run_defuddle 不应抛 NameError，且能正常解析 JSON 输出。"""
    extract._DEFUDDLE_CACHE['cmd'] = '/fake/defuddle'
    extract._DEFUDDLE_CACHE['shell'] = False
    extract._DEFUDDLE_CACHE['cwd'] = None

    payload = {'title': 'T', 'contentMarkdown': '# body'}
    with mock.patch.object(
        extract.subprocess, 'run',
        return_value=_fake_completed(json.dumps(payload)),
    ) as m:
        result = extract.run_defuddle('https://example.com', 'json')

    assert result == payload
    assert m.called, 'subprocess.run 未被调用（可能仍在抛 NameError）'


def test_run_defuddle_cwd_shell_from_cache():
    """subprocess.run 的 cwd/shell 必须来自 _get_defuddle_cmd() 缓存。"""
    extract._DEFUDDLE_CACHE['cmd'] = '/fake/defuddle'
    extract._DEFUDDLE_CACHE['shell'] = True
    extract._DEFUDDLE_CACHE['cwd'] = '/fake/workspace'

    with mock.patch.object(
        extract.subprocess, 'run',
        return_value=_fake_completed('{"a":1}'),
    ) as m:
        extract.run_defuddle('https://example.com', 'json')

    kwargs = m.call_args.kwargs
    assert kwargs['cwd'] == '/fake/workspace'
    assert kwargs['shell'] is True


def test_run_defuddle_markdown_format_flag():
    """markdown 格式应追加 --markdown 参数并返回纯文本。"""
    extract._DEFUDDLE_CACHE['cmd'] = '/fake/defuddle'
    extract._DEFUDDLE_CACHE['shell'] = False
    extract._DEFUDDLE_CACHE['cwd'] = None

    with mock.patch.object(
        extract.subprocess, 'run',
        return_value=_fake_completed('# body'),
    ) as m:
        result = extract.run_defuddle('https://example.com', 'markdown')

    assert result == '# body'
    cmd_args = m.call_args.args[0]
    assert cmd_args[0] == '/fake/defuddle'
    assert 'parse' in cmd_args
    assert '--markdown' in cmd_args


def test_run_defuddle_npx_entrypoint():
    """npx 入口应使用 'npx defuddle parse' 形式并透传缓存 shell/cwd。

    注意：用裸 'npx' 而非带路径的 'C:\\node\\npx.cmd'，
    因为 Linux 上 os.path.basename 不解析反斜杠路径，
    带 Windows 路径的断言在 CI（Linux）上会误走 else 分支。
    """
    extract._DEFUDDLE_CACHE['cmd'] = 'npx'
    extract._DEFUDDLE_CACHE['shell'] = True
    extract._DEFUDDLE_CACHE['cwd'] = '/some/dir'

    with mock.patch.object(
        extract.subprocess, 'run',
        return_value=_fake_completed('{"a":1}'),
    ) as m:
        extract.run_defuddle('https://example.com', 'json')

    cmd_args = m.call_args.args[0]
    assert cmd_args[:3] == ['npx', 'defuddle', 'parse']
    kwargs = m.call_args.kwargs
    assert kwargs['shell'] is True
    assert kwargs['cwd'] == '/some/dir'


def test_run_defuddle_unavailable_returns_none():
    """defuddle 不可用（cmd 为空）时应返回 None 而不是抛异常。"""
    extract._DEFUDDLE_CACHE['cmd'] = ''
    extract._DEFUDDLE_CACHE['shell'] = False
    extract._DEFUDDLE_CACHE['cwd'] = None

    assert extract.run_defuddle('https://example.com') is None
