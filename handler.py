import asyncio
import logging
import time
import json
import httpx
from fastapi import Request, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse

from pool import KeyPool

logger = logging.getLogger(__name__)

class RequestHandler:
    def __init__(self, pool: KeyPool, base_url: str, timeout: int = 120, max_retries: int = 2):
        self.pool = pool
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
    
    async def forward(self, method: str, path: str, request: Request):
        key_obj = await self.pool.get_available_key()
        if not key_obj:
            raise HTTPException(status_code=429, detail="No available API keys")
        
        key = key_obj.key
        target_url = f"{self.base_url}/{path}"
        
        body = None
        is_stream = False
        if method in ("POST", "PUT", "PATCH"):
            body = await request.body()
            try:
                parsed = json.loads(body)
                is_stream = parsed.get("stream", False)
            except Exception:
                pass
        
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        
        for attempt in range(self.max_retries + 1):
            start_time = time.time()
            try:
                if is_stream:
                    return await self._handle_stream(method, target_url, body, headers, key)
                
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.request(method, target_url, content=body, headers=headers)
                    latency_ms = (time.time() - start_time) * 1000
                    
                    if resp.status_code == 429:
                        await self.pool.report_failure(key, is_rate_limit=True)
                        if attempt < self.max_retries:
                            continue
                        raise HTTPException(status_code=429, detail="Rate limited")
                    
                    if resp.status_code >= 500:
                        await self.pool.report_failure(key)
                        if attempt < self.max_retries:
                            await asyncio.sleep(0.5 * (attempt + 1))
                            continue
                    
                    if resp.status_code >= 400:
                        return JSONResponse(content=resp.json(), status_code=resp.status_code)
                    
                    await self.pool.report_success(key, latency_ms)
                    return JSONResponse(content=resp.json(), status_code=resp.status_code)
                    
            except httpx.TimeoutException:
                await self.pool.report_failure(key)
                if attempt < self.max_retries:
                    continue
                raise HTTPException(status_code=504, detail="Upstream timeout")
            except httpx.RequestError as e:
                await self.pool.report_failure(key)
                if attempt < self.max_retries:
                    continue
                raise HTTPException(status_code=502, detail=f"Upstream error: {str(e)}")
        
        raise HTTPException(status_code=503, detail="Service unavailable after retries")
    
    async def _handle_stream(self, method: str, url: str, body: bytes, headers: dict, key: str):
        async def generate():
            start_time = time.time()
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    async with client.stream(method, url, content=body, headers=headers) as resp:
                        if resp.status_code == 429:
                            await self.pool.report_failure(key, is_rate_limit=True)
                            yield json.dumps({"error": "Rate limited"}).encode()
                            return
                        async for chunk in resp.aiter_bytes():
                            yield chunk
                        latency_ms = (time.time() - start_time) * 1000
                        await self.pool.report_success(key, latency_ms)
            except Exception as e:
                await self.pool.report_failure(key)
                yield json.dumps({"error": str(e)}).encode()
        
        return StreamingResponse(generate(), media_type="text/event-stream")
