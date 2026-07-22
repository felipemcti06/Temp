"""Loop genérico de LLM + tools, reutilizável por agentes."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Callable

from anthropic import Anthropic
from openai import OpenAI

from llm_config import ModelOption
from report_tools import execute_report_tool
from tm1_mcp import TM1MCPClient, TM1MCPError
from tm1_tools import execute_tm1_tool

DEFAULT_MAX_ITERATIONS = int(os.getenv("TM1_MAX_ITERATIONS", "20"))

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

Para gráficos interativos, use Chart.js com container fixo (evita expansão infinita):
<div class="chart-container"><canvas id="chart"></canvas></div>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script>new Chart(document.getElementById('chart'), { options: { responsive: true, maintainAspectRatio: true, aspectRatio: 2.2 } });</script>
NUNCA use maintainAspectRatio: false nem height no canvas.

Nunca invente nomes de cubos, dimensões ou valores numéricos.

Capacidades TM1:
- Listar cubos, dimensões e processos
- Executar consultas MDX para obter valores de células
- Buscar texto no modelo e nas regras
- Ler regras de cubos e listar elementos de dimensões
- Publicar relatórios HTML em /relatorio/{id}"""


ToolExecutor = Callable[[str, dict[str, Any]], str]


@dataclass
class ToolLoopConfig:
    messages: list[dict]
    tools: list[dict[str, Any]]
    system_prompt: str
    mcp_client: TM1MCPClient | None = None
    username: str | None = None
    force_tools: bool = False
    needs_report: bool = False
    max_iterations: int = DEFAULT_MAX_ITERATIONS
    max_tokens: int = 8192
    temperature: float = 0.2
    mode_prefix: str = "ai"
    tool_executor: ToolExecutor | None = None
    report_created: bool = False
    report_url: str | None = None
    tool_trace: list[dict[str, Any]] = field(default_factory=list)

    def should_force_tools(self) -> bool:
        if self.needs_report and not self.report_created:
            return True
        return self.force_tools

    def note_tool_results(
        self,
        tool_calls: list[tuple[str, str, dict]],
        results: list[tuple[str, str]],
    ) -> None:
        for (_, fn_name, args), (_, result) in zip(tool_calls, results):
            entry: dict[str, Any] = {
                "tool": fn_name,
                "args": args,
                "result_preview": result[:500],
            }
            # Manter payload completo para tools estruturadas usadas pelo pipeline
            if fn_name in {"tm1_get_time_series", "create_html_report"}:
                entry["result"] = result
            self.tool_trace.append(entry)
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
            "completo (título, resumo executivo, tabela de dados e gráfico se pedido). "
            "Não responda apenas com texto."
        )


def default_tool_executor(
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


def _to_anthropic_tools(tools: list[dict]) -> list[dict]:
    return [
        {
            "name": t["function"]["name"],
            "description": t["function"]["description"],
            "input_schema": t["function"]["parameters"],
        }
        for t in tools
    ]


def _run_tool_calls(cfg: ToolLoopConfig, tool_calls: list[tuple[str, str, dict]]) -> list[tuple[str, str]]:
    results = []
    executor = cfg.tool_executor
    for call_id, fn_name, fn_args in tool_calls:
        try:
            if executor:
                result = executor(fn_name, fn_args)
            else:
                result = default_tool_executor(
                    cfg.mcp_client, fn_name, fn_args, username=cfg.username
                )
        except (TM1MCPError, json.JSONDecodeError, KeyError, ValueError) as exc:
            result = f"Erro ao executar {fn_name}: {exc}"
        results.append((call_id, result))
    return results


def _finalize_response(content: str, cfg: ToolLoopConfig) -> str:
    text = content.strip() or "Não consegui gerar uma resposta."
    if cfg.report_url and cfg.report_url not in text:
        text = f"{text}\n\nRelatório publicado: {cfg.report_url}"
    return text


def _openai_tool_loop(client: OpenAI, model: str, cfg: ToolLoopConfig) -> tuple[str, str]:
    api_messages = [{"role": "system", "content": cfg.system_prompt}, *cfg.messages]
    temperature = cfg.temperature if cfg.should_force_tools() else max(cfg.temperature, 0.5)

    for _ in range(cfg.max_iterations):
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": api_messages,
            "max_tokens": cfg.max_tokens,
            "temperature": temperature,
        }
        if cfg.tools:
            kwargs["tools"] = cfg.tools
            if cfg.should_force_tools():
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
            tool_results = _run_tool_calls(cfg, tool_batch)
            cfg.note_tool_results(tool_batch, tool_results)
            for call_id, result in tool_results:
                api_messages.append({"role": "tool", "tool_call_id": call_id, "content": result})
            if not cfg.needs_report or cfg.report_created:
                cfg.force_tools = False
            continue

        content = message.content or ""
        if cfg.needs_report and not cfg.report_created:
            api_messages.append({"role": "assistant", "content": content or "..."})
            api_messages.append({"role": "user", "content": cfg.report_pending_nudge()})
            continue

        suffix = "+tm1" if cfg.mcp_client else ""
        return _finalize_response(content, cfg), f"{cfg.mode_prefix}{suffix}"

    return (
        "Não foi possível concluir a solicitação. "
        + (
            "O relatório HTML não foi publicado — tente novamente."
            if cfg.needs_report and not cfg.report_created
            else "Tente uma pergunta mais específica."
        ),
        f"{cfg.mode_prefix}+tm1" if cfg.mcp_client else cfg.mode_prefix,
    )


def _anthropic_tool_loop(client: Anthropic, model: str, cfg: ToolLoopConfig) -> tuple[str, str]:
    anthropic_messages = [
        {"role": m["role"], "content": m["content"]}
        for m in cfg.messages
        if m["role"] in ("user", "assistant")
    ]
    tools = _to_anthropic_tools(cfg.tools) if cfg.tools else None

    for _ in range(cfg.max_iterations):
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": cfg.max_tokens,
            "system": cfg.system_prompt,
            "messages": anthropic_messages,
        }
        if tools:
            kwargs["tools"] = tools
            if cfg.should_force_tools():
                kwargs["tool_choice"] = {"type": "any"}

        response = client.messages.create(**kwargs)

        if response.stop_reason == "tool_use":
            anthropic_messages.append({"role": "assistant", "content": response.content})
            tool_calls = [
                (block.id, block.name, block.input if isinstance(block.input, dict) else {})
                for block in response.content
                if block.type == "tool_use"
            ]
            tool_results = _run_tool_calls(cfg, tool_calls)
            cfg.note_tool_results(tool_calls, tool_results)
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
            if not cfg.needs_report or cfg.report_created:
                cfg.force_tools = False
            continue

        parts = [block.text for block in response.content if block.type == "text"]
        content = "".join(parts)
        if cfg.needs_report and not cfg.report_created:
            anthropic_messages.append({"role": "assistant", "content": response.content})
            anthropic_messages.append({"role": "user", "content": cfg.report_pending_nudge()})
            continue

        suffix = "+tm1" if cfg.mcp_client else ""
        return _finalize_response(content, cfg), f"{cfg.mode_prefix}{suffix}"

    return (
        "Não foi possível concluir a solicitação. "
        + (
            "O relatório HTML não foi publicado — tente novamente."
            if cfg.needs_report and not cfg.report_created
            else "Tente uma pergunta mais específica."
        ),
        f"{cfg.mode_prefix}+tm1" if cfg.mcp_client else cfg.mode_prefix,
    )


def run_tool_loop(option: ModelOption, cfg: ToolLoopConfig) -> tuple[str, str]:
    """Executa um loop LLM+tools com configuração customizada."""
    if option.provider == "openai":
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        return _openai_tool_loop(client, option.model, cfg)

    if option.provider == "anthropic":
        client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        return _anthropic_tool_loop(client, option.model, cfg)

    raise ValueError(f"Provedor não suportado: {option.provider}")


def generate_with_model(
    messages: list[dict],
    option: ModelOption,
    *,
    mcp_client: TM1MCPClient | None,
    force_tools: bool,
    needs_report: bool = False,
    username: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    system_prompt: str | None = None,
    mode_prefix: str | None = None,
    max_iterations: int | None = None,
) -> tuple[str, str]:
    from report_tools import REPORT_TOOL_DEFINITIONS
    from tm1_tools import OPENAI_TOOL_DEFINITIONS

    if tools is None:
        tools = list(REPORT_TOOL_DEFINITIONS)
        if mcp_client is not None:
            tools.extend(OPENAI_TOOL_DEFINITIONS)

    use_tools = force_tools or needs_report or mcp_client is not None
    prefix = mode_prefix or option.provider

    if not use_tools or not tools:
        if option.provider == "openai":
            client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            completion = client.chat.completions.create(
                model=option.model,
                messages=[
                    {"role": "system", "content": system_prompt or SYSTEM_PROMPT},
                    *messages,
                ],
                max_tokens=1024,
                temperature=0.7,
            )
            return completion.choices[0].message.content or "", prefix

        if option.provider == "anthropic":
            client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
            response = client.messages.create(
                model=option.model,
                max_tokens=1024,
                system=system_prompt or SYSTEM_PROMPT,
                messages=[
                    {"role": m["role"], "content": m["content"]}
                    for m in messages
                    if m["role"] in ("user", "assistant")
                ],
            )
            text = "".join(b.text for b in response.content if b.type == "text")
            return text or "", prefix

        raise ValueError(f"Provedor não suportado: {option.provider}")

    cfg = ToolLoopConfig(
        messages=messages,
        tools=tools,
        system_prompt=system_prompt or SYSTEM_PROMPT,
        mcp_client=mcp_client,
        username=username,
        force_tools=force_tools,
        needs_report=needs_report,
        max_iterations=max_iterations or DEFAULT_MAX_ITERATIONS,
        mode_prefix=prefix,
    )
    return run_tool_loop(option, cfg)
