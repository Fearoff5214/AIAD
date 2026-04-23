# Fearoff AIAD Setup and Startup Guide

## What this application provides

- Multi-tenant Frappe/ERPNext portal
- User registration for manufacturing and wholesale customers
- Admin management pages for tenant/user control
- Built-in GST Copilot with local Ollama AI

## Primary admin account

- Username: `parameshlogaa@gmail.com`
- Password: `PE42026`

This is the current primary admin account for the running deployment. Use it for the first admin login and change the password after first access in a production environment.

## Prerequisites

- Docker Desktop or Docker Engine with Compose
- WSL Ubuntu recommended for local development and production-style startup
- Python available for running `start_frappe_server.py`

## Start the server

From the project root:

```powershell
Set-Location -Path "d:\AIAD\Fearoff_AIAD"
& C:/Python314/python.exe .\start_frappe_server.py
```

Useful flags:

- `--no-build` to skip rebuilding the image
- `--skip-migrate` to skip site migration
- `--skip-ollama-pull` to skip pulling the local model
- `--skip-ollama-service` to keep Ollama from starting automatically
- `--follow-logs` to stream Docker logs after startup

## Website links

After startup, the terminal prints the main links:

- Main site: `http://localhost:8085`
- Create account: `http://localhost:8085/user-register`
- User portal: `http://localhost:8085/user-portal`
- Admin page: `http://localhost:8085/admin-user-management`
- GST Copilot: `http://localhost:8085/gst-copilot`

## Account creation flow

1. Open the Create Account page.
2. Enter full name, email, password, company name, industry type, and website slug.
3. Submit the form.
4. Log in with the new account and use the integrated user portal.

## Admin flow

1. Log in with `parameshlogaa@gmail.com` and `PE42026`.
2. Open the Admin Page.
3. Assign admins to tenants, grant access, and use the embedded GST Copilot if needed.

## Notes for production startup

- The startup script brings up core services first and then starts Ollama separately so the app does not block on a large model pull.
- The app uses host-based routing. The startup process maps `localhost` and `127.0.0.1` to the default tenant so browser access works without manual Host headers.
- Keep the primary admin password secret and rotate it after first use.

## Troubleshooting

- If `http://localhost:8085` shows a 404, rerun the startup script so the site aliases are recreated.
- If the GST Copilot is slow the first time, let Ollama finish loading the model.
