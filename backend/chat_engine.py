import os
import re

from llm_config import ModelOption, has_anthropic_key, has_openai_key, resolve_model_id
from llm_runner import generate_with_model
from tm1_mcp import TM1MCPClient, tm1_is_configured


FALLBACK_RESPONSES = {
    "saudacao": [
        "Olá! 👋 Sou o ChatBot. Como posso ajudar você hoje?",
        "Oi! Tudo bem? Estou aqui para conversar e ajudar no que precisar!",
        "Bem-vindo! Em que posso ser útil?",
    ],
    "despedida": [
        "Até logo! Foi um prazer conversar com você. Volte sempre! 😊",
        "Tchau! Se precisar de algo, é só chamar.",
        "Até mais! Tenha um ótimo dia!",
    ],
    "agradecimento": [
        "Por nada! Fico feliz em ajudar. 😊",
        "De nada! Estou aqui sempre que precisar.",
        "Imagina! Qualquer coisa, é só perguntar.",
    ],
    "ajuda": [
        "Posso consultar seu TM1 e responder com OpenAI ou Claude. "
        "Escolha o modelo no seletor acima do chat.",
        "Sou um chatbot com integração TM1! Selecione GPT ou Claude no topo da tela.",
    ],
    "tm1": [
        "Para consultar o TM1, configure TM1_MCP_URL, TM1_MCP_TOKEN e TM1_CONNECTION_ID no servidor.",
    ],
    "default": [
        "Interessante! Conte-me mais sobre isso.",
        "Entendi. Pode elaborar um pouco mais?",
        "Configure OPENAI_API_KEY ou ANTHROPIC_API_KEY no servidor para respostas com IA.",
    ],
}


def _classify_message(text: str) -> str:
    text_lower = text.lower().strip()

    if re.search(r"\b(oi|olá|ola|hey|bom dia|boa tarde|boa noite|e aí|eai)\b", text_lower):
        return "saudacao"
    if re.search(r"\b(tchau|até|adeus|bye|flw|falou)\b", text_lower):
        return "despedida"
    if re.search(r"\b(obrigad|valeu|agradeço|thanks)\b", text_lower):
        return "agradecimento"
    if re.search(r"\b(ajuda|help|o que você faz|quem é você|como funciona)\b", text_lower):
        return "ajuda"
    if re.search(r"\b(tm1|cubo|cubos|dimensão|dimensões|mdx|planning analytics)\b", text_lower):
        return "tm1"
    if "?" in text:
        return "pergunta"
    return "default"


def _fallback_response(text: str) -> str:
    category = _classify_message(text)
    responses = FALLBACK_RESPONSES.get(category, FALLBACK_RESPONSES["default"])
    return responses[len(text) % len(responses)]


def _has_openai_key() -> bool:
    return has_openai_key()


def _needs_tm1_tools(messages: list[dict]) -> bool:
    last_user = next(
        (m["content"] for m in reversed(messages) if m["role"] == "user"),
        "",
    )
    text = last_user.lower()
    patterns = [
        r"\b(dados?|valores?|total|resumo|consulta|mostra|exibe|lista)\b",
        r"\b20\d{2}\b",
        r"\b(cubo|cubos|mdx|tm1|dimensão|dimensões|rentabilidade|dre)\b",
        r"\b(financeiro|rateio|receita|despesa)\b",
    ]
    return any(re.search(p, text) for p in patterns)


def generate_response(
    messages: list[dict],
    model_id: str | None = None,
) -> tuple[str, str]:
    """Generate a chat response. Returns (response_text, mode)."""
    try:
        option = resolve_model_id(model_id)
    except ValueError as exc:
        return str(exc), "error"

    if not option:
        last_user_msg = next(
            (m["content"] for m in reversed(messages) if m["role"] == "user"),
            "",
        )
        return _fallback_response(last_user_msg), "fallback"

    mcp_client = TM1MCPClient.from_env() if tm1_is_configured() else None
    force_tools = bool(mcp_client and _needs_tm1_tools(messages))

    return generate_with_model(
        messages,
        option,
        mcp_client=mcp_client,
        force_tools=force_tools,
    )


def any_llm_configured() -> bool:
    return has_openai_key() or has_anthropic_key()
