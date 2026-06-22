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

### Install Docker

```shell
apt update && apt upgrade -y
apt install -y ca-certificates curl gnupg

install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
  > /etc/apt/sources.list.d/docker.list

apt update
apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
```

Verify:
```shell
docker run hello-world
```

### Mount the Block Volume

DigitalOcean automatically attaches the volume. Format and mount it:

```shell
# Check the device name (usually /dev/sda or /dev/disk/by-id/scsi-...)
lsblk

# Format (only needed once — skip if re-using an existing volume)
mkfs.ext4 /dev/sda

# Create mount point and mount
mkdir -p /mnt/mfethuls-data
mount /dev/sda /mnt/mfethuls-data

# Persist across reboots
echo '/dev/sda /mnt/mfethuls-data ext4 defaults,nofail 0 2' >> /etc/fstab
```

Create the expected sub-directories:

```shell
mkdir -p /mnt/mfethuls-data/raw
mkdir -p /mnt/mfethuls-data/mfethuls_storage
```

### Install Tailscale

```shell
curl -fsSL https://tailscale.com/install.sh | sh
tailscale up
```

This prints a URL — open it in a browser, log in with the lab Tailscale account, and authorise the machine. The Droplet will appear in the Tailscale dashboard with a stable `100.x.x.x` address. **Note this address** — it is how the team will reach the server.

After joining the tailnet, you can close port 22 to the public internet in the DigitalOcean firewall and SSH via the Tailscale IP instead:

```shell
ssh root@100.x.x.x
```

---

## Step 4 — Deploy the application

### Clone the repo

```shell
cd /opt
git clone git@github.com:lucaAyt/mfethuls.git
cd mfethuls
```

### Create `.env`

```shell
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

Once data is on the server, submit an ingest via the API (uploading your registry CSV):

```shell
curl -s -X POST http://100.x.x.x:8000/ingest \
  -H "Authorization: Bearer <your-api-key>" \
  -F "file=@/path/to/experiments_registry.csv"
```

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
| Registry sync | Upload via API at ingest time | Stays as-is — works well |
| TLS for team access | Plain HTTP over Tailscale | Acceptable: Tailscale encrypts all traffic end-to-end (WireGuard). Add `tailscale serve` for HTTPS if needed. |
| Automated backups | None | Add DigitalOcean volume snapshot policy (1-click in console) |

Tailscale encrypts all traffic between devices using WireGuard — plain HTTP over the Tailscale network is safe. You do not need a TLS certificate for private lab access.
