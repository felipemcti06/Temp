import uuid
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from chat_engine import generate_response

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


@app.get("/api/health", response_model=HealthResponse)
async def health():
    from chat_engine import _has_openai_key

    return HealthResponse(
        status="ok",
        mode="ai" if _has_openai_key() else "fallback",
        sessions=len(sessions),
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
