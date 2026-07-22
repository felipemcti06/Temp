import json
import os
import re
from datetime import datetime

from openai import OpenAI

from tm1_mcp import TM1MCPClient, TM1MCPError, tm1_is_configured
from tm1_tools import OPENAI_TOOL_DEFINITIONS, execute_tm1_tool


SYSTEM_PROMPT = """Você é um assistente virtual chamado ChatBot, especializado em IBM Planning Analytics / TM1.
Responda sempre em português brasileiro de forma clara, concisa e educada.

Quando o usuário perguntar sobre cubos, dimensões ou o modelo TM1, use as ferramentas disponíveis
para buscar dados reais do servidor antes de responder. Nunca invente nomes de cubos ou dimensões.

Se não houver integração TM1 configurada, informe isso e responda de forma geral."""


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
        "Posso conversar com você e consultar seu ambiente TM1 (cubos, dimensões, resumos). "
        "Experimente perguntar: 'Quais cubos existem?' ou 'Me mostra as dimensões'.",
        "Sou um chatbot com integração TM1! Posso listar cubos, dimensões e dar resumos do modelo.",
    ],
    "tm1": [
        "Para consultar o TM1, preciso que a integração esteja configurada no servidor "
        "(TM1_MCP_URL, TM1_MCP_TOKEN e TM1_CONNECTION_ID).",
    ],
    "default": [
        "Interessante! Conte-me mais sobre isso.",
        "Entendi. Pode elaborar um pouco mais?",
        "Hmm, boa pergunta! Para respostas mais detalhadas, configure a API OpenAI.",
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
    index = len(text) % len(responses)
    return responses[index]


def _has_openai_key() -> bool:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    return bool(key and key != "sk-your-key-here")


def _build_tools() -> list[dict] | None:
    if not tm1_is_configured():
        return None
    return OPENAI_TOOL_DEFINITIONS


def _run_with_tools(
    client: OpenAI,
    messages: list[dict],
    mcp_client: TM1MCPClient,
    model: str,
) -> tuple[str, str]:
    tools = _build_tools()
    api_messages = [{"role": "system", "content": SYSTEM_PROMPT}, *messages]

    for _ in range(6):
        kwargs: dict = {
            "model": model,
            "messages": api_messages,
            "max_tokens": 1024,
            "temperature": 0.7,
        }
        if tools:
            kwargs["tools"] = tools

        completion = client.chat.completions.create(**kwargs)
        choice = completion.choices[0]
        message = choice.message

        if choice.finish_reason == "tool_calls" and message.tool_calls:
            api_messages.append(
                {
                    "role": "assistant",
                    "content": message.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in message.tool_calls
                    ],
                }
            )

            for tool_call in message.tool_calls:
                fn_name = tool_call.function.name
                try:
                    fn_args = json.loads(tool_call.function.arguments or "{}")
                    result = execute_tm1_tool(mcp_client, fn_name, fn_args)
                except (TM1MCPError, json.JSONDecodeError) as exc:
                    result = f"Erro ao executar {fn_name}: {exc}"

                api_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result,
                    }
                )
            continue

        content = message.content or "Não consegui gerar uma resposta."
        mode = "ai+tm1" if tools else "ai"
        return content, mode

    return "Limite de iterações atingido ao consultar o TM1.", "ai+tm1"


def generate_response(messages: list[dict]) -> tuple[str, str]:
    """Generate a chat response. Returns (response_text, mode)."""
    if _has_openai_key():
        openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        mcp_client = TM1MCPClient.from_env()

        if mcp_client and tm1_is_configured():
            return _run_with_tools(openai_client, messages, mcp_client, model)

        api_messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for msg in messages:
            api_messages.append({"role": msg["role"], "content": msg["content"]})

        completion = openai_client.chat.completions.create(
            model=model,
            messages=api_messages,
            max_tokens=1024,
            temperature=0.7,
        )
        return completion.choices[0].message.content, "ai"

    last_user_msg = next(
        (m["content"] for m in reversed(messages) if m["role"] == "user"),
        "",
    )
    return _fallback_response(last_user_msg), "fallback"
