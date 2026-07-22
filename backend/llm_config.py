import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelOption:
    id: str
    provider: str
    model: str
    label: str

    @classmethod
    def parse(cls, model_id: str) -> "ModelOption":
        if "/" not in model_id:
            raise ValueError(f"model_id inválido: {model_id}")
        provider, model = model_id.split("/", 1)
        label = next((m.label for m in AVAILABLE_MODELS if m.id == model_id), model)
        return cls(id=model_id, provider=provider, model=model, label=label)


AVAILABLE_MODELS: list[ModelOption] = [
    ModelOption("openai/gpt-4o-mini", "openai", "gpt-4o-mini", "GPT-4o Mini"),
    ModelOption("openai/gpt-4o", "openai", "gpt-4o", "GPT-4o"),
    ModelOption(
        "anthropic/claude-sonnet-4-20250514",
        "anthropic",
        "claude-sonnet-4-20250514",
        "Claude Sonnet 4",
    ),
    ModelOption(
        "anthropic/claude-3-5-haiku-20241022",
        "anthropic",
        "claude-3-5-haiku-20241022",
        "Claude 3.5 Haiku",
    ),
]


def has_openai_key() -> bool:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    return bool(key and key != "sk-your-key-here")


def has_anthropic_key() -> bool:
    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    return bool(key and key != "sk-ant-your-key-here")


def is_model_available(model_id: str) -> bool:
    try:
        option = ModelOption.parse(model_id)
    except ValueError:
        return False
    if option.provider == "openai":
        return has_openai_key()
    if option.provider == "anthropic":
        return has_anthropic_key()
    return False


def list_available_models() -> list[dict]:
    return [
        {
            "id": m.id,
            "provider": m.provider,
            "label": m.label,
            "available": is_model_available(m.id),
        }
        for m in AVAILABLE_MODELS
    ]


def resolve_default_model_id() -> str | None:
    default = os.getenv("DEFAULT_MODEL_ID", "").strip()
    if default and is_model_available(default):
        return default
    if has_openai_key():
        return "openai/gpt-4o-mini"
    if has_anthropic_key():
        return "anthropic/claude-sonnet-4-20250514"
    return None


def resolve_model_id(requested: str | None) -> ModelOption | None:
    model_id = requested or resolve_default_model_id()
    if not model_id:
        return None
    if not is_model_available(model_id):
        raise ValueError(
            f"Modelo '{model_id}' indisponível. Verifique a API key do provedor no servidor."
        )
    return ModelOption.parse(model_id)
