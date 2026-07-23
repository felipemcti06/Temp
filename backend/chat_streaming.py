"""Helpers para streaming SSE do chat."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

StatusCallback = Callable[[str], None] | None
WorkerResult = tuple[str, str] | tuple[str, str, dict[str, Any]]

KEEPALIVE_INTERVAL_SECONDS = float(
    __import__("os").getenv("SSE_KEEPALIVE_SECONDS", "15")
)


async def stream_chat_events(
    worker: Callable[[StatusCallback], WorkerResult],
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
            result = await asyncio.to_thread(worker, status_cb)
            if len(result) == 3:
                text, mode, worker_meta = result
            else:
                text, mode = result
                worker_meta = {}

            payload = {"response": text, "mode": mode}
            if worker_meta:
                payload.update(worker_meta)
            if extra_done:
                payload.update(extra_done)
            await queue.put(("done", payload))
        except Exception as exc:
            await queue.put(("error", {"detail": str(exc)}))

    task = asyncio.create_task(run_worker())

    while True:
        try:
            kind, payload = await asyncio.wait_for(
                queue.get(),
                timeout=KEEPALIVE_INTERVAL_SECONDS,
            )
        except asyncio.TimeoutError:
            yield _sse_comment("keep-alive")
            yield _sse_event("ping", {"ts": time.time()})
            if task.done():
                exc = task.exception()
                if exc:
                    yield _sse_event("error", {"detail": str(exc)})
                    break
            continue

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


def _sse_comment(text: str) -> str:
    return f": {text}\n\n"
