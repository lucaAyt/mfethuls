# Cloud Deployment — DigitalOcean + Tailscale

Step-by-step guide to running mfethuls on a DigitalOcean Droplet accessible to the lab team via Tailscale.

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

Open the Streamlit dashboard in your browser:

```
http://100.x.x.x:8501
```

---

## Step 5 — Configure rclone for OneDrive sync

rclone pulls data from OneDrive to the Droplet on demand. The OAuth token is generated on your local machine (where a browser is available) and copied to the server — this sidesteps any institutional restrictions on headless OAuth.

### One-time setup (run on your Windows machine)

Install rclone locally: download from [rclone.org/downloads](https://rclone.org/downloads/) and add to PATH.

Configure the OneDrive remote:

```shell
rclone config
```

Follow the prompts:
- Name: `onedrive`
- Storage type: `Microsoft OneDrive`
- Sign in with your institutional (or personal) Microsoft account in the browser that opens
- Accept defaults for everything else

Copy the config to the Droplet:

```shell
# Windows (Git Bash / WSL)
scp ~/.config/rclone/rclone.conf root@100.x.x.x:/root/.config/rclone/rclone.conf

# macOS / Linux
scp ~/.config/rclone/rclone.conf root@100.x.x.x:/root/.config/rclone/rclone.conf
```

Add the rclone paths to `.env` on the Droplet:

```
RCLONE_REMOTE=onedrive
RCLONE_SOURCE_PATH=Documents/raw
RCLONE_REGISTRY_PATH=Documents/experiments_template.csv
```

Verify it works from the Droplet:

```shell
rclone ls onedrive:Documents
```

### Token refresh (~every 90 days)

Microsoft OAuth tokens expire. When sync starts failing, re-run `rclone config` locally and re-copy the conf file to the Droplet.

### Sync on demand

**Via Streamlit:** open the Ingest sidebar → click **"Sync from OneDrive"**. An info message confirms the sync started; wait ~30 s before triggering ingest.

**Via curl:**

```shell
curl -s -X POST http://100.x.x.x:8000/sync \
  -H "Authorization: Bearer <your-api-key>"
# {"status": "sync_started"}
```

Then trigger ingest:

```shell
curl -s -X POST http://100.x.x.x:8000/ingest \
  -H "Authorization: Bearer <your-api-key>"
```

### Fallback: direct file transfer (SFTP / rsync)

When rclone is unavailable or the token has lapsed, push data directly over SSH.

**Non-technical users (Windows):** use [WinSCP](https://winscp.net) — free GUI SFTP client. Connect with the Tailscale IP and your SSH key, then drag and drop files into `/mnt/mfethuls-data/`.

**Technical users:**

```shell
rsync -avz --progress /local/raw-data/ root@100.x.x.x:/mnt/mfethuls-data/
rsync -avz --progress experiments_template.csv root@100.x.x.x:/mnt/mfethuls-data/
```

---

## Step 6 — Share access with the team

For each team member:

1. They install Tailscale and join the lab tailnet (send them the tailnet name; they log in at tailscale.com with the lab account credentials or via an invite link)
2. Give them the Tailscale IP of the server (`100.x.x.x`)
3. They open `http://100.x.x.x:8501` in their browser — the Streamlit dashboard requires no local install

| Service | URL |
|---------|-----|
| Streamlit dashboard | `http://100.x.x.x:8501` |
| REST API | `http://100.x.x.x:8000` |

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

## Known limitations

| Item | Status | Plan |
|------|--------|------|
| Data sync from OneDrive | rclone on-demand (Streamlit button or `POST /sync`) | Done — Phase 1b |
| Registry sync | rclone alongside raw data | Done — Phase 1b |
| TLS for team access | Plain HTTP over Tailscale | Acceptable: Tailscale encrypts all traffic end-to-end (WireGuard). Add `tailscale serve` for HTTPS if needed. |
| Automated backups | None | Add DigitalOcean volume snapshot policy (1-click in console) |

Tailscale encrypts all traffic between devices using WireGuard — plain HTTP over the Tailscale network is safe. You do not need a TLS certificate for private lab access.
