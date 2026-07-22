import uuid
import os
from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from auth import (
    auth_is_enabled,
    create_access_token,
    get_current_user,
    get_optional_user,
    verify_credentials,
)
from chat_engine import any_llm_configured, generate_response
from llm_config import list_available_models, resolve_default_model_id
from tm1_mcp import TM1MCPClient, TM1MCPError, get_default_connection_id, tm1_is_configured

app = FastAPI(
    title="ChatBot API",
    description="API do assistente virtual ChatBot",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

sessions: dict[str, list[dict]] = {}


class MessageRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    session_id: str | None = None
    model_id: str | None = None


class MessageResponse(BaseModel):
    response: str
    session_id: str
    mode: str
    model_id: str | None = None
    timestamp: str


class HealthResponse(BaseModel):
    status: str
    mode: str
    sessions: int
    tm1: bool
    llm: bool


class ModelsResponse(BaseModel):
    models: list[dict]
    default: str | None


class TM1StatusResponse(BaseModel):
    configured: bool
    connection_id: str | None
    mcp_url: str | None
    ping: dict | None = None
    error: str | None = None


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1, max_length=200)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 86400


class AuthStatusResponse(BaseModel):
    auth_required: bool
    authenticated: bool = False
    username: str | None = None


def _resolve_mode() -> str:
    if any_llm_configured() and tm1_is_configured():
        return "ai+tm1"
    if any_llm_configured():
        return "ai"
    return "fallback"


@app.get("/api/health", response_model=HealthResponse)
async def health():
    return HealthResponse(
        status="ok",
        mode=_resolve_mode(),
        sessions=len(sessions),
        tm1=tm1_is_configured(),
        llm=any_llm_configured(),
    )


@app.get("/api/auth/status", response_model=AuthStatusResponse)
async def auth_status(user: str | None = Depends(get_optional_user)):
    return AuthStatusResponse(
        auth_required=auth_is_enabled(),
        authenticated=user is not None,
        username=user,
    )


@app.post("/api/auth/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    if not auth_is_enabled():
        raise HTTPException(status_code=400, detail="Autenticação não está configurada no servidor")

    if not verify_credentials(request.username, request.password):
        raise HTTPException(status_code=401, detail="Usuário ou senha incorretos")

    token = create_access_token(request.username)
    return LoginResponse(access_token=token)


@app.get("/api/models", response_model=ModelsResponse)
async def models(_user: str | None = Depends(get_current_user)):
    return ModelsResponse(
        models=list_available_models(),
        default=resolve_default_model_id(),
    )


@app.get("/api/tm1/status", response_model=TM1StatusResponse)
async def tm1_status(_user: str | None = Depends(get_current_user)):
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
async def chat(request: MessageRequest, _user: str | None = Depends(get_current_user)):
    session_id = request.session_id or str(uuid.uuid4())

    if session_id not in sessions:
        sessions[session_id] = []

    sessions[session_id].append({"role": "user", "content": request.message.strip()})

    try:
        response_text, mode = generate_response(
            sessions[session_id],
            model_id=request.model_id,
        )
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
        model_id=request.model_id or resolve_default_model_id(),
        timestamp=datetime.utcnow().isoformat() + "Z",
    )


@app.delete("/api/chat/{session_id}")
async def clear_session(session_id: str, _user: str | None = Depends(get_current_user)):
    sessions.pop(session_id, None)
    return {"status": "cleared", "session_id": session_id}
