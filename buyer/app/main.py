import asyncio
import json
import os
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from . import tools
from .agent import run_agent

OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

# session_id -> list of (event, json_str); subscribers get live events via queues
_history: dict[str, list] = defaultdict(list)
_queues: dict[str, list] = defaultdict(list)


def _emit(session_id: str, event: str, data: dict):
    item = (event, json.dumps(data, default=str))
    _history[session_id].append(item)
    for q in _queues[session_id]:
        q.put_nowait(item)


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("=" * 60)
    print(f"  BUYER AGENT  |  merchant={tools.MERCHANT_BASE_URL}  model={OPENAI_MODEL}")
    print("=" * 60)
    yield


app = FastAPI(title="Buyer Agent (agentic-commerce MVP)", lifespan=lifespan)


class SessionIn(BaseModel):
    merchant_url: str = ""
    goal: str


@app.post("/session")
async def create_session(body: SessionIn):
    session_id = uuid.uuid4().hex
    _history[session_id] = []
    # merchant_url from the UI is a BROWSER-facing address (used for approval links).
    # All agent→merchant HTTP calls use the internal MERCHANT_BASE_URL (docker network);
    # overwriting it with a browser URL breaks connectivity inside the container.
    _emit(session_id, "status", {"text": "session created"})

    async def runner():
        def emit(event: str, data: dict):
            _emit(session_id, event, data)
        try:
            await run_agent(body.goal, emit, OPENAI_API_KEY, OPENAI_MODEL)
        except Exception as e:  # noqa: BLE001
            _emit(session_id, "done", {"result": f"agent error: {e}"})

    asyncio.create_task(runner())
    return {"session_id": session_id}


@app.get("/session/{session_id}/stream")
async def stream(session_id: str):
    async def gen():
        q: asyncio.Queue = asyncio.Queue()

        def sse(event: str, data: str) -> str:
            return f"event: {event}\ndata: {data}\n\n"

        for item in list(_history.get(session_id, [])):
            yield sse(*item)
            if item[0] == "done":
                return
        _queues[session_id].append(q)
        try:
            while True:
                event, data = await q.get()
                yield sse(event, data)
                if event == "done":
                    return
        finally:
            _queues[session_id].remove(q)

    return StreamingResponse(gen(), media_type="text/event-stream")
