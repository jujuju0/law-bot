import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)

# OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

API_KEY = os.getenv("LLM_API_KEY")
BASE_URL = os.getenv("LLM_BASE_URL")

MODEL = os.getenv("LLM_MODEL", "gpt-5.4-mini")
# LLM_TEMPERATURE를 비워 두면(또는 none) temperature 인자를 생략한다(일부 reasoning 계열 모델용)
_temperature = os.getenv("LLM_TEMPERATURE", "0").strip()
TEMPERATURE: float | None = (
    None if _temperature.lower() in ("", "none") else float(_temperature)
)
MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "1024"))

# 평가용 LLM judge 모델. 비어 있으면 서비스 모델을 그대로 사용
JUDGE_MODEL = os.getenv("JUDGE_MODEL") or MODEL

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
# 로컬 CrossEncoder reranker (sentence-transformers, HuggingFace Hub 모델명 또는 로컬 경로)
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "ai_basic_law")
# 비교용(E0) 고정 길이 청킹 컬렉션
NAIVE_COLLECTION_NAME = os.getenv("NAIVE_COLLECTION_NAME", f"{COLLECTION_NAME}_naive")
# 비교용(E1) 구조 청킹이지만 contextual header 없이 본문(text)만 임베딩한 컬렉션
RAW_COLLECTION_NAME = os.getenv("RAW_COLLECTION_NAME", f"{COLLECTION_NAME}_raw")

# 국가법령정보 공동활용 Open API. OC 값은 .env에서만 읽는다(하드코딩 금지)
LAW_OC = os.getenv("LAW_OC")
LAW_API_BASE = os.getenv("LAW_API_BASE", "http://www.law.go.kr/DRF").rstrip("/")

# 데이터 경로 (프로젝트 루트 기준)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
SOURCES_FILE = DATA_DIR / "sources.yaml"

# /ask 서비스가 사용할 RetrievalConfig 프리셋 이름 (rag/configs.py)
SERVICE_RETRIEVAL_PRESET = os.getenv("SERVICE_RETRIEVAL_PRESET", "full")
