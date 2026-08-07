"""Pytest 配置：清理 extract 模块的全局 cache，确保测试隔离。"""
import pytest


@pytest.fixture(autouse=True)
def reset_extract_caches():
    """每个测试前后清理 extract 的 lazy-init cache。

    之前测试填充 cache 后会影响后续测试（例如 test_url_validation 依赖空 cache）。
    """
    import extract
    extract._DEFUDDLE_CACHE.clear()
    extract._YTDLP_CACHE.clear()
    yield
    extract._DEFUDDLE_CACHE.clear()
    extract._YTDLP_CACHE.clear()
