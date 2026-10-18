# Deployment guide

**Status:** AgentVault has been verified locally (native) and in Docker Compose. It has **not**
been deployed to a public host, because no hosting credentials were available while building it.
The steps below are prepared but unexecuted. Verify every URL yourself before you call it live.

## What was verified (2026-10-18)

| Check | Result |
|---|---|
| Native backend + Vite dev server, Playwright E2E (3 tests) | passed |
| `docker compose build` (backend `python:3.13-slim`, web `nginx:1.27-alpine`) | built |
| `docker compose up`: `/api/v1/ready` through nginx, launch → approval → completion, audit verify | passed |
| All 8 UI routes plus the flow graph under the production CSP, console errors | none |

## Option A: one machine with Docker (simplest, durable)

Any VM or home server with Docker:

```bash
git clone <your repo> agentvault && cd agentvault
cp .env.example .env              # set AGENTVAULT_API_TOKEN to a long random value
AGENTVAULT_WEB_PORT=80 docker compose up -d --build
```

Put TLS in front of it (Caddy, Traefik or a cloud load balancer). The SQLite database lives in the
`agentvault-data` volume. Back it up with
`docker run --rm -v agentvault_agentvault-data:/d -v $PWD:/b alpine cp /d/agentvault.db /b/`.

## Option B: managed hosting (split frontend and API)

Hosting limits change often. These are the limits as researched in October 2026; confirm them on
each provider's pricing page.

| Need | Option | Relevant limits |
|---|---|---|
| API container | **Render** free web service | 512 MB RAM, 0.1 CPU, spins down after 15 min idle (~1 min cold start), **no persistent disk on free plans**: SQLite resets on restart/redeploy (re-seeded automatically). Persistent disks are a paid add-on. |
| API container (durable) | **Fly.io** | Pay-as-you-go for new accounts (the legacy free allowance applies only to grandfathered orgs). Volumes ≈ $0.15/GB-month. Good fit: one machine + one volume at `/data`. |
| Static frontend | **Cloudflare Pages** / **Netlify** | Both free for a static SPA. Cloudflare's free bandwidth is generally described as unmetered. Netlify moved to a credit model; check current limits. `frontend/public/_redirects` handles SPA routing on both. |

### Render (API)
1. Push the repository to GitHub.
2. In Render, choose **New → Blueprint** and select the repo (uses `render.yaml`).
3. Set `AGENTVAULT_API_TOKEN` (long random value) and `AGENTVAULT_CORS_ORIGINS` (your frontend origin, e.g. `https://agentvault.pages.dev`).
4. Wait for `/api/v1/ready` to return 200.

### Cloudflare Pages or Netlify (frontend)
* Root directory: `frontend`, build command: `npm ci && npm run build`, output: `dist`, Node 22.
* Environment variable: `VITE_API_BASE_URL=https://<your-api-host>` (read at build time).
* After it deploys, open the UI, click **API token** in the sidebar and paste the token.

### Fly.io (API, durable)
```bash
fly launch --no-deploy --dockerfile Dockerfile --name <app-name>
fly volumes create agentvault_data --size 1
# in fly.toml: [mounts] source="agentvault_data" destination="/data"; internal_port=8000
fly secrets set AGENTVAULT_API_TOKEN=<random> AGENTVAULT_CORS_ORIGINS=https://<frontend-origin>
fly deploy
```
Keep exactly one machine (`fly scale count 1`): SQLite and the approval-locking design assume a
single process per database.

## Verifying a deployment

```powershell
.\scripts\demo.ps1 -Api https://<api-host> -Token <token>
cd frontend; node e2e/smoke-deployed.mjs https://<frontend-host>
```
Only call a URL "live" after both commands succeed against it.

## Public exposure checklist
* Set `AGENTVAULT_API_TOKEN`. Without it, anyone who can reach the API can read audit data and approve actions.
* Keep `AGENTVAULT_ENVIRONMENT=production` (it disables `/api/docs`).
* Restrict `AGENTVAULT_CORS_ORIGINS` to the frontend origin.
* The token is a shared secret, not user accounts. Do not present a public instance as a secure
  multi-user approval system.
* Leave the LLM adapter disabled unless you accept that task text and tool outputs are sent to the provider.
