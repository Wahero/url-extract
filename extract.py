"""向後相容入口：實作已移至 :mod:`url_extract.extract`。

保留本檔是為了讓既有用法（``python extract.py <link>``）與
``import extract`` 繼續運作；新程式碼建議直接匯入 ``url_extract.extract``。
"""

import sys as _sys

from url_extract import extract as _impl

if __name__ == "__main__":
    _impl.main()
else:
    # 讓 `import extract` 拿到同一個 module 物件（共享全域快取與狀態）
    _sys.modules[__name__] = _impl
