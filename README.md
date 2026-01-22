# Telegram Session Keepalive Manager

基于 Telethon 的 Telegram 会话保活管理工具，提供 Web 界面用于登录账号、创建保活任务和接收验证码。

> **安全注意**：StringSession 等同于账号密钥，泄露即失控；2FA 也无法阻止。请妥善保管，不要记录到日志、截图或提交到 Git。

## 功能特性

- **Web 管理界面**：通过浏览器管理 Telegram 会话和保活任务
- **三大功能页签**：
  - 登录 TG 账号：在线登录并获取 StringSession
  - 创建保活任务：配置自动保活任务，保持会话活跃
  - 获取验证码：实时接收 Telegram 登录验证码
- **自动保活**：定期执行心跳操作，防止会话过期
- **Bot 通知**：通过 Telegram Bot 发送保活状态通知
- **任务管理**：自动加载、执行和清理保活任务
- **Docker 支持**：一键部署，开箱即用

## 项目结构

```
.
├── web_server.py          # FastAPI Web 服务器
├── session_manager.py     # 保活任务管理器
├── telegram_client.py     # Telethon 客户端封装
├── bot_notifier.py        # Telegram Bot 通知模块
├── models.py              # Pydantic 数据模型
├── config.py              # 配置管理
├── static/                # 前端页面
│   ├── index.html         # 主页
│   ├── verify.html        # 验证码接收页面
│   └── app.js             # 前端交互逻辑
├── data/                  # 保活任务配置文件（JSON）
├── logs/                  # 日志文件
├── Dockerfile             # Docker 镜像配置
├── docker-compose.yml     # Docker Compose 配置
├── .env.example           # 环境变量示例
└── requirements.txt       # Python 依赖

```

## 前置准备

### 1. 获取 Telegram API 凭证

1. 访问 https://my.telegram.org，使用你的 Telegram 账号登录
2. 点击 "API development tools"
3. 创建应用（名称/描述随意，平台选其他即可）
4. 记录 `App api_id` 和 `App api_hash`

### 2. 创建 Telegram Bot

1. 在 Telegram 中搜索 `@BotFather`
2. 发送 `/newbot` 创建新 Bot
3. 按提示设置 Bot 名称和用户名
4. 记录 Bot Token 和用户名

### 3. 同步系统时间

Telegram 对时间同步要求严格，建议启用 NTP：

```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install -y systemd-timesyncd
sudo systemctl enable --now systemd-timesyncd
sudo timedatectl set-ntp true
timedatectl status
```

## 快速开始

### 方式一：Docker Compose（推荐）

使用预构建的 Docker 镜像快速部署：

1. 克隆项目并进入目录：
```bash
git clone https://github.com/jbtt-2025/tg-session-web.git
cd tg-session-web
```

2. 复制环境变量文件：
```bash
cp .env.example .env
```

3. 编辑 `.env` 文件，填入你的凭证：
```bash
TG_API_ID=your_api_id
TG_API_HASH=your_api_hash
TG_NOTIFY_BOT_TOKEN=your_bot_token
TG_NOTIFY_BOT_NAME=your_bot_username
```

4. 禁用开发环境配置（使用预构建镜像）：
```bash
mv docker-compose.override.yml docker-compose.override.yml.disabled
```

5. 启动服务：
```bash
docker-compose up -d
```

6. 访问 Web 界面：http://localhost:8000

**开发模式**：如果你想从源码构建并启用热重载，保留 `docker-compose.override.yml` 文件即可。

### 方式二：Docker 直接部署

使用预构建的 Docker 镜像快速部署：

```bash
docker run -d \
  --name tg-session-web \
  --restart unless-stopped \
  -p 8000:8000 \
  -e TG_API_ID=your_api_id \
  -e TG_API_HASH=your_api_hash \
  -e TG_NOTIFY_BOT_TOKEN=your_bot_token \
  -e TG_NOTIFY_BOT_NAME=your_bot_username \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/logs:/app/logs \
  ghcr.io/jbtt-2025/tg-session-web:latest
```

**Windows PowerShell**：
```powershell
docker run -d `
  --name tg-session-web `
  --restart unless-stopped `
  -p 8000:8000 `
  -e TG_API_ID=your_api_id `
  -e TG_API_HASH=your_api_hash `
  -e TG_NOTIFY_BOT_TOKEN=your_bot_token `
  -e TG_NOTIFY_BOT_NAME=your_bot_username `
  -v ${PWD}/data:/app/data `
  -v ${PWD}/logs:/app/logs `
  ghcr.io/jbtt-2025/tg-session-web:latest
```

访问 Web 界面：http://localhost:8000

### 方式三：本地运行

1. 安装依赖：
```bash
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# 或
.venv\Scripts\activate     # Windows

pip install -r requirements.txt
```

2. 配置环境变量：
```bash
export TG_API_ID=your_api_id
export TG_API_HASH=your_api_hash
export TG_NOTIFY_BOT_TOKEN=your_bot_token
export TG_NOTIFY_BOT_NAME=your_bot_username
```

3. 启动 Web 服务器：
```bash
# 默认端口 8000
uvicorn web_server:app --host 0.0.0.0 --port 8000

# 或使用自定义端口
export PORT=3000
uvicorn web_server:app --host 0.0.0.0 --port $PORT
```

4. 访问 Web 界面：http://localhost:8000（或你配置的端口）

## 使用指南

### 页签 1：登录 TG 账号

1. 输入手机号（国际格式，如 +1234567890）
2. 点击"发送验证码"
3. 输入 Telegram 发送的验证码
4. 如果启用了 2FA，输入密码
5. 获取 StringSession 字符串
6. 可选：直接点击"创建保活任务"按钮

**安全说明**：
- 每个登录流程使用唯一的会话标识符（session_id）
- 多个用户可以同时登录，会话完全隔离
- 会话有效期为 10 分钟，超时自动清理
- 登录成功或失败后会话立即清理

### 页签 2：创建保活任务

1. 输入 StringSession（从页签 1 获取或已有的）
2. 点击"验证"查看账号信息
3. 配置通知接收者 ID：
   - 默认为当前账号 ID
   - 可修改为其他用户 ID
   - 点击 ? 查看获取 ID 的教程
4. 点击"创建任务"
5. 记录返回的验证码接收 URL

**重要**：
- 创建任务前，请先在 Telegram 中 start 你的 Bot，否则无法接收通知
- 同一 Telegram 账号只能有一个保活任务，创建新任务会自动清理旧任务

### 页签 3：获取验证码

1. 输入 StringSession
2. 点击"开始监听"
3. 在其他设备上登录 Telegram
4. 验证码到达时会自动显示在页面上

**并发限制**：
- 系统最多支持 50 个并发 SSE 连接
- 超过限制时会返回 503 错误，请稍后重试
- 每个连接超时时间为 5 分钟

### 通过 UUID 接收验证码

创建保活任务后，可以通过返回的 URL 接收验证码：

```
http://localhost:8000/verifyCode/{uuid}
```

打开此 URL 后，页面会自动监听并显示验证码。


## 环境变量配置

### 必填参数

| 变量名 | 说明 | 示例 |
|--------|------|------|
| `TG_NOTIFY_BOT_TOKEN` | Bot Token | `123456:ABC-DEF...` |
| `TG_NOTIFY_BOT_NAME` | Bot 用户名 | `my_bot` |

### 可选参数

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `TG_API_ID` | Telegram API ID | `32471437` |
| `TG_API_HASH` | Telegram API Hash | `c356cf8137a04c92ebfda0fdbd299604` |
| `TG_INTERVAL_SECONDS` | 保活间隔（秒） | `86400`（1 天） |
| `TG_JITTER_SECONDS` | 随机抖动（秒） | `300`（5 分钟） |
| `TG_HEART_BEAT_MAX_FAIL` | 最大连续失败次数 | `3` |
| `DATA_DIR` | 数据存储目录 | `./data` |
| `LOG_LEVEL` | 日志级别 | `INFO` |
| `LOG_DIR` | 日志目录 | `./logs` |
| `PORT` | Web 服务器端口 | `8000` |
| `HOST` | Web 服务器绑定地址 | `0.0.0.0` |

详见 `.env.example` 文件。

## 数据存储

### 会话文件

保活任务配置存储在 `./data/` 目录下的 JSON 文件中：

```json
{
  "uuid": "550e8400-e29b-41d4-a716-446655440000",
  "tg_id": 123456789,
  "session_string": "1AQAAA...",
  "notify_chat_id": 123456789,
  "consecutive_failures": 0,
  "created_at": "2025-01-14T10:30:00Z",
  "last_heartbeat": "2025-01-14T12:00:00Z"
}
```

## 通知功能

启用 Bot 通知后，系统会在以下情况发送消息：

- ✅ **保活成功**：每次心跳成功时通知
- ⚠️ **保活失败**：心跳失败时通知，包含错误原因
- 🗑️ **任务清理**：连续失败达到上限时通知并清理任务

**前置条件**：用户需要先在 Telegram 中 start 你的 Bot，否则无法接收通知。

## Docker 部署

### Docker Compose 说明

项目包含两个 Docker Compose 配置文件：

1. **docker-compose.yml**：生产环境配置，使用预构建镜像 `ghcr.io/jbtt-2025/tg-session-web:latest`
2. **docker-compose.override.yml**：开发环境配置，从源码构建并启用热重载

Docker Compose 会自动合并这两个文件。要使用生产镜像，需要禁用 override 文件：

```bash
# 禁用开发配置，使用生产镜像
mv docker-compose.override.yml docker-compose.override.yml.disabled
docker-compose up -d

# 恢复开发配置
mv docker-compose.override.yml.disabled docker-compose.override.yml
docker-compose up -d
```

### 使用 Docker Compose

```bash
# 启动服务（生产模式 - 需先禁用 override 文件）
docker-compose up -d

# 启动服务（开发模式 - 保留 override 文件）
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止服务
docker-compose down

# 停止并删除数据
docker-compose down -v
```

### 使用 Docker 命令

```bash
# 运行容器（默认端口 8000）
docker run -d \
  --name tg-session-web \
  --restart unless-stopped \
  -p 8000:8000 \
  -e TG_API_ID=your_api_id \
  -e TG_API_HASH=your_api_hash \
  -e TG_NOTIFY_BOT_TOKEN=your_bot_token \
  -e TG_NOTIFY_BOT_NAME=your_bot_username \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/logs:/app/logs \
  ghcr.io/jbtt-2025/tg-session-web:latest

# 或使用自定义端口
docker run -d \
  --name tg-session-web \
  --restart unless-stopped \
  -p 3000:3000 \
  -e PORT=3000 \
  -e TG_API_ID=your_api_id \
  -e TG_API_HASH=your_api_hash \
  -e TG_NOTIFY_BOT_TOKEN=your_bot_token \
  -e TG_NOTIFY_BOT_NAME=your_bot_username \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/logs:/app/logs \
  ghcr.io/jbtt-2025/tg-session-web:latest
```

### 从源码构建

如果你想从源码构建镜像：

```bash
# 构建镜像
docker build -t tg-session-web .

# 运行容器
docker run -d \
  --name tg-session-web \
  --restart unless-stopped \
  -p 8000:8000 \
  -e TG_API_ID=your_api_id \
  -e TG_API_HASH=your_api_hash \
  -e TG_NOTIFY_BOT_TOKEN=your_bot_token \
  -e TG_NOTIFY_BOT_NAME=your_bot_username \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/logs:/app/logs \
  tg-session-web
```

### Restart 策略说明

所有 Docker 部署方式都使用 `--restart unless-stopped` 策略：
- ✅ 容器异常退出时自动重启
- ✅ Docker 守护进程重启时自动启动容器
- ✅ 手动停止的容器不会自动重启
- ✅ 系统重启后自动恢复服务

### 数据持久化

通过 Docker 卷挂载实现数据持久化：
- `./data:/app/data` - 会话配置文件
- `./logs:/app/logs` - 日志文件

重启容器时数据不会丢失。

## 生产部署建议

1. **使用反向代理**：在 Docker 前面使用 Nginx 或 Traefik 处理 HTTPS
2. **环境变量管理**：使用 `.env` 文件或 Docker secrets 管理敏感信息
3. **资源限制**：在 `docker-compose.yml` 中添加 `resources` 限制
4. **监控和日志**：配置日志驱动和监控工具
5. **备份**：定期备份 `./data/` 目录
6. **防火墙**：限制 Web 界面访问，仅允许可信 IP

### Nginx 反向代理示例

```nginx
server {
    listen 80;
    server_name your-domain.com;
    
    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # SSE 支持
        proxy_buffering off;
        proxy_cache off;
        proxy_set_header Connection '';
        proxy_http_version 1.1;
        chunked_transfer_encoding off;
    }
}
```

## 故障排查

### Web 服务无法启动

- 检查环境变量是否正确设置
- 查看日志：`docker-compose logs web` 或 `./logs/error.log`
- 确保端口 8000 未被占用
- 验证 Telegram API 凭证是否有效

### 无法接收通知

- 确保用户已在 Telegram 中 start 你的 Bot
- 检查 Bot Token 是否正确
- 验证 `notify_chat_id` 是否正确
- 查看日志中的错误信息

### 保活任务不执行

- 检查 `./data/` 目录中是否有任务配置文件
- 查看日志确认任务是否被加载
- 验证 StringSession 是否仍然有效
- 检查系统时间是否同步

### 验证码无法接收

- 确保 StringSession 有效
- 检查网络连接
- 验证 Telegram 是否发送了验证码
- 查看浏览器控制台是否有 SSE 连接错误

## 安全注意事项

⚠️ **重要安全提示**：

1. **StringSession 保护**：
   - StringSession 等同于账号密钥，泄露即失控
   - 不要记录到日志、截图或提交到 Git
   - 不要在不可信的机器上使用

2. **单机运行**：
   - 同一 StringSession 只能在一台机器上运行
   - 不要多机并发使用同一会话

3. **IP 稳定性**：
   - 使用稳定的 VPS IP
   - 避免使用住宅 IP 或频繁变动的 IP

4. **保活频率**：
   - 建议使用天/周级别的保活间隔
   - 不要使用分钟级别的频繁调用

5. **环境变量安全**：
   - 使用 `.env` 文件管理敏感信息
   - 不要将 `.env` 文件提交到版本控制
   - 容器日志、CI 变量、命令历史都可能泄露敏感信息

6. **访问控制**：
   - 限制 Web 界面访问，仅允许可信 IP
   - 使用 HTTPS 加密传输
   - 考虑添加身份验证

## 技术栈

- **后端**：Python 3.11 + FastAPI + Telethon
- **任务调度**：APScheduler
- **前端**：HTML + JavaScript（原生）
- **实时通信**：Server-Sent Events (SSE)
- **数据存储**：JSON 文件
- **容器化**：Docker + Docker Compose