# NIM API Pool

企业级 NVIDIA NIM API 账号池管理工具，支持动态 Key 管理、智能负载均衡、自动健康检查。

## 特性

- **动态 Key 管理** - 运行时添加/移除/禁用 API Key，无需重启
- **智能负载均衡** - 轮询分配请求，自动避开限流和异常 Key
- **自动健康检查** - 后台定期探测异常 Key，自动恢复可用节点
- **自动重试** - 请求失败自动切换 Key 重试
- **持久化存储** - SQLite 存储 Key 配置，重启后自动恢复
- **流式支持** - 完整支持 SSE 流式响应
- **延迟测试** - 内置模型延迟测试接口

## 快速开始

```bash
# 克隆仓库
git clone https://github.com/yourusername/nim-api-pool.git
cd nim-api-pool

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env 添加你的 API Keys

# 启动服务
python main.py
```

## 配置

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `NIM_API_KEYS` | - | API Keys，逗号分隔 |
| `NIM_RPM_LIMIT` | 40 | 每分钟请求限制 |
| `NIM_MAX_CONSECUTIVE_FAILURES` | 3 | 连续失败次数阈值 |
| `NIM_REQUEST_TIMEOUT` | 120 | 请求超时(秒) |
| `NIM_MAX_RETRIES` | 2 | 最大重试次数 |
| `NIM_HEALTH_CHECK_INTERVAL` | 300 | 健康检查间隔(秒) |
| `NIM_LOG_LEVEL` | INFO | 日志级别 |

## API 接口

### 管理 API

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/admin/keys` | 添加 API Key |
| `DELETE` | `/admin/keys/{key_preview}` | 移除 Key |
| `POST` | `/admin/keys/{key_preview}/disable` | 禁用 Key |
| `POST` | `/admin/keys/{key_preview}/enable` | 启用 Key |
| `GET` | `/admin/status` | 查看账号池状态 |
| `GET` | `/admin/latency` | 测试模型延迟 |
| `GET` | `/admin/models` | 列出可用模型 |
| `GET` | `/health` | 健康检查 |

### 代理 API

所有 `/v1/*` 请求代理到 NIM API：

- `POST /v1/chat/completions` - 对话补全
- `POST /v1/completions` - 文本补全
- `POST /v1/embeddings` - 向量嵌入
- `GET /v1/models` - 模型列表

## 使用示例

### 添加 API Key

```bash
curl -X POST http://localhost:8000/admin/keys \
  -H "Content-Type: application/json" \
  -d '{"key": "nvapi-xxx", "name": "prod-key-1"}'
```

### 查看状态

```bash
curl http://localhost:8000/admin/status
```

返回示例：
```json
{
  "total_keys": 3,
  "active_keys": 2,
  "keys": [
    {
      "name": "prod-key-1",
      "key_preview": "nvapi-xxx...",
      "status": "active",
      "current_rpm": 12,
      "metrics": {
        "total_requests": 1234,
        "success_rate": 99.2,
        "avg_latency_ms": 234.56,
        "consecutive_failures": 0
      }
    }
  ]
}
```

### 测试模型延迟

```bash
# 测试默认模型
curl http://localhost:8000/admin/latency

# 测试指定模型
curl "http://localhost:8000/admin/latency?model=nvidia/llama-3.1-nemotron-70b-instruct"
```

### 调用代理 API

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "meta/llama-3.1-8b-instruct",
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

## 架构

```
┌─────────────────────────────────────────────────┐
│                   FastAPI Server                │
├─────────────────────────────────────────────────┤
│  main.py          入口 & 路由                    │
│  handler.py       请求处理 & 重试                │
│  pool.py          账号池 & 负载均衡              │
│  health.py        后台健康检查                   │
│  storage.py       持久化存储                     │
│  config.py        配置管理                       │
└─────────────────────────────────────────────────┘
```

## Key 状态

| 状态 | 说明 |
|------|------|
| `active` | 正常可用 |
| `rate_limited` | 被限流，等待恢复 |
| `unhealthy` | 连续失败过多，已隔离 |
| `disabled` | 手动禁用 |

## 生产部署

### Docker

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["python", "main.py"]
```

```bash
docker build -t nim-pool .
docker run -d -p 8000:8000 -e NIM_API_KEYS=nvapi-xxx nim-pool
```

### Systemd

```ini
[Unit]
Description=NIM API Pool
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/nim-pool
ExecStart=/usr/bin/python main.py
Restart=always
Environment=NIM_API_KEYS=nvapi-xxx

[Install]
WantedBy=multi-user.target
```

## License

MIT
