import time
import json
import logging
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

class RequestLoggerMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.time()
        
        # 读取请求体
        body = None
        if request.method in ("POST", "PUT", "PATCH"):
            body = await request.body()
            # 重新包装 request 以便后续使用
            async def receive():
                return {"type": "http.request", "body": body}
            request._receive = receive
        
        response = await call_next(request)
        duration = (time.time() - start) * 1000
        
        if request.url.path.startswith("/v1/"):
            log_data = {
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round(duration)
            }
            
            # 解析请求体获取 token 信息
            if body:
                try:
                    req_json = json.loads(body)
                    if "messages" in req_json:
                        # 估算输入 token (粗略: 1 token ≈ 4 chars)
                        msg_chars = sum(len(m.get("content", "")) for m in req_json.get("messages", []))
                        log_data["input_tokens_est"] = msg_chars // 4
                        log_data["model"] = req_json.get("model", "unknown")
                except:
                    pass
            
            logger.info(json.dumps(log_data))
        
        return response
