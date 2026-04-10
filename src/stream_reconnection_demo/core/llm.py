import os

from langchain_core.language_models import BaseChatModel

USE_VERTEX_AI = os.getenv("USE_VERTEX_AI", "false").lower() == "true"

DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-20250514"
DEFAULT_VERTEX_MODEL = "gemini-2.5-flash"

DEFAULT_MODEL = DEFAULT_VERTEX_MODEL if USE_VERTEX_AI else DEFAULT_ANTHROPIC_MODEL


def get_llm(model: str = DEFAULT_MODEL) -> BaseChatModel:
    """Return an LLM client based on the USE_VERTEX_AI environment variable.

    Set USE_VERTEX_AI=true to use Google Vertex AI (ADC auth).
    Otherwise uses Anthropic (ANTHROPIC_API_KEY env var).
    """
    if USE_VERTEX_AI:
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(model=model, vertexai=True)

    from langchain_anthropic import ChatAnthropic

    return ChatAnthropic(model=model)
