# 빠른 시작

Clone the repository, copy `.env.example`, configure a public HTTPS URL, OAuth PIN, and JWT secret, then start Docker Compose.

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
cp .env.example .env
mkdir -p workspaces/default
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
```

공개 배포에서는 OAuth 를 활성화하고 Docker socket, 호스트 루트, 장기 자격 증명을 마운트하지 마십시오.
