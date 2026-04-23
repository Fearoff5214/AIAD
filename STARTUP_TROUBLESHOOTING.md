# Startup Troubleshooting Guide

## Goal

Use this guide when startup fails so you can recover quickly without debugging every time.

## Standard startup command

```powershell
Set-Location -Path "d:\AIAD\Fearoff_AIAD"
& C:/Python314/python.exe .\start_frappe_server.py
```

## Fast startup for retry/debug

```powershell
Set-Location -Path "d:\AIAD\Fearoff_AIAD"
& C:/Python314/python.exe .\start_frappe_server.py --no-build --skip-migrate --skip-ollama-pull --skip-ollama-service
```

## Error: NameError set_site_hostname is not defined

Why it happened:

- The startup file had a broken/partial function block where `set_site_hostname` was accidentally removed.

How to fix:

- Use the repaired `start_frappe_server.py` in this repo.
- Re-run startup with the fast startup command first.

Prevention:

- Avoid partial manual edits inside function blocks.
- After editing startup script, run once with `--no-build --skip-migrate --skip-ollama-pull --skip-ollama-service`.

## Error: 502 Bad Gateway right after backend recreate

Why it happens:

- Frontend becomes available before backend workers are fully ready.

How to handle:

- Wait 10-30 seconds and refresh.
- Check status:

```powershell
Set-Location -Path "d:\AIAD\Fearoff_AIAD"
docker compose ps
```

## Error: localhost does not exist

Why it happens:

- Host-based routing expects site aliases and they were not present.

How to handle:

- Re-run startup script (it creates localhost and 127.0.0.1 aliases).

## Error: Ollama service or model pull problems

Why it happens:

- Port conflict, image pull delay, or service startup lag.

How to handle:

```powershell
Set-Location -Path "d:\AIAD\Fearoff_AIAD"
docker compose up -d ollama
```

If model missing:

```powershell
Set-Location -Path "d:\AIAD\Fearoff_AIAD"
docker compose exec -T ollama ollama pull mistral:7b-instruct
```

## Error: backend needs refresh after code changes

Use:

```powershell
Set-Location -Path "d:\AIAD\Fearoff_AIAD"
docker compose up -d --build backend
```

## Verification checks

```powershell
Set-Location -Path "d:\AIAD\Fearoff_AIAD"
(Invoke-WebRequest -Uri "http://localhost:8085/" -UseBasicParsing -TimeoutSec 30).StatusCode
(Invoke-WebRequest -Uri "http://localhost:8085/user-register" -UseBasicParsing -TimeoutSec 30).StatusCode
(Invoke-WebRequest -Uri "http://localhost:8085/user-portal" -UseBasicParsing -TimeoutSec 30).StatusCode
(Invoke-WebRequest -Uri "http://localhost:8085/admin-user-management" -UseBasicParsing -TimeoutSec 30).StatusCode
```

Expected result:

- `200` for all endpoints.

## When to rebuild everything

If startup still fails after retries:

```powershell
Set-Location -Path "d:\AIAD\Fearoff_AIAD"
docker compose up -d --build
```

Then retry normal startup command.
