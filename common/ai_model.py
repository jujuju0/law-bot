from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from common.config import (
    API_KEY,
    BASE_URL,
    EMBEDDING_MODEL,
    LLM_MAX_RETRIES,
    LLM_TIMEOUT,
    MAX_TOKENS,
    MODEL,
    TEMPERATURE,
)


def get_llm_model(
    model: str = MODEL,
    api_key: str | None = API_KEY,
    temperature: float | None = TEMPERATURE,
    max_tokens: int = MAX_TOKENS,
) -> ChatOpenAI:
    """ChatOpenAI 클라이언트를 만든다. judge 등 다른 모델은 `model` 인자로 지정.

    `temperature=None`이면 인자를 보내지 않는다(temperature를 거부하는 모델용).
    """
    kwargs: dict = {}
    if temperature is not None:
        kwargs["temperature"] = temperature
    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=BASE_URL,
        use_responses_api=False,  # base url로 할 때는 이부분 넣어야 함.(MonoRouter 사용)
        max_tokens=max_tokens,
        timeout=LLM_TIMEOUT,
        max_retries=LLM_MAX_RETRIES,
        **kwargs,
    )


def get_embedding_model() -> OpenAIEmbeddings:
    """설정된 임베딩 모델 클라이언트를 만든다."""
    embedding_model = EMBEDDING_MODEL
    embeddings = OpenAIEmbeddings(
        api_key=API_KEY,
        base_url=BASE_URL,
        model=embedding_model,
        max_retries=6,  # 게이트웨이 분당 요청 한도(429) 대비
    )
    # print(embeddings)
    return embeddings
