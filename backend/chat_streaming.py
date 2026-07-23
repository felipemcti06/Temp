"""Helpers para streaming SSE do chat."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from typing import Any

StatusCallback = Callable[[str], None] | None


async def stream_chat_events(
    worker: Callable[[StatusCallback], tuple[str, str]],
    *,
    extra_done: dict[str, Any] | None = None,
) -> AsyncIterator[str]:
    """Executa worker em thread e emite eventos SSE de status + done/error."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

    def status_cb(message: str) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, ("status", message))

    async def run_worker() -> None:
        try:
            text, mode = await asyncio.to_thread(worker, status_cb)
            payload = {"response": text, "mode": mode}
            if extra_done:
                payload.update(extra_done)
            await queue.put(("done", payload))
        except Exception as exc:
            await queue.put(("error", {"detail": str(exc)}))

    task = asyncio.create_task(run_worker())

    while True:
        kind, payload = await queue.get()
        if kind == "status":
            yield _sse_event("status", {"message": payload})
            continue
        if kind == "done":
            yield _sse_event("done", payload)
            break
        if kind == "error":
            yield _sse_event("error", payload)
            break

    await task


def _sse_event(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
