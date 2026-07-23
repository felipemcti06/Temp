import os
import re
from collections.abc import Callable

from agents.fast_path import try_fast_report_path
from agents.orchestrator import run_report_pipeline
from llm_config import has_anthropic_key, has_openai_key, resolve_model_id
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
        "Escolha o modelo no seletor acima do chat. "
        "Para relatórios HTML, uso um agente de dados (modelo econômico) "
        "e um agente de relatório (modelo premium).",
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


def _needs_report(messages: list[dict]) -> bool:
    last_user = next(
        (m["content"] for m in reversed(messages) if m["role"] == "user"),
        "",
    )
    text = last_user.lower()
    return bool(
        re.search(r"\b(html|relatório|relatorio|dashboard|executivo|gráfico|grafico)\b", text)
    )


def _needs_tm1_tools(messages: list[dict]) -> bool:
    last_user = next(
        (m["content"] for m in reversed(messages) if m["role"] == "user"),
        "",
    )
    text = last_user.lower()
    patterns = [
        r"\b(dados?|valores?|total|resumo|consulta|mostra|exibe|lista)\b",
        r"\b20\d{2}\b",
        r"\b(cubo|cubos|mdx|tm1|dimensão|dimensões|rentabilidade|dre|ebitda)\b",
        r"\b(financeiro|rateio|receita|despesa)\b",
        r"\b(html|relatório|relatorio|dashboard|executivo|gráfico|grafico)\b",
    ]
    return any(re.search(p, text) for p in patterns)


def _agents_enabled() -> bool:
    return os.getenv("ENABLE_REPORT_AGENTS", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def generate_response(
    messages: list[dict],
    model_id: str | None = None,
    *,
    username: str | None = None,
    status_cb: Callable[[str], None] | None = None,
) -> tuple[str, str, dict]:
    """Generate a chat response. Returns (response_text, mode, metadata)."""

    meta: dict = {"cache_hit": False}

    def emit(message: str) -> None:
        if status_cb:
            status_cb(message)

    try:
        option = resolve_model_id(model_id)
    except ValueError as exc:
        return str(exc), "error", meta

    if not option:
        last_user_msg = next(
            (m["content"] for m in reversed(messages) if m["role"] == "user"),
            "",
        )
        return _fallback_response(last_user_msg), "fallback", meta

    mcp_client = TM1MCPClient.from_env() if tm1_is_configured() else None
    wants_report = _needs_report(messages)

    emit("Analisando pedido...")

    # Fase 2: fast path determinístico (glossário + Jinja2, sem LLM)
    if wants_report and mcp_client:
        fast_result = try_fast_report_path(
            messages,
            mcp_client,
            username=username,
            status_cb=status_cb,
        )
        if fast_result:
            text, mode, fast_meta = fast_result
            meta.update(fast_meta)
            return text, mode, meta

    # Fase 1: pipeline de subagentes para pedidos de relatório HTML
    if wants_report and mcp_client and _agents_enabled():
        try:
            text, mode = run_report_pipeline(
                messages,
                option,
                mcp_client=mcp_client,
                username=username,
                status_cb=status_cb,
            )
            return text, mode, meta
        except Exception as exc:
            # Fallback para o fluxo monolítico se o pipeline falhar
            err_note = f"(Pipeline de agentes falhou: {exc}. Usando fluxo padrão.)\n\n"
            emit("Usando fluxo alternativo...")
            force_tools = True
            text, mode = generate_with_model(
                messages,
                option,
                mcp_client=mcp_client,
                force_tools=force_tools,
                needs_report=True,
                username=username,
                status_cb=status_cb,
            )
            return err_note + text, f"{mode}+fallback", meta

    force_tools = bool(mcp_client and (_needs_tm1_tools(messages) or wants_report))
    if force_tools:
        emit("Consultando TM1 e gerando resposta...")
    else:
        emit("Gerando resposta...")

    text, mode = generate_with_model(
        messages,
        option,
        mcp_client=mcp_client,
        force_tools=force_tools,
        needs_report=wants_report,
        username=username,
        status_cb=status_cb,
    )
    return text, mode, meta


def any_llm_configured() -> bool:
    return has_openai_key() or has_anthropic_key()
