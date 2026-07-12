# Deploy to AWS EC2

Docker + Caddy (auto-HTTPS). Mongo stays on Atlas. You need a **domain** — the iOS
app talks HTTPS and Apple's ATS won't accept a raw EC2 IP without a real cert.

## 1. Launch the instance
- **t3.small** (2 GB) — Ubuntu 24.04. (t3.micro's 1 GB can OOM building torch; 2 GB is safe,
  and lets you flip `EMBEDDING_PROVIDER=local` for semantic matching later.)
- Security group inbound: **22** (your IP), **80**, **443** (0.0.0.0/0).
- Allocate an **Elastic IP** and associate it (so the IP survives reboots).

## 2. DNS
Point an **A record** for `api.yourdomain.com` at the Elastic IP.

## 3. On the box
```bash
ssh ubuntu@<elastic-ip>
# Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker ubuntu && newgrp docker

git clone <this-repo-url> twotable && cd twotable
cp .env.example .env && nano .env      # set DOMAIN, PUBLIC_BASE_URL, MONGODB_URI, JWT_SECRET_KEY

docker compose up -d --build           # Caddy fetches the TLS cert on first boot (~30s)
curl https://api.yourdomain.com/health # {"status":"ok",...}
```
Atlas: allow the Elastic IP in **Network Access** (or 0.0.0.0/0 for now).

## 4. Point the app at it
`Config/Release.xcconfig` (and Debug if you test against it):
```
API_BASE_URL = https:/$()/api.yourdomain.com/api/v1
```
Rebuild the app.

## Ops
```bash
docker compose logs -f app     # logs
git pull && docker compose up -d --build   # deploy an update
```

skipped: CI/CD, ALB, autoscaling, container registry. Add when one box isn't enough.
skipped: keep-warm cron + client cold-start retry are now dead weight (EC2 doesn't sleep) —
leave them, harmless, or delete `.github/workflows/keep-warm.yml`.
