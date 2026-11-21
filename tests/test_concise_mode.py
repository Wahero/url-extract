"""精简模式（--concise）单元测试。

验证：Markdown 只保留「内容主体 + 重要声明」，其余章节（概览表 / 评论 / 参考资料）被省略。
覆盖 zh 与 en 两套模板。不联网，纯本地。
"""
import json
import sys
from pathlib import Path

# 让 extract.py 可被 import
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import extract  # noqa: E402

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def _both(data: dict):
    return extract._build_markdown_content(data), extract._build_markdown_content(data, concise=True)


def _via_flag(data: dict, concise: bool) -> str:
    """模拟 CLI：data['concise'] 由 main() 写入后，渲染应自动精简。"""
    d = dict(data)
    d['concise'] = concise
    return extract._build_markdown_content(d)


# ============================================================
# 通用不变量：所有来源都必须保留「重要声明」
# ============================================================

ZH_CASES = [
    ("bilibili_with_subtitle.json", "bilibili"),
    ("bilibili_no_subtitle.json", "bilibili"),
    ("github_with_readme.json", "github"),
    ("github_api_limited.json", "github"),
    ("webpage.json", "webpage"),
    ("weishi.json", "weishi"),
]


def test_concise_keeps_declaration_for_all_sources():
    for fname, source in ZH_CASES:
        data = _load(fname)
        md = extract._build_markdown_content(data, concise=True)
        assert "重要声明" in md, f"{source}: 精简模式必须保留重要声明"
        assert "学术测试版" in md, f"{source}: 精简模式必须保留学术测试版声明"
        assert md.lstrip().startswith("# "), f"{source}: 必须以 # 标题开头"


def test_concise_keeps_english_declaration():
    """英文模板（--lang en）同样必须保留 Important Disclaimer。"""
    data = _load("webpage.json")
    data = dict(data)
    data['lang'] = 'en'
    md = extract._build_markdown_content(data, concise=True)
    assert "Important Disclaimer" in md
    assert "Academic Preview" in md
    assert "References" not in md


def test_concise_via_data_flag_matches_explicit_param():
    """main() 写入 data['concise'] 时，渲染结果与显式传参一致。"""
    data = _load("webpage.json")
    assert _via_flag(data, True) == extract._build_markdown_content(data, concise=True)
    assert _via_flag(data, False) == extract._build_markdown_content(data)


def test_concise_keeps_source_header_line():
    """精简模式仍保留来源头（出处可追溯），但不再有概览章节。"""
    data = _load("webpage.json")
    md = extract._build_markdown_content(data, concise=True)
    assert "> 来源：网页" in md
    assert "测试网页标题" in md


# ============================================================
# B站
# ============================================================

def test_bilibili_concise_drops_overview_comments_and_refs():
    data = _load("bilibili_with_subtitle.json")
    full, concise = _both(data)

    # 完整模式有这些章节
    assert "## 一、视频概览" in full
    assert "## 三、高赞评论" in full
    assert "## 四、参考资料" in full

    # 精简模式全部省略
    assert "视频概览" not in concise
    assert "高赞评论" not in concise
    assert "高赞用户" not in concise
    assert "参考资料" not in concise

    # 但保留字幕正文与声明
    assert "视频字幕" in concise
    assert "这是一段测试字幕" in concise
    assert "重要声明" in concise


def test_bilibili_concise_keeps_description():
    """简介是创作者内容，精简模式保留（提升为独立章节）。"""
    data = _load("bilibili_with_subtitle.json")
    if not data.get("desc"):
        return
    concise = extract._build_markdown_content(data, concise=True)
    assert "## 视频简介" in concise
    assert data["desc"] in concise


def test_bilibili_concise_no_subtitle_branch():
    data = _load("bilibili_no_subtitle.json")
    concise = extract._build_markdown_content(data, concise=True)
    assert "## 精华内容" in concise
    assert "未上传字幕" in concise
    assert "视频字幕（完整转录）" not in concise
    assert "重要声明" in concise


def test_bilibili_concise_english():
    data = dict(_load("bilibili_with_subtitle.json"))
    data['lang'] = 'en'
    full = extract._build_markdown_content(data)
    concise = extract._build_markdown_content(data, concise=True)

    assert "## 1. Video Overview" in full
    assert "## 4. References" in full
    assert "Video Overview" not in concise
    assert "References" not in concise
    assert "Subtitles" in concise
    assert "Important Disclaimer" in concise


# ============================================================
# 网页
# ============================================================

def test_webpage_concise_keeps_body_only():
    data = _load("webpage.json")
    full, concise = _both(data)

    assert "## 一、概览" in full
    assert "## 三、参考资料" in full

    assert "## 一、概览" not in concise
    assert "参考资料" not in concise

    # 正文主体保留（精简模式不带「二、」序号——只剩一个章节时编号无意义）
    assert "## 正文内容" in concise
    assert "## 二、正文内容" not in concise
    assert "测试网页正文段落" in concise
    assert "重要声明" in concise


# ============================================================
# GitHub
# ============================================================

def test_github_concise_keeps_readme_only():
    data = _load("github_with_readme.json")
    full, concise = _both(data)

    assert "## 一、仓库概览" in full
    assert "## 三、参考资料" in full

    assert "## 一、仓库概览" not in concise
    assert "参考资料" not in concise
    assert "Stars" not in concise

    assert "## README" in concise
    assert "测试 README 内容" in concise
    assert "重要声明" in concise


def test_github_concise_keeps_note_when_no_readme():
    data = _load("github_api_limited.json")
    concise = extract._build_markdown_content(data, concise=True)
    assert "## README" in concise
    assert "重要声明" in concise


def test_github_concise_english():
    data = dict(_load("github_with_readme.json"))
    data['lang'] = 'en'
    concise = extract._build_markdown_content(data, concise=True)
    assert "## README" in concise
    assert "Repository Overview" not in concise
    assert "References" not in concise
    assert "Important Disclaimer" in concise


# ============================================================
# 微视 / 未知来源 fallback
# ============================================================

def test_weishi_concise_drops_reference_section():
    data = _load("weishi.json")
    full, concise = _both(data)

    assert "## 二、参考资料" in full
    assert "## 二、参考资料" not in concise
    assert "## 一、视频信息" in concise
    assert "WebSearch" in concise
    assert "重要声明" in concise


def test_unknown_source_fallback_concise():
    data = {
        "source": "unknown_future",
        "title": "未知来源",
        "url": "https://example.com",
        "desc": "fallback 描述",
        "content_markdown": "fallback 正文",
        "version": "2.7.0",
    }
    full = extract._build_markdown_content(data)
    concise = extract._build_markdown_content(data, concise=True)

    assert "## 参考资料" in full
    assert "## 参考资料" not in concise
    assert "fallback 正文" in concise
    assert "fallback 描述" in concise


# ============================================================
# CLI 选项与本地输出命名
# ============================================================

def test_cli_registers_concise_flag():
    src = Path(extract.__file__).read_text(encoding="utf-8")
    assert "'--concise'" in src, "必须注册 --concise 选项"
    assert "action='store_true'" in src
    assert "data['markdown_mode']" in src or '"markdown_mode"' in src


def test_local_markdown_sink_concise_suffix(tmp_path):
    """精简版与完整版同名会互相覆盖 → LocalMarkdownSink 需加后缀。"""
    data = {"source": "webpage", "title": "测试网页标题", "lang": "zh"}
    sink = extract.LocalMarkdownSink(str(tmp_path))

    data_full = dict(data)
    data_full['concise'] = False
    sink.upload(data_full, "https://example.com")

    data_concise = dict(data)
    data_concise['concise'] = True
    sink.upload(data_concise, "https://example.com")

    names = sorted(p.name for p in tmp_path.glob("*.md"))
    assert len(names) == 2, f"完整版与精简版应并存，实际: {names}"
    assert any(n.endswith("_精简.md") for n in names), f"精简版需带 _精简 后缀: {names}"


def test_local_markdown_sink_english_concise_suffix(tmp_path):
    data = {"source": "webpage", "title": "Sample Title", "lang": "en", "concise": True}
    extract.LocalMarkdownSink(str(tmp_path)).upload(data, "https://example.com")
    names = [p.name for p in tmp_path.glob("*.md")]
    assert len(names) == 1
    assert names[0].endswith("_concise.md"), f"英文精简版需带 _concise 后缀: {names}"


def test_build_markdown_content_signature_accepts_concise():
    import inspect
    params = inspect.signature(extract._build_markdown_content).parameters
    assert "concise" in params
    assert params["concise"].default is False


def test_version_bumped():
    assert extract.__version__ == '2.7.0'
