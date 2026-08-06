# Changelog

## [Unreleased]

### Changed
- **SKILL.md 重写**：删除过期的 `~/.workbuddy/...`、`<skill_dir>/scripts/deps`、`<managed_python>` 等硬编码命令路径；新增「零配置快速上手」段落；精简 frontmatter `description`。
- **defuddle 跨平台探测**：去掉 `~/.workbuddy/binaries/node/22.22.2/` 路径硬编码，按 `DEFUDDLE_BIN` 环境变量 → `PATH` 中的 defuddle → `PATH` 中的 npx → 自动 `npm i -g defuddle` 顺序探测。向后兼容旧的 workbuddy 布局作为 NODE_PATH 兜底。
- **模板拆 Jinja2**：`_build_markdown_content()` 由 270 行大函数拆为 `templates/{bilibili,github,webpage,weishi}.md.j2` + Python 端只负责拼 context + 选模板。未知 source 走通用 fallback。
- **依赖声明**：新增 `pyproject.toml` + `requirements.txt`（`requests`、`beautifulsoup4`、`jinja2`）。

### Added
- `_SOURCE_PREFIX` 常量集中维护输出文件名前缀。
- `tests/test_templates.py` + `tests/fixtures/*.json`：10 个单元测试覆盖所有来源分支。

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
