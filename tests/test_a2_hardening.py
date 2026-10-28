"""A2 护城河加固 + 异常隔离测试：

- SourceError：任意 source 抽取异常被统一包装为结构化错误（机读 code）
- LocalMarkdownSink：零依赖本地后备，写入文件
- _run_sinks：多 sink 任一成功即 ok；全失败才 False；空列表视为成功
- self_test：所有探测健康时返回 0
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import extract  # noqa: E402


def test_source_error_wraps_unknown_exception(monkeypatch):
    """extract() 内部任意未捕获异常应包装为 SourceError，便于调用方机读。"""
    monkeypatch.setattr(extract, "detect_source", lambda link: "bilibili")

    def _boom(link):
        raise ValueError("boom")

    monkeypatch.setattr(extract, "extract_bilibili", _boom)
    with pytest.raises(extract.SourceError) as exc:
        extract.extract("https://www.bilibili.com/video/BV1xx")
    assert exc.value.source == "bilibili"
    assert exc.value.code == "E_EXTRACT_FAILED"
    assert "ValueError" in str(exc.value)
    assert exc.value.cause is not None


def test_local_markdown_sink_writes_file(tmp_path, monkeypatch):
    """LocalMarkdownSink 零依赖写入本地目录。"""
    monkeypatch.setattr(extract, "_build_markdown_content", lambda data: "# Title\n\nbody")
    sink = extract.LocalMarkdownSink(str(tmp_path))
    ok = sink.upload({"title": "My Note", "full_name": "My Note"}, "https://example.com/x", "")
    assert ok is True
    files = list(tmp_path.glob("*.md"))
    assert len(files) == 1
    assert "Title" in files[0].read_text(encoding="utf-8")


def test_run_sinks_any_ok(monkeypatch, tmp_path):
    """一个 sink 失败、另一个成功 -> 整体视为成功。"""

    class FailSink:
        name = "Fail"

        def upload(self, data, source_url, md_path=""):
            return False

    sink_ok = extract.LocalMarkdownSink(str(tmp_path))
    monkeypatch.setattr(extract, "_build_markdown_content", lambda data: "x")
    ok = extract._run_sinks([FailSink(), sink_ok], {"title": "t"}, "https://e.com/x", "")
    assert ok is True


def test_run_sinks_all_fail(monkeypatch, tmp_path):
    class FailSink:
        name = "Fail"

        def upload(self, data, source_url, md_path=""):
            return False

    ok = extract._run_sinks([FailSink()], {"title": "t"}, "https://e.com/x", "")
    assert ok is False


def test_run_sinks_empty_is_ok():
    """无 sink 配置 -> 视为成功（无需写入）。"""
    assert extract._run_sinks([], {}, "https://e.com/x", "") is True


def test_build_sinks_requires_kb_for_upload_ima():
    """--upload-ima 但缺 --ima-kb -> 返回空列表（参数有误）。"""

    class Args:
        upload_ima = True
        ima_kb = ""
        ima_raw = False
        local_out = ""

    assert extract._build_sinks(Args()) == []


def test_self_test_all_healthy(monkeypatch):
    """所有依赖与端点健康时 self_test 返回 0。"""

    class _Resp:
        status_code = 200

    monkeypatch.setattr(extract, "safe_request", lambda *a, **k: _Resp())
    monkeypatch.setattr(extract.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(extract, "_get_defuddle_cmd", lambda: ("/usr/bin/defuddle", False, None))
    monkeypatch.setenv("IMA_OPENAPI_CLIENTID", "x")
    monkeypatch.setenv("IMA_OPENAPI_APIKEY", "y")
    assert extract.self_test() == 0
