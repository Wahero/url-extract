# Changelog

## [Unreleased]

### Fixed
- **ima_client.py COS SDK 上传修复**：移除 `ContentLength` 参数（int 触发 `http.client` 报错），改用 `ETag` 判定上传成功（SDK 成功返回 dict 含 `ETag`，失败抛 `CosServiceError`）。（#15）

### Added
- **新来源支持：YouTube / 小红书 / 抖音**（issue #4）：
  - **YouTube**：检测 `youtube.com/watch?v=` / `youtu.be/`，优先 yt-dlp (--dump-json + --write-auto-sub) 拿完整元数据 + 字幕，无 yt-dlp 时降级到 noembed.com 公开代理（仅 title/author/thumbnail）。含轻量 WebVTT parser。
  - **小红书**：检测 `xiaohongshu.com` / `xhslink.com` / `xhslink.cn`，重定向链解析 item_id + type（note/video）。无登录态拿不到内容，标记 partial=True，强提示 WebSearch 补充。
  - **抖音**：检测 `douyin.com` / `v.douyin.com` / `iesdouyin.com`，长链直接解析 video_id。无 X-Sign 签名拿不到内容，标记 partial=True，强提示 WebSearch 补充。
  - 3 个新模板：`templates/{youtube,xiaohongshu,douyin}.md.j2`
  - 32 个新单测：`tests/test_new_sources.py`（detect/resolve/extract/模板渲染/VTT 解析）
  - `_SOURCE_PREFIX` 加 3 个前缀：`YouTube精华_` / `小红书精华_` / `抖音精华_`
- **依赖**：`yt-dlp` 加入 `requirements.txt` 注释（不强制，未装自动降级 noembed）
- **yt-dlp 探测** `_resolve_ytdlp()`：复用 defuddle 模式，按 `YTDLP_BIN` env → PATH yt-dlp → `python -m yt_dlp` → `pip install yt-dlp --break-system-packages -i 阿里源` 顺序探测
- **Popen 临时文件**：`_run_ytdlp_dump_json` 用临时文件代替 PIPE，避免 yt-dlp spawn 子进程时 pipe 阻塞
- **B站风控缓解**（issue #3）：
  - 新增 `--sessdata` / `--bili-jct` / `--dedeuserid` CLI 参数 + `BILIBILI_SESSDATA` / `BILIBILI_BILI_JCT` / `BILIBILI_DEDEUSERID` 环境变量，注入 B站 Cookie 缓解风控。
  - 新增 `--wbi-sign on` 开关，开启后自动给 view/player wbi v2/reply 接口加 wbi 签名（无需登录）。实现参考 [socialsisteryi/bilibili-API-collect](https://github.com/SocialSisterYi/bilibili-API-collect/blob/master/docs/misc/sign/wbi.md)，含 1h mixin_key 缓存。
  - 新增 `BilibiliRiskControlError` 异常类，风控响应（code ∈ {-101, -352, -412, -799, -509, -1200}）自动抛错。
  - 新增 `tenacity` 重试：3 次指数退避（1s/2s/4s），仅对风控响应触发。
  - `fetch_bili_video_info` / `fetch_bili_tags` / `fetch_bili_subtitle` / `fetch_bili_top_replies` 全部走新的 `_bili_get()` 包装器，自动带 Cookie + wbi 签名 + 重试 + 风控检测。
  - 新增 `tests/test_bilibili_cookie_retry.py`：24 个单元测试覆盖 Cookie 注入 / 风控检测 / 重试 / wbi 签名 / 端到端集成。
- **依赖**：`tenacity>=8.0` 加入 `requirements.txt`（推荐装，不装也能跑只是失去重试能力）。
- **CI workflow**：新增 `timeout-minutes: 20` 防止单 job 卡死导致 matrix 撞 6h limit 取消。

### Changed
- **SKILL.md 重写**：删除过期的 `~/.workbuddy/...`、`<skill_dir>/scripts/deps`、`<managed_python>` 等硬编码命令路径；新增「零配置快速上手」段落；精简 frontmatter `description`。
- **defuddle 跨平台探测**：去掉 `~/.workbuddy/binaries/node/22.22.2/` 路径硬编码，按 `DEFUDDLE_BIN` 环境变量 → `PATH` 中的 defuddle → `PATH` 中的 npx → 自动 `npm i -g defuddle` 顺序探测。向后兼容旧的 workbuddy 布局作为 NODE_PATH 兜底。
- **模板拆 Jinja2**：`_build_markdown_content()` 由 270 行大函数拆为 `templates/{bilibili,github,webpage,weishi}.md.j2` + Python 端只负责拼 context + 选模板。未知 source 走通用 fallback。
- **依赖声明**：新增 `pyproject.toml` + `requirements.txt`（`requests`、`beautifulsoup4`、`jinja2`）。

### Added
- `_SOURCE_PREFIX` 常量集中维护输出文件名前缀。
- `tests/test_templates.py` + `tests/fixtures/*.json`：10 个单元测试覆盖所有来源分支。

- **CI workflow**：新增 `timeout-minutes: 20` 防止单 job 卡死导致 matrix 撞 6h limit 取消。

### Changed (PR #10)
- **CI workflow 安装依赖**：`Install dependencies` 步骤显式装 `tenacity`（之前是 requirements.txt 注释，runner 实际没装），并设置 `timeout-minutes: 20` 防单 job 卡死。

### Added (PR #11, issue #5)
- **ima_client.py v1.4：tenacity 重试**：
  - `api_call()` 用 tenacity `@retry` 装饰，3 次指数退避（1s/2s/4s，最多 10s）
  - 只对 `URLError` / `HTTP 5xx` 重试；HTTP 4xx / 业务 code != 0 → 抛 `ImaAPIBusinessError` 不重试
  - 通过环境变量 `IMA_API_RETRY`（默认 3）/ `IMA_API_BACKOFF`（默认 1）可调
  - 新增自定义异常：`ImaAPIRetryableError`（可重试）/ `ImaAPIBusinessError`（不可重试）
  - no-op fallback：tenacity 未装时装饰器是 pass-through
- **ima_client.py 全函数类型注解**：所有公开函数加 type hint（`tuple[str, str]` / `list[dict[str, Any]]` 等）
- **22 个新测试**：`tests/test_ima_retry.py` 覆盖 `_is_retryable` 14 个 + `api_call` 集成 5 个 + 辅助 3 个
- **修 bug**：`HTTPError` 是 `URLError` 子类，`_is_retryable` 检查顺序必须 HTTPError 先于 URLError

### Changed (PR #12, extract.py Phase 1 重构)
- **C3 模块级副作用移除（lazy init）**：删除模块级 `_DEFUDDLE_CMD = _resolve_defuddle()` / `_YTDLP_CMD = _resolve_ytdlp()`（之前 import 触发 npm install / pip install 30-180s）。改用 `_DEFUDDLE_CACHE` / `_YTDLP_CACHE` 首次调用时再解析。**`import extract` 从 30-180s 缩到 0.1s**
- **C2 `sys.exit(1)` → 异常**：`resolve_bvid` / `parse_repo` 失败 → 抛 `URLError` 而非 `sys.exit(1)`；`import requests` / `import jinja2` 直接 ImportError 自然抛出。`main()` 加 try/except URLError，库使用者可 try/except 捕获
- **C9 `_load_ima_client` 简化**：删除 `importlib.util.spec_from_file_location` 动态加载，改用模块级 `_IMA_CLIENT` + `_get_ima_client()`（首次调用 import + 缓存）
- **C6 版本号统一**：提取 `__version__ = '2.5.2'` 单一来源（与 pyproject.toml 同步），argparse / data / 默认值都引用
- **S2 URL 验证（防 SSRF）**：新增 `validate_url()`，白名单 http/https，黑名单 `localhost` / `127.0.0.1` / `169.254.169.254` / `metadata.google.internal`
- **E1 B站 3 API 并行化**：`extract_bilibili()` 用 `ThreadPoolExecutor(max_workers=3)` 并行 `tags` / `subtitle` / `replies` 三个独立请求（`video_info` 必须先做），串行 ~2-3s → 并行 ~0.5-1s
- **C8 重复 import 清理**：删除 `resolve_xhs_url()` 内 `import re as _re` / `import urllib.parse as _up`，全文替换为模块顶部 import

### Changed (PR #13, extract.py Phase 2 重构)
- **T3 HEADERS 拆分（防跨源 Referer 污染）**：拆 `BASE_HEADERS = {UA}` / `HEADERS (BILI_HEADERS) = {UA, Referer=B站}`。defuddle 降级路径改用 `BASE_HEADERS`（不带 B站 Referer，避免被跨源拒）
- **E4 非 B站路径加重试**：新增 `safe_request(method, url, max_retries=2, backoff=1.0, **kwargs)`，ConnectionError/Timeout 自动重试，HTTPError 不重试。环境变量 `EXTRACT_HTTP_RETRY` 可调。应用：fetch_youtube_noembed / resolve_xhs_url / defuddle fallback
- **E2 YouTube 合并 yt-dlp 调用**：用 `_run_ytdlp_combined` 单进程拿 metadata + 字幕（命令：`--dump-json --write-info-json --write-auto-sub --write-subs`），替代之前的 `_run_ytdlp_dump_json` + `_run_ytdlp_subtitle`。节省 3-5s 启动开销，总超时 102s → 60s
- **D1 删 main 分支**：删除 GitHub 上 1b944518 (v2.5) 的 main 分支（与 master 不同步，且非默认分支）

### Fixed (PR #15, _cos_upload_sdk 两个 bug 修复)
- **Bug 1 (ContentLength)**：旧代码传 int `ContentLength=file_size` 在某些 Python/SDK 版本下触发 http.client 报错。修复：不传 ContentLength，让 SDK 从 Body 自动计算
- **Bug 2 (SDK 返回判断错误, critical)**：cos-sdk-v5 成功返回的是 dict（含 ETag），不是带 status_code 属性的对象。旧代码 `getattr(response, "status_code", None) or response.get("status_code")` 永远返回 None，导致 **所有 --ima-raw 走 SDK 路径之前都误判失败**。修复：用 `response.get("ETag")` 判定成功
- 影响范围：自 PR #2 引入，所有 --ima-raw 走 SDK 路径之前都是 bug 状态

### Added (PR #12-15 测试)
- 17 个新测试（`tests/test_url_validation.py`）覆盖 validate_url 9 个 + 异常化 2 个 + lazy init 2 个 + 版本号 2 个 + ima cache 1 个 + 异常捕获 1 个
- 12 个新测试（`tests/test_refactor_13.py`）覆盖 HEADERS 3 个 + safe_request 5 个 + _run_ytdlp_combined 2 个 + defuddle fallback 1 个 + import 1 个
- 6 个新测试（`tests/test_cos_sdk_etag.py`）覆盖 ContentLength 1 个 + ETag 判定 5 个
- 新增 `tests/conftest.py`：autouse fixture 清理 extract 缓存（解决 lazy init 引入的 test 隔离问题）
- **总测试数 73 → 130，新增 57 个**

### Added (PR #14, docs)
- 新增 `REFACTOR_PROGRESS.md`：记录 2026-08-07 一天完成的 url-extract 重构工作（6 个 PR 详情 + 5 个技术亮点 + 报告进度 + 反思）

## [2.5.1] - 2026-08-04
- 修复 `--ima-raw` 在 B 站无字幕时仍上传空壳 Markdown 的 bug，增加安全守卫。

## [2.5] - 2026-07-22
- 修复 `_build_markdown_content()` 对 B 站无字幕视频只输出空壳的 bug，重写为来源感知的完整结构化输出。
- 新增 `--ima-raw-md` 参数，支持指定外部 Markdown 文件优先上传。

## [2.4] - 2026-07-21
- IMA 凭证改为仅从环境变量读取，不持久化存储。
- `--ima-raw` 上传完整 Markdown 文档（create_media → COS → add_knowledge）。

## [2.3] - 2026-07-20
- 新增 `--ima-raw`：抽取后自动导入 IMA「RAW」个人知识库，导入前搜索去重。

## [2.2] - 2026-07-20
- 集成 IMA OpenAPI：新增 `ima_client.py` + `setup.py`，支持 `--upload-ima` 一键导入知识库。

## [2.1] - 2026-07-20
- 集成 defuddle CLI 替代 WebFetch：网页一步提取、GitHub 降级、B 站/微视内容补充均用 defuddle。

## [2.0] - 2026-07-20
- 通用版发布：支持 B 站 / GitHub / 网页 / 微视 四种来源，平台无关设计。

## [1.0] - 2026-07-19
- WorkBuddy 专版（bili-extract），仅支持 B 站视频。
