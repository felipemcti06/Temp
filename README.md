# ChatBot

Assistente virtual com interface web moderna, construído com **React** (frontend) e **FastAPI** (backend).

## Funcionalidades

- Interface de chat responsiva com tema escuro
- Respostas inteligentes via OpenAI (quando configurado)
- Modo demonstração com respostas locais (sem API key)
- Histórico de conversa por sessão
- Sugestões rápidas para iniciar a conversa

## Pré-requisitos

- Python 3.10+
- Node.js 18+

## Instalação

### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate   # Linux/macOS
pip install -r requirements.txt
```

### Frontend

```bash
cd frontend
npm install
```

### Configuração (opcional)

Copie o arquivo de exemplo e adicione sua chave da OpenAI para respostas com IA:

```bash
cp .env.example .env
```

Edite `.env`:

```
OPENAI_API_KEY=sk-sua-chave-aqui
OPENAI_MODEL=gpt-4o-mini
```

Sem a chave, o chatbot funciona em **modo demonstração** com respostas pré-definidas.

## Executar

Em dois terminais:

**Terminal 1 — Backend:**
```bash
cd backend
source venv/bin/activate
uvicorn main:app --reload --port 8000
```

**Terminal 2 — Frontend:**
```bash
cd frontend
npm run dev
```

Acesse: http://localhost:5173

## API

| Método | Endpoint | Descrição |
|--------|----------|-----------|
| GET | `/api/health` | Status do servidor e modo ativo |
| POST | `/api/chat` | Enviar mensagem e receber resposta |
| DELETE | `/api/chat/{session_id}` | Limpar histórico da sessão |

### Exemplo de requisição

```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Olá!"}'
```

## Estrutura do projeto

```
├── backend/
│   ├── main.py           # API FastAPI
│   ├── chat_engine.py    # Lógica de respostas (IA + fallback)
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   └── components/
│   └── package.json
└── .env.example
```

## Tecnologias

- [React](https://react.dev/) + [Vite](https://vitejs.dev/)
- [FastAPI](https://fastapi.tiangolo.com/)
- [OpenAI API](https://platform.openai.com/) (opcional)
