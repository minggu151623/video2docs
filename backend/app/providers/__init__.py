from app.providers.gemini import GeminiProvider
from app.providers.mock import MockProvider


def get_provider(settings):
    return MockProvider(settings) if settings.ai_provider == "mock" else GeminiProvider(settings)
