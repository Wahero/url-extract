"""模板渲染单元测试。

对每个 source 跑一组固定 fixture，验证渲染出的 Markdown 包含关键字段。
不联网，纯本地。
"""
import sys
import os
import json
from pathlib import Path

# 让 extract.py 可被 import
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import extract  # noqa: E402

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def test_bilibili_with_subtitle():
    data = _load("bilibili_with_subtitle.json")
    md = extract._build_markdown_content(data)

    assert md.startswith("# 测试视频标题"), "必须以 # 标题 开头"
    assert "B站视频" in md, "来源必须含 B 站"
    assert "测试UP主" in md, "UP 主必须出现"
    assert "BV1xx411c7mD" in md, "BV 号必须出现"
    assert "视频字幕" in md, "有字幕时必须出现字幕小节"
    assert "这是一段测试字幕" in md, "字幕正文必须出现"
    assert "## 三、高赞评论" in md, "评论小节必须出现"
    assert "高赞用户" in md, "评论作者必须出现"
    assert "## 四、参考资料" in md, "参考资料小节必须出现"
    assert "学术测试版" in md, "学术声明必须出现"


def test_bilibili_without_subtitle():
    data = _load("bilibili_no_subtitle.json")
    md = extract._build_markdown_content(data)

    assert "## 二、精华内容" in md, "无字幕时必须走『精华内容』分支"
    assert "未上传字幕" in md, "必须显式提示无字幕"
    assert "视频字幕（完整转录）" not in md, "无字幕时不应出现字幕小节"
    assert "学术测试版" in md


def test_github_with_readme():
    data = _load("github_with_readme.json")
    md = extract._build_markdown_content(data)

    assert "# test/repo" in md, "必须使用 full_name 作为标题"
    assert "GitHub" in md
    assert "Stars" in md
    assert "MIT" in md
    assert "## 二、README" in md
    assert "测试 README 内容" in md
    assert "## 三、参考资料" in md


def test_github_api_limited():
    """API 限流走 defuddle 降级：note 含 defuddle，content_markdown 是 README。"""
    data = _load("github_api_limited.json")
    md = extract._build_markdown_content(data)

    assert "defuddle" in md.lower() or "API 限流" in md
    assert "## 二、README" in md
    assert "## 三、参考资料" in md


def test_webpage():
    data = _load("webpage.json")
    md = extract._build_markdown_content(data)

    assert "网页" in md
    assert "测试网页标题" in md
    assert "测试作者" in md
    assert "## 二、正文内容" in md
    assert "测试网页正文段落" in md
    assert "## 三、参考资料" in md


def test_weishi():
    data = _load("weishi.json")
    md = extract._build_markdown_content(data)

    assert "微视" in md
    assert "## 一、视频信息" in md
    assert "WebSearch" in md, "微视必须提示 WebSearch 补充"


def test_unknown_source_fallback():
    """未知 source 走通用 fallback。"""
    data = {
        "source": "unknown_future",
        "title": "未知来源",
        "url": "https://example.com",
        "desc": "fallback 描述",
        "content_markdown": "fallback 正文",
        "version": "2.5.2",
    }
    md = extract._build_markdown_content(data)
    assert "未知来源" in md
    assert "fallback 描述" in md
    assert "fallback 正文" in md
    assert "## 参考资料" in md


def test_sanitize_filename():
    assert extract._sanitize_filename("Hello World!") == "Hello_World"
    assert extract._sanitize_filename("中文标题-测试") == "中文标题_测试" or "中文标题" in extract._sanitize_filename("中文标题-测试")
    long = "a" * 100
    out = extract._sanitize_filename(long)
    assert len(out) <= 60
    assert extract._sanitize_filename("") == "extract"


def test_source_prefix():
    assert extract._SOURCE_PREFIX["bilibili"] == "B站视频精华_"
    assert extract._SOURCE_PREFIX["github"] == "GitHub精华_"
    assert extract._SOURCE_PREFIX["webpage"] == "网页精华_"
    assert extract._SOURCE_PREFIX["weishi"] == "视频精华_"


def test_templates_dir_exists():
    tpl_dir = Path(extract.TEMPLATES_DIR)
    assert tpl_dir.is_dir(), f"templates 目录不存在: {tpl_dir}"
    for name in ("bilibili", "github", "webpage", "weishi"):
        assert (tpl_dir / f"{name}.md.j2").is_file(), f"缺少模板 {name}.md.j2"
