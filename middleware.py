import time
import logging
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

class RequestLoggerMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.time()
        response = await call_next(request)
        duration = (time.time() - start) * 1000
        
        if request.url.path.startswith("/v1/"):
            logger.info(f"{request.method} {request.url.path} {response.status_code} {duration:.0f}ms")
        
        return response
