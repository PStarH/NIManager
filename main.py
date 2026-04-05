import asyncio
import logging
import signal
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional

from config import settings
from pool import KeyPool, KeyStatus
from handler import RequestHandler, close_client
from storage import KeyStorage
from health import HealthChecker
from middleware import RequestLoggerMiddleware

logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

pool: KeyPool = None
handler: RequestHandler = None
storage: KeyStorage = None
health_checker: HealthChecker = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool, handler, storage, health_checker
    
    storage = KeyStorage(settings.database_url.replace("sqlite+aiosqlite:///", ""))
    await storage.init()
    
    pool = KeyPool(
        rpm_limit=settings.rpm_limit,
        window_seconds=settings.window_seconds,
        max_consecutive_failures=settings.max_consecutive_failures
    )
    
    saved_keys = await storage.load_all_keys()
    for k in saved_keys:
        await pool.add_key(k["key"], k["name"])
        if k["status"] == "disabled":
            await pool.disable_key(k["key"])
    
    if settings.api_keys:
        for key in settings.api_keys:
            try:
                await pool.add_key(key)
                await storage.save_key(key)
            except ValueError:
                pass
    
    logger.info(f"Loaded {len(pool._keys)} API keys")
    
    handler = RequestHandler(
        pool=pool,
        base_url=settings.nim_base_url,
        timeout=settings.request_timeout,
        max_retries=settings.max_retries
    )
    
    health_checker = HealthChecker(
        pool=pool,
        base_url=settings.nim_base_url,
        interval=settings.health_check_interval
    )
    await health_checker.start()
    
    yield
    
    logger.info("Shutting down...")
    await health_checker.stop()
    await close_client()
    await storage.close()
    logger.info("Shutdown complete")

app = FastAPI(title="NIM API Pool", lifespan=lifespan)
app.add_middleware(RequestLoggerMiddleware)

class AddKeyRequest(BaseModel):
    key: str
    name: Optional[str] = ""

class KeyResponse(BaseModel):
    name: str
    key_preview: str
    status: str

@app.post("/admin/keys", response_model=KeyResponse)
async def add_key(req: AddKeyRequest):
    try:
        k = await pool.add_key(req.key, req.name)
        await storage.save_key(req.key, req.name)
        return KeyResponse(name=k.name, key_preview=k.key[:8]+"...", status=k.status.value)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.delete("/admin/keys/{key_preview}")
async def remove_key(key_preview: str):
    for k in list(pool._keys.keys()):
        if k.startswith(key_preview):
            await pool.remove_key(k)
            await storage.delete_key(k)
            return {"message": "Key removed"}
    raise HTTPException(status_code=404, detail="Key not found")

@app.post("/admin/keys/{key_preview}/disable")
async def disable_key(key_preview: str):
    for k in list(pool._keys.keys()):
        if k.startswith(key_preview):
            await pool.disable_key(k)
            await storage.update_status(k, "disabled")
            return {"message": "Key disabled"}
    raise HTTPException(status_code=404, detail="Key not found")

@app.post("/admin/keys/{key_preview}/enable")
async def enable_key(key_preview: str):
    for k in list(pool._keys.keys()):
        if k.startswith(key_preview):
            await pool.enable_key(k)
            await storage.update_status(k, "active")
            return {"message": "Key enabled"}
    raise HTTPException(status_code=404, detail="Key not found")

@app.get("/admin/status")
async def get_status():
    return await pool.get_status()

@app.get("/health")
async def health():
    import psutil
    import platform
    
    status = await pool.get_status()
    
    health_data = {
        "status": "healthy" if status["active_keys"] > 0 else "unhealthy",
        "active_keys": status["active_keys"],
        "total_keys": status["total_keys"],
        "system": {
            "cpu_percent": psutil.cpu_percent(),
            "memory_percent": psutil.virtual_memory().percent,
            "python_version": platform.python_version(),
            "platform": platform.system()
        }
    }
    
    if status["active_keys"] == 0:
        return JSONResponse(status_code=503, content=health_data)
    return health_data

@app.get("/admin/latency")
async def test_latency(model: str = "meta/llama-3.1-8b-instruct", prompt: str = "Hello"):
    import httpx
    import time
    
    key_obj = await pool.get_available_key()
    if not key_obj:
        raise HTTPException(status_code=503, detail="No available keys")
    
    start = time.time()
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{settings.nim_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {key_obj.key}"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 50
                }
            )
        latency = (time.time() - start) * 1000
        return {
            "model": model,
            "latency_ms": round(latency, 2),
            "status_code": resp.status_code,
            "success": resp.status_code == 200,
            "response": resp.json() if resp.status_code == 200 else None
        }
    except Exception as e:
        return {"model": model, "latency_ms": None, "error": str(e), "success": False}

@app.get("/admin/models")
async def list_models():
    import httpx
    
    key_obj = await pool.get_available_key()
    if not key_obj:
        raise HTTPException(status_code=503, detail="No available keys")
    
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{settings.nim_base_url}/models",
            headers={"Authorization": f"Bearer {key_obj.key}"}
        )
        return resp.json()

@app.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy(path: str, request: Request):
    return await handler.forward(request.method, path, request)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
