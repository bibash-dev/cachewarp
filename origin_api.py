from fastapi import FastAPI

app = FastAPI()

@app.get("/{path:path}")
async def mock_endpoint(path: str):
    return {"data": f"response_from_origin_for_{path}", "path": path}