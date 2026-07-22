import uuid
import os
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from chat_engine import _has_openai_key, generate_response
from tm1_mcp import TM1MCPClient, TM1MCPError, get_default_connection_id, tm1_is_configured

app = FastAPI(
    title="ChatBot API",
    description="API do assistente virtual ChatBot",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

sessions: dict[str, list[dict]] = {}


class MessageRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    session_id: str | None = None


class MessageResponse(BaseModel):
    response: str
    session_id: str
    mode: str
    timestamp: str


class HealthResponse(BaseModel):
    status: str
    mode: str
    sessions: int
    tm1: bool


class TM1StatusResponse(BaseModel):
    configured: bool
    connection_id: str | None
    mcp_url: str | None
    ping: dict | None = None
    error: str | None = None


def _resolve_mode() -> str:
    if _has_openai_key() and tm1_is_configured():
        return "ai+tm1"
    if _has_openai_key():
        return "ai"
    return "fallback"


@app.get("/api/health", response_model=HealthResponse)
async def health():
    return HealthResponse(
        status="ok",
        mode=_resolve_mode(),
        sessions=len(sessions),
        tm1=tm1_is_configured(),
    )


@app.get("/api/tm1/status", response_model=TM1StatusResponse)
async def tm1_status():
    client = TM1MCPClient.from_env()
    connection_id = get_default_connection_id()

    if not client or not connection_id:
        return TM1StatusResponse(
            configured=False,
            connection_id=connection_id,
            mcp_url=os.getenv("TM1_MCP_URL"),
            error="Configure TM1_MCP_URL, TM1_MCP_TOKEN e TM1_CONNECTION_ID",
        )

    try:
        ping = client.call_tool("ping", {"connection_id": connection_id})
        return TM1StatusResponse(
            configured=True,
            connection_id=connection_id,
            mcp_url=os.getenv("TM1_MCP_URL"),
            ping=ping if isinstance(ping, dict) else {"result": ping},
        )
    except TM1MCPError as exc:
        return TM1StatusResponse(
            configured=False,
            connection_id=connection_id,
            mcp_url=os.getenv("TM1_MCP_URL"),
            error=str(exc),
        )


@app.post("/api/chat", response_model=MessageResponse)
async def chat(request: MessageRequest):
    session_id = request.session_id or str(uuid.uuid4())

    if session_id not in sessions:
        sessions[session_id] = []

    sessions[session_id].append({"role": "user", "content": request.message.strip()})

    try:
        response_text, mode = generate_response(sessions[session_id])
    except Exception as exc:
        sessions[session_id].pop()
        raise HTTPException(status_code=500, detail=f"Erro ao gerar resposta: {exc}") from exc

    sessions[session_id].append({"role": "assistant", "content": response_text})

    if len(sessions[session_id]) > 40:
        sessions[session_id] = sessions[session_id][-40:]

    return MessageResponse(
        response=response_text,
        session_id=session_id,
        mode=mode,
        timestamp=datetime.utcnow().isoformat() + "Z",
    )


@app.delete("/api/chat/{session_id}")
async def clear_session(session_id: str):
    sessions.pop(session_id, None)
    return {"status": "cleared", "session_id": session_id}
