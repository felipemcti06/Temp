import os
import re
from datetime import datetime

from openai import OpenAI


SYSTEM_PROMPT = """Você é um assistente virtual amigável e prestativo chamado ChatBot.
Responda sempre em português brasileiro de forma clara, concisa e educada.
Seja útil, empático e mantenha um tom conversacional natural."""


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
        "Posso conversar com você, responder perguntas gerais e ajudar com informações. "
        "Para respostas mais inteligentes, configure uma chave da API OpenAI no arquivo `.env`.",
        "Sou um chatbot! Posso bater papo, tirar dúvidas simples e ajudar no que precisar. "
        "Experimente me perguntar algo!",
    ],
    "default": [
        "Interessante! Conte-me mais sobre isso.",
        "Entendi. Pode elaborar um pouco mais?",
        "Hmm, boa pergunta! Para respostas mais detalhadas, configure a API OpenAI. "
        "Por enquanto, posso conversar sobre assuntos gerais.",
        "Estou processando... Na verdade, sem uma API de IA configurada, minhas respostas "
        "são limitadas. Mas adoraria continuar nossa conversa!",
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


def generate_response(messages: list[dict]) -> tuple[str, str]:
    """Generate a chat response. Returns (response_text, mode)."""
    if _has_openai_key():
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        api_messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for msg in messages:
            api_messages.append({"role": msg["role"], "content": msg["content"]})

        completion = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
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
