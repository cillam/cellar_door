"""FastAPI entrypoint.

No business logic here — routers, providers, and the graph get wired in
later steps. This file's only job right now is to prove the app boots
and to expose a health endpoint for deploy checks (Railway) and CI.
"""

from fastapi import FastAPI

app = FastAPI(title="Cellar Door API")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
