import json
import os
import re
from typing import Any

from anthropic import Anthropic
from openai import OpenAI

from llm_config import ModelOption
from report_tools import REPORT_TOOL_DEFINITIONS, execute_report_tool
from tm1_mcp import TM1MCPClient, TM1MCPError
from tm1_tools import OPENAI_TOOL_DEFINITIONS, execute_tm1_tool

SYSTEM_PROMPT = """Você é um assistente virtual chamado ChatBot, especializado em IBM Planning Analytics / TM1.
Responda sempre em português brasileiro de forma clara, concisa e educada.

IMPORTANTE: Você TEM acesso ao servidor TM1 via ferramentas. NUNCA diga que não pode acessar dados,
cubos ou o ambiente TM1. Sempre use as ferramentas para consultar antes de responder.

Quando o usuário pedir dados, valores, totais ou informações de um ano (ex: 2025):
1. Use tm1_get_cube_data com cube_name e year — ela monta o MDX automaticamente
2. Se não souber o cubo, chame tm1_list_cubes ou tm1_search primeiro
3. Só use tm1_execute_mdx se precisar de MDX customizado

Quando o usuário pedir relatório, resumo executivo, dashboard ou HTML:
1. PRIMEIRO consulte o TM1 e obtenha os dados reais (use tm1_execute_mdx para séries mensais)
2. Analise tendências, variações e destaques
3. OBRIGATÓRIO: chame create_html_report com title e html — NUNCA diga "vou montar" sem chamar a ferramenta
4. Só depois de create_html_report retornar a URL, envie a resposta final com o link /relatorio/{id}

PROIBIDO encerrar com mensagens como "agora vou montar o relatório" sem ter chamado create_html_report.

Exemplo de HTML no relatório:
<h1>Título</h1>
<p>Resumo executivo...</p>
<table><thead>...</thead><tbody>...</tbody></table>

Nunca invente nomes de cubos, dimensões ou valores numéricos.

Capacidades TM1:
- Listar cubos, dimensões e processos
- Executar consultas MDX para obter valores de células
- Buscar texto no modelo e nas regras
- Ler regras de cubos e listar elementos de dimensões
- Publicar relatórios HTML em /relatorio/{id}"""


MAX_TM1_ITERATIONS = int(os.getenv("TM1_MAX_ITERATIONS", "20"))


class ToolLoopContext:
    def __init__(
        self,
        messages: list[dict],
        mcp_client: TM1MCPClient | None,
        force_tools: bool,
        username: str | None = None,
        needs_report: bool = False,
    ):
        self.messages = messages
        self.mcp_client = mcp_client
        self.force_tools = force_tools
        self.username = username
        self.needs_report = needs_report
        self.report_created = False
        self.report_url: str | None = None
        self.use_tm1 = mcp_client is not None
        self.tools: list[dict[str, Any]] = list(REPORT_TOOL_DEFINITIONS)
        if self.use_tm1:
            self.tools.extend(OPENAI_TOOL_DEFINITIONS)

    def should_force_tools(self) -> bool:
        if self.needs_report and not self.report_created:
            return True
        return self.force_tools

    def note_tool_results(self, tool_calls: list[tuple[str, str, dict]], results: list[tuple[str, str]]) -> None:
        for (_, fn_name, _), (_, result) in zip(tool_calls, results):
            if fn_name != "create_html_report":
                continue
            try:
                payload = json.loads(result)
            except json.JSONDecodeError:
                continue
            if payload.get("url"):
                self.report_created = True
                self.report_url = payload["url"]

    def report_pending_nudge(self) -> str:
        return (
            "Você ainda NÃO publicou o relatório. Chame create_html_report AGORA com o HTML "
            "completo (título, resumo executivo, tabela de dados). Não responda apenas com texto."
        )


def _to_anthropic_tools(tools: list[dict]) -> list[dict]:
    return [
        {
            "name": t["function"]["name"],
            "description": t["function"]["description"],
            "input_schema": t["function"]["parameters"],
        }
        for t in tools
    ]


def _execute_tool(
    mcp_client: TM1MCPClient | None,
    fn_name: str,
    fn_args: dict[str, Any],
    *,
    username: str | None,
) -> str:
    if fn_name == "create_html_report":
        return execute_report_tool(fn_args, created_by=username)

    if not mcp_client:
        return f"Ferramenta {fn_name} requer conexão TM1, que não está disponível."

    return execute_tm1_tool(mcp_client, fn_name, fn_args)


def _run_tool_calls(
    mcp_client: TM1MCPClient | None,
    tool_calls: list[tuple[str, str, dict]],
    *,
    username: str | None,
) -> list[tuple[str, str]]:
    results = []
    for call_id, fn_name, fn_args in tool_calls:
        try:
            result = _execute_tool(mcp_client, fn_name, fn_args, username=username)
        except (TM1MCPError, json.JSONDecodeError, KeyError, ValueError) as exc:
            result = f"Erro ao executar {fn_name}: {exc}"
        results.append((call_id, result))
    return results


def _finalize_response(content: str, ctx: ToolLoopContext) -> str:
    text = content.strip() or "Não consegui gerar uma resposta."
    if ctx.report_url and ctx.report_url not in text:
        text = f"{text}\n\nRelatório publicado: {ctx.report_url}"
    return text


def _openai_tool_loop(
    client: OpenAI,
    model: str,
    ctx: ToolLoopContext,
    mode_prefix: str,
) -> tuple[str, str]:
    api_messages = [{"role": "system", "content": SYSTEM_PROMPT}, *ctx.messages]
    temperature = 0.2 if ctx.should_force_tools() else 0.7

    for _ in range(MAX_TM1_ITERATIONS):
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": api_messages,
            "max_tokens": 8192,
            "temperature": temperature,
        }
        if ctx.tools:
            kwargs["tools"] = ctx.tools
            if ctx.should_force_tools():
                kwargs["tool_choice"] = "required"

        completion = client.chat.completions.create(**kwargs)
        choice = completion.choices[0]
        message = choice.message

        if choice.finish_reason == "tool_calls" and message.tool_calls:
            tool_batch = [
                (tc.id, tc.function.name, json.loads(tc.function.arguments or "{}"))
                for tc in message.tool_calls
            ]
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
            tool_results = _run_tool_calls(ctx.mcp_client, tool_batch, username=ctx.username)
            ctx.note_tool_results(tool_batch, tool_results)
            for call_id, result in tool_results:
                api_messages.append(
                    {"role": "tool", "tool_call_id": call_id, "content": result}
                )
            if not ctx.needs_report or ctx.report_created:
                ctx.force_tools = False
            continue

        content = message.content or ""
        if ctx.needs_report and not ctx.report_created:
            api_messages.append({"role": "assistant", "content": content or "..."})
            api_messages.append({"role": "user", "content": ctx.report_pending_nudge()})
            continue

        suffix = "+tm1" if ctx.use_tm1 else ""
        return _finalize_response(content, ctx), f"{mode_prefix}{suffix}"

    return (
        "Não foi possível concluir a solicitação. "
        + (
            "O relatório HTML não foi publicado — tente novamente."
            if ctx.needs_report and not ctx.report_created
            else "Tente uma pergunta mais específica."
        ),
        f"{mode_prefix}+tm1" if ctx.use_tm1 else mode_prefix,
    )


def _anthropic_tool_loop(
    client: Anthropic,
    model: str,
    ctx: ToolLoopContext,
    mode_prefix: str,
) -> tuple[str, str]:
    anthropic_messages = [
        {"role": m["role"], "content": m["content"]}
        for m in ctx.messages
        if m["role"] in ("user", "assistant")
    ]
    tools = _to_anthropic_tools(ctx.tools) if ctx.tools else None

    for _ in range(MAX_TM1_ITERATIONS):
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": 8192,
            "system": SYSTEM_PROMPT,
            "messages": anthropic_messages,
        }
        if tools:
            kwargs["tools"] = tools
            if ctx.should_force_tools():
                kwargs["tool_choice"] = {"type": "any"}

        response = client.messages.create(**kwargs)

        if response.stop_reason == "tool_use":
            anthropic_messages.append({"role": "assistant", "content": response.content})
            tool_calls = [
                (block.id, block.name, block.input if isinstance(block.input, dict) else {})
                for block in response.content
                if block.type == "tool_use"
            ]
            tool_results = _run_tool_calls(
                ctx.mcp_client, tool_calls, username=ctx.username
            )
            ctx.note_tool_results(tool_calls, tool_results)
            anthropic_messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": call_id,
                            "content": result,
                        }
                        for call_id, result in tool_results
                    ],
                }
            )
            if not ctx.needs_report or ctx.report_created:
                ctx.force_tools = False
            continue

        parts = [block.text for block in response.content if block.type == "text"]
        content = "".join(parts)
        if ctx.needs_report and not ctx.report_created:
            anthropic_messages.append({"role": "assistant", "content": response.content})
            anthropic_messages.append({"role": "user", "content": ctx.report_pending_nudge()})
            continue

        suffix = "+tm1" if ctx.use_tm1 else ""
        return _finalize_response(content, ctx), f"{mode_prefix}{suffix}"

    return (
        "Não foi possível concluir a solicitação. "
        + (
            "O relatório HTML não foi publicado — tente novamente."
            if ctx.needs_report and not ctx.report_created
            else "Tente uma pergunta mais específica."
        ),
        f"{mode_prefix}+tm1" if ctx.use_tm1 else mode_prefix,
    )


def _should_use_tools(mcp_client: TM1MCPClient | None, force_tools: bool) -> bool:
    return force_tools or mcp_client is not None


def generate_with_model(
    messages: list[dict],
    option: ModelOption,
    *,
    mcp_client: TM1MCPClient | None,
    force_tools: bool,
    needs_report: bool = False,
    username: str | None = None,
) -> tuple[str, str]:
    ctx = ToolLoopContext(
        messages, mcp_client, force_tools, username=username, needs_report=needs_report
    )
    use_tools = _should_use_tools(mcp_client, force_tools)

    if option.provider == "openai":
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        if use_tools:
            return _openai_tool_loop(client, option.model, ctx, "openai")
        completion = client.chat.completions.create(
            model=option.model,
            messages=[{"role": "system", "content": SYSTEM_PROMPT}, *messages],
            max_tokens=1024,
            temperature=0.7,
        )
        return completion.choices[0].message.content or "", "openai"

    if option.provider == "anthropic":
        client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        if use_tools:
            return _anthropic_tool_loop(client, option.model, ctx, "anthropic")
        response = client.messages.create(
            model=option.model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[
                {"role": m["role"], "content": m["content"]}
                for m in messages
                if m["role"] in ("user", "assistant")
            ],
        )
        text = "".join(b.text for b in response.content if b.type == "text")
        return text or "", "anthropic"

    raise ValueError(f"Provedor não suportado: {option.provider}")
