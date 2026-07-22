import json
import os
import re
from datetime import datetime

from openai import OpenAI

from tm1_mcp import TM1MCPClient, TM1MCPError, tm1_is_configured
from tm1_tools import OPENAI_TOOL_DEFINITIONS, execute_tm1_tool


SYSTEM_PROMPT = """Você é um assistente virtual chamado ChatBot, especializado em IBM Planning Analytics / TM1.
Responda sempre em português brasileiro de forma clara, concisa e educada.

IMPORTANTE: Você TEM acesso ao servidor TM1 via ferramentas. NUNCA diga que não pode acessar dados,
cubos ou o ambiente TM1. Sempre use as ferramentas para consultar antes de responder.

Quando o usuário pedir dados, valores, totais ou informações de um ano (ex: 2025):
1. Use tm1_get_cube_data com cube_name e year — ela monta o MDX automaticamente
2. Se não souber o cubo, chame tm1_list_cubes primeiro
3. Só use tm1_execute_mdx se precisar de MDX customizado

Exemplo: tm1_get_cube_data(cube_name="RTB.100.DRE_Produto", year="2025")

Nunca invente nomes de cubos, dimensões ou valores numéricos.

Capacidades TM1:
- Listar cubos, dimensões e processos
- Executar consultas MDX para obter valores de células
- Buscar texto no modelo e nas regras
- Ler regras de cubos e listar elementos de dimensões"""


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
        "Posso consultar seu TM1: listar cubos/dimensões, executar MDX, buscar no modelo "
        "e ler regras. Experimente: 'Busca cubos com Vendas' ou 'Lista os processos TI'.",
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


MAX_TM1_ITERATIONS = int(os.getenv("TM1_MAX_ITERATIONS", "20"))


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


def _run_with_tools(
    client: OpenAI,
    messages: list[dict],
    mcp_client: TM1MCPClient,
    model: str,
) -> tuple[str, str]:
    tools = _build_tools()
    api_messages = [{"role": "system", "content": SYSTEM_PROMPT}, *messages]
    force_tools = _needs_tm1_tools(messages)
    temperature = 0.2 if force_tools else 0.7

    for iteration in range(MAX_TM1_ITERATIONS):
        kwargs: dict = {
            "model": model,
            "messages": api_messages,
            "max_tokens": 1024,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools
            if force_tools and iteration == 0:
                kwargs["tool_choice"] = "required"

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

    # Limite atingido — tenta resumir o que já foi consultado
    try:
        summary = client.chat.completions.create(
            model=model,
            messages=[
                *api_messages,
                {
                    "role": "user",
                    "content": (
                        "Com base nos dados TM1 já consultados acima, responda ao usuário "
                        "de forma clara. Se a consulta ficou incompleta, explique o que foi "
                        "possível obter."
                    ),
                },
            ],
            max_tokens=1024,
            temperature=0.3,
        )
        content = summary.choices[0].message.content
        if content:
            return content, "ai+tm1"
    except Exception:
        pass

    return (
        "A consulta ao TM1 exigiu muitas etapas. Tente uma pergunta mais específica, "
        "informando o nome do cubo (ex: RTB.100.DRE_Produto) e o ano desejado.",
        "ai+tm1",
    )


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
