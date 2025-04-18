from fastapi import FastAPI
from fastapi.responses import JSONResponse
from typing import Dict, Any

app = FastAPI(
    title="Mock Origin API",
    description="A simple mock API to simulate the origin server for CacheWarp development and testing.",
    version="0.1.0",
)


@app.get("/{path:path}")
async def mock_endpoint(path: str) -> JSONResponse:
    """
    A generic mock endpoint that returns a JSON response containing the requested path.
    This is useful for simulating different origin responses during CacheWarp development.
    """
    return JSONResponse(
        content={"data": f"response_from_origin_for_{path}", "path": path}
    )
