#!/usr/bin/env python3
"""
通用内容抽取脚本 v2.4
支持来源：B站视频、GitHub仓库、一般网页URL、腾讯微视视频（降级方案）
增强：抽取后自动导入 IMA 知识库，支持上传 Markdown 精华文档到「RAW」个人知识库

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
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

try:
    import requests
except ImportError:
    print("ERROR: 缺少 requests 库，请运行: pip install requests", file=sys.stderr)
    sys.exit(1)

CST = timezone(timedelta(hours=8))
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://www.bilibili.com/',
}

# ============================================================
# defuddle CLI 集成
# ============================================================

DEFUDDLE_WORKSPACE = os.path.join(
    os.environ.get('USERPROFILE', os.environ.get('HOME', '/tmp')),
    '.workbuddy', 'binaries', 'node', 'workspace'
)

# Windows 下 npx 是 .cmd 文件，需要 shell=True 或直接用完整路径
NODE_BIN_DIR = os.path.join(
    os.environ.get('USERPROFILE', os.environ.get('HOME', '/tmp')),
    '.workbuddy', 'binaries', 'node', 'versions', '22.22.2'
)

def _find_npx_path() -> str:
    """查找 npx 可执行文件的完整路径（兼容 Windows/macOS/Linux）。"""
    # Windows: 优先找 npx.cmd
    npx_cmd = os.path.join(NODE_BIN_DIR, 'npx.cmd')
    if os.path.isfile(npx_cmd):
        return npx_cmd
    # Unix: 找 npx
    npx_bin = os.path.join(NODE_BIN_DIR, 'npx')
    if os.path.isfile(npx_bin):
        return npx_bin
    # 兜底：系统 PATH 中的 npx
    return 'npx'

NPX_PATH = _find_npx_path()
# Windows 下 .cmd 文件需要 shell=True
NPX_NEEDS_SHELL = os.path.isfile(os.path.join(NODE_BIN_DIR, 'npx.cmd'))

def run_defuddle(url: str, format: str = 'json') -> dict | str | None:
    """
    调用 defuddle CLI 提取网页内容。
    
    Args:
        url: 目标网页 URL
        format: 输出格式，'json' 返回完整元数据+内容，'markdown' 返回纯 Markdown
    
    Returns:
        dict (format='json') 或 str (format='markdown')，失败返回 None
    """
    cmd_args = [NPX_PATH, 'defuddle', 'parse', url]
    if format == 'json':
        cmd_args.append('--json')
    elif format == 'markdown':
        cmd_args.append('--markdown')

    env = {**os.environ, 'NODE_PATH': os.path.join(DEFUDDLE_WORKSPACE, 'node_modules')}

    try:
        result = subprocess.run(
            cmd_args,
            capture_output=True, text=True, timeout=30,
            cwd=DEFUDDLE_WORKSPACE,
            env=env,
            shell=NPX_NEEDS_SHELL,
        )
        if result.returncode != 0:
            print(f"WARN: defuddle CLI 失败 (exit={result.returncode}): {result.stderr[:200]}", file=sys.stderr)
            return None

        output = result.stdout.strip()
        if not output:
            return None

        if format == 'json':
            return json.loads(output)
        else:
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
    return 'webpage'

# ============================================================
# B站 抽取
# ============================================================

def extract_bilibili(link: str) -> dict:
    """B站视频完整抽取。"""
    bvid = resolve_bvid(link)
    info = fetch_bili_video_info(bvid)
    tags = fetch_bili_tags(bvid)
    subtitle = fetch_bili_subtitle(bvid, info.get('cid'))
    replies = fetch_bili_top_replies(info.get('aid'))
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
    print(f"ERROR: 无法解析BV号: {s}", file=sys.stderr)
    sys.exit(1)

def fetch_bili_video_info(bvid: str) -> dict:
    r = requests.get('https://api.bilibili.com/x/web-interface/view', params={'bvid': bvid}, headers=HEADERS, timeout=15)
    d = r.json()
    if d.get('code') != 0:
        print(f"ERROR: 获取B站视频信息失败: {d.get('message')}", file=sys.stderr)
        sys.exit(1)
    return d['data']

def fetch_bili_tags(bvid: str) -> list:
    try:
        r = requests.get('https://api.bilibili.com/x/tag/archive/tags', params={'bvid': bvid}, headers=HEADERS, timeout=15)
        d = r.json()
        if d.get('code') == 0:
            return [t.get('tag_name') for t in d.get('data', [])]
    except Exception:
        pass
    return []

def fetch_bili_subtitle(bvid: str, cid: int) -> dict:
    try:
        r = requests.get('https://api.bilibili.com/x/player/wbi/v2', params={'bvid': bvid, 'cid': cid}, headers=HEADERS, timeout=15)
        d = r.json()
        subs = d.get('data', {}).get('subtitle', {}).get('subtitles', [])
        if subs:
            sub_url = subs[0].get('subtitle_url', '')
            if sub_url.startswith('//'):
                sub_url = 'https:' + sub_url
            elif not sub_url.startswith('http'):
                sub_url = 'https://' + sub_url
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
    try:
        r = requests.get('https://api.bilibili.com/x/v2/reply/main', params={'type': 1, 'oid': aid, 'mode': 3, 'next': 0, 'ps': 30}, headers=HEADERS, timeout=15)
        d = r.json()
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
    print("ERROR: 无法解析GitHub仓库地址", file=sys.stderr)
    sys.exit(1)

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
        r = requests.get(link, headers=HEADERS, allow_redirects=True, timeout=15)
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
    else:
        return extract_webpage(link)

def _load_ima_client():
    """动态加载 ima_client 模块。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "ima_client", os.path.join(os.path.dirname(__file__), "ima_client.py")
    )
    ima = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ima)
    return ima


def _upload_to_ima(data: dict, kb_name: str, source_url: str):
    """将抽取结果作为 URL 导入 IMA 知识库。"""
    ima = _load_ima_client()

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


def _build_markdown_content(data: dict) -> str:
    """将抽取结果组装成 Markdown 文档。"""
    lines = []
    source = data.get('source', '')
    title = data.get('title', '') or data.get('full_name', '')

    lines.append(f"# {title}")
    lines.append("")

    source_url = data.get('url', '')
    lines.append(f"> 来源：{source} · 链接：{source_url}")
    if data.get('author'):
        lines.append(f"> 作者：{data['author']}")
    if data.get('pubdate'):
        lines.append(f"> 发布时间：{data['pubdate']}")
    lines.append("")
    lines.append("---")
    lines.append("")

    content_md = data.get('content_markdown', '')
    if content_md:
        lines.append(content_md)
        lines.append("")

    desc = data.get('desc', '') or data.get('description', '')
    if desc:
        lines.append("## 简介")
        lines.append("")
        lines.append(desc)
        lines.append("")

    stat = data.get('stat', {})
    if stat:
        lines.append("## 数据统计")
        lines.append("")
        lines.append("| 项目 | 数值 |")
        lines.append("|---|---|")
        for k, v in stat.items():
            lines.append(f"| {k} | {v} |")
        lines.append("")

    replies = data.get('top_replies', [])
    if replies:
        lines.append("## 高赞评论")
        lines.append("")
        for r in replies:
            like = r.get('like', 0)
            content = r.get('content', '')
            lines.append(f"> **[{like}赞]** {content}")
            sub = r.get('top_sub_reply')
            if sub:
                sub_like = sub.get('like', 0)
                sub_content = sub.get('content', '')
                lines.append(f"> └─ **[{sub_like}赞]** {sub_content}")
            lines.append("")

    lines.append("## 参考资料")
    lines.append("")
    lines.append(f"- 原始链接：{source_url}")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"*本文档由 url-extract v{data.get('version', '2.4')} 自动生成，仅作信息整理与学习参考之用。*")

    return "\n".join(lines)


def _sanitize_filename(title: str) -> str:
    """将标题转换为合法文件名。"""
    safe = re.sub(r'[^\w\u4e00-\u9fff\-]', '_', title)
    safe = re.sub(r'_+', '_', safe).strip('_')
    if len(safe) > 60:
        safe = safe[:60]
    return safe or 'extract'


def _upload_to_ima_raw(data: dict, source_url: str):
    """将抽取结果作为 Markdown 文件上传到 IMA「RAW」个人知识库。"""
    ima = _load_ima_client()
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
    parser = argparse.ArgumentParser(description='通用内容精华抽取 v2.4 (defuddle + IMA 集成)')
    parser.add_argument('link', help='链接（B站/GitHub/网页/微视）')
    parser.add_argument('--output', '-o', default='extract_result.json', help='输出JSON路径')
    parser.add_argument('--upload-ima', action='store_true', help='抽取后导入 URL 到 IMA 知识库')
    parser.add_argument('--ima-kb', type=str, default='', help='目标 IMA 知识库名称（需配合 --upload-ima）')
    parser.add_argument('--ima-raw', action='store_true', help='上传 Markdown 文档到 IMA「RAW」个人知识库')
    args = parser.parse_args()

    data = extract(args.link)
    data['extracted_at'] = datetime.now(tz=CST).strftime('%Y-%m-%d %H:%M:%S')
    data['version'] = '2.4'

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
        _upload_to_ima_raw(data, source_url)
    elif args.upload_ima:
        if not args.ima_kb:
            print("[IMA] 错误: 请用 --ima-kb 指定目标知识库名称。", file=sys.stderr)
        else:
            source_url = data.get('url', args.link)
            _upload_to_ima(data, args.ima_kb.strip(), source_url)

if __name__ == '__main__':
    main()
