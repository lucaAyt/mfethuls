# Cloud Deployment — DigitalOcean + Tailscale

Step-by-step guide to running mfethuls on a DigitalOcean Droplet accessible to the lab team via Tailscale. This is the Phase 1 deployment: manual data sync, full functionality.

---

## What you need before starting

- DigitalOcean account with access to the `fra1` region
- A lab Tailscale account (tailscale.com — use a shared lab/group email, not personal)
- SSH key added to your DigitalOcean account
- The mfethuls repo cloned and working locally

---

## Step 1 — Create the Tailscale lab account

1. Go to [tailscale.com](https://tailscale.com) and sign up with the lab group email
2. Download and install Tailscale on your laptop — log in with the lab account
3. Keep the tailnet name (shown in the dashboard) — you'll need it later

Every team member who needs access installs Tailscale on their machine and joins the same tailnet. They do not need DigitalOcean access.

---

## Step 2 — Create the Droplet

In the DigitalOcean console:

- **Region:** Frankfurt (`fra1`)
- **Image:** Ubuntu 24.04 LTS x64
- **Size:** Basic Shared CPU — **2 vCPU / 4 GB RAM** (~$24/mo). Upgrade to 8 GB if you have many large datasets.
- **Storage:** Add a **Block Volume** — 100 GB is comfortable for a lab (~$10/mo). Mount path: `/mnt/mfethuls-data`
- **Authentication:** SSH key (add yours in the console)
- **Hostname:** `mfethuls`

Once the Droplet is ready, note the public IP. You will stop using this IP once Tailscale is configured — all access will go through Tailscale instead.

---

## Step 3 — Provision the Droplet

SSH in:

```shell
ssh root@<droplet-public-ip>
```

Clone the repo first so you have the setup script:

```shell
apt-get install -y git
cd /opt && git clone -b feature/cloud_deployment git@github.com:lucaAyt/mfethuls.git && cd mfethuls
```

Then run the bootstrap script (installs Docker, Tailscale, mounts the block volume, creates data directories):

```shell
bash scripts/vm_setup.sh
```

Next, join the tailnet:

```shell
tailscale up
```

This prints a URL — open it in a browser, log in with the lab Tailscale account, and authorise the machine. The Droplet will appear in the Tailscale dashboard with a stable `100.x.x.x` address. **Note this address** — it is how the team will reach the server.

After joining the tailnet you can SSH via the Tailscale IP and close port 22 to the public internet in the DigitalOcean firewall:

```shell
ssh root@100.x.x.x
```

---

## Step 4 — Deploy the application

### Create `.env`

```shell
cd /opt/mfethuls
cp env_example .env
nano .env
```

Set these values (everything else can stay as default):

```
MFETHULS_MODE=local           # not used by containers but keep it
DATA_ROOT=/mnt/mfethuls-data  # the block volume mount point

MFETHULS_API_KEY=<generate with: python3 -c "import secrets; print(secrets.token_urlsafe(32))">

MFETHULS_POSTGRES_ENABLED=true
MFETHULS_POSTGRES_USER=mfethuls
MFETHULS_POSTGRES_PASSWORD=<strong random password>
MFETHULS_POSTGRES_DB=mfethuls
MFETHULS_POSTGRES_HOST=localhost
MFETHULS_POSTGRES_HOST_SERVICE=postgres
MFETHULS_POSTGRES_PORT=5432
```

#### DO Spaces (Parquet output — recommended)

If you have a DigitalOcean Spaces bucket, fill in the S3 block to store parsed Parquet files in the cloud rather than on the Droplet's block volume. This is already supported by the worker and requires no code changes:

```
MFETHULS_S3_BUCKET=mfethulsdev
MFETHULS_S3_REGION=fra1
MFETHULS_S3_ENDPOINT=digitaloceanspaces.com
MFETHULS_S3_ACCESS_KEY=<from DO console → Spaces → Manage Keys>
MFETHULS_S3_SECRET_KEY=<from DO console>
MFETHULS_S3_PREFIX=data
```

Leave these blank to store Parquet files on the block volume instead.

### Start the stack

```shell
docker compose up --build -d
```

Check all services are running:

```shell
docker compose ps
docker compose logs -f api
```

### Smoke test

From the Droplet itself:

```shell
curl http://localhost:8000/health
# {"status": "ok"}

curl -H "Authorization: Bearer <your-api-key>" http://localhost:8000/datasets
# []
```

From your laptop (via Tailscale):

```shell
curl http://100.x.x.x:8000/health
# {"status": "ok"}
```

---

## Step 5 — Push data to the server

For the first deployment, sync raw instrument data manually with `rsync`. Run this from your lab machine whenever you have new data to ingest:

```shell
# From your Windows machine (Git Bash or WSL)
rsync -avz --progress \
  "/mnt/c/Users/BertossL/OneDrive - Université de Fribourg/Documents/" \
  root@100.x.x.x:/mnt/mfethuls-data/raw/
```

Or from macOS/Linux:
```shell
rsync -avz --progress \
  "/Users/you/OneDrive - Lab/Documents/" \
  root@100.x.x.x:/mnt/mfethuls-data/raw/
```

Also sync the registry CSV to the server:

```shell
rsync -avz --progress \
  "/mnt/c/Users/BertossL/OneDrive - Université de Fribourg/Documents/experiments_template.csv" \
  root@100.x.x.x:/mnt/mfethuls_data/
```

Once data and registry are on the server, trigger ingest:

```shell
curl -s -X POST http://100.x.x.x:8000/ingest \
  -H "Authorization: Bearer <your-api-key>"
```

The server reads the registry from `PATH_TO_REGISTRY` — no file upload needed.

---

## Step 6 — Share access with the team

For each team member:

1. They install Tailscale and join the lab tailnet (send them the tailnet name, they log in at tailscale.com with the lab account credentials or via an invite link)
2. Give them the Tailscale IP of the server (`100.x.x.x`) and the `MFETHULS_API_KEY`
3. They can now reach the API, Metabase (`:3000`), and the Quack gateway (`:8080`) from anywhere — no VPN setup required beyond Tailscale

---

## Updating the application

```shell
ssh root@100.x.x.x
cd /opt/mfethuls
git pull
docker compose up --build -d
```

Postgres data and DuckDB (both on the block volume) survive rebuilds.

---

## What's not automated yet (Phase 1 known limitations)

| Item | Status | Plan |
|------|--------|------|
| Data sync from OneDrive | Manual `rsync` | Phase 1b: `rclone` sync on demand |
| Registry sync | Manual `rsync` alongside raw data | Phase 1b: `rclone` sync on demand |
| TLS for team access | Plain HTTP over Tailscale | Acceptable: Tailscale encrypts all traffic end-to-end (WireGuard). Add `tailscale serve` for HTTPS if needed. |
| Automated backups | None | Add DigitalOcean volume snapshot policy (1-click in console) |

Tailscale encrypts all traffic between devices using WireGuard — plain HTTP over the Tailscale network is safe. You do not need a TLS certificate for private lab access.
