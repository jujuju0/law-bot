"""평가 프리셋. 정의는 서비스와 공유하는 `rag/config.py`에 있다(서비스 코드가 eval을 import하지 않도록)."""

from rag.config import PRESETS, RetrievalConfig, get_preset

__all__ = ["PRESETS", "RetrievalConfig", "get_preset"]
