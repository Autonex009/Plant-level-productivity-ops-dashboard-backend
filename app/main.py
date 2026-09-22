from fastapi import FastAPI

from app.api.router import api_router

app = FastAPI(title="Plant-Level Productivity & Ops Dashboard")
app.include_router(api_router, prefix="/api/v1")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
