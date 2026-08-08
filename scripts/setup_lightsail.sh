#!/usr/bin/env bash
# One-shot setup for AgriRadius Pro on a Lightsail Ubuntu 24.04 box.
# Run as root:  curl -fsSL https://raw.githubusercontent.com/saravana-gif/agriradius-pro/main/scripts/setup_lightsail.sh | sudo bash
# Idempotent - safe to re-run. Fixed-cost stack: no serverless, no
# per-request billing. Streamlit behind Caddy (auto-TLS), systemd
# keeps it alive, cron pulls new commits from GitHub every 5 min.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

echo "== [1/7] swap =="
if ! swapon --show | grep -q /swapfile; then
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "== [2/7] packages =="
apt-get update -y
apt-get install -y python3-venv python3-pip git curl

echo "== [3/7] caddy =="
if ! command -v caddy >/dev/null 2>&1; then
    apt-get install -y debian-keyring debian-archive-keyring apt-transport-https
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
        | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
        > /etc/apt/sources.list.d/caddy-stable.list
    apt-get update -y
    apt-get install -y caddy
fi

echo "== [4/7] app user + clone + deps =="
id -u agri >/dev/null 2>&1 || useradd -m -s /bin/bash agri
sudo -u agri bash -ec '
    cd ~
    if [ ! -d agriradius-pro ]; then
        git clone --depth 1 https://github.com/saravana-gif/agriradius-pro.git
    fi
    cd agriradius-pro
    git fetch origin main && git reset --hard origin/main
    [ -d .venv ] || python3 -m venv .venv
    .venv/bin/pip install --upgrade pip wheel
    .venv/bin/pip install -r requirements.txt
    mkdir -p .streamlit
'

echo "== [5/7] systemd service =="
cat > /etc/systemd/system/agriradius.service <<'EOF'
[Unit]
Description=AgriRadius Pro (Streamlit)
After=network-online.target
Wants=network-online.target

[Service]
User=agri
WorkingDirectory=/home/agri/agriradius-pro
ExecStart=/home/agri/agriradius-pro/.venv/bin/streamlit run app.py --server.port 8501 --server.address 127.0.0.1 --server.headless true --server.enableCORS false
Restart=always
RestartSec=5
MemoryMax=850M

[Install]
WantedBy=multi-user.target
EOF

echo "== [6/7] caddy vhost =="
cat > /etc/caddy/Caddyfile <<'EOF'
groundintel.oneroot.farm {
    encode gzip
    reverse_proxy 127.0.0.1:8501
}
EOF

echo "== [7/7] auto-deploy cron (pull main every 5 min) =="
cat > /etc/cron.d/agriradius-deploy <<'EOF'
*/5 * * * * root cd /home/agri/agriradius-pro && sudo -u agri git fetch -q origin main && [ "$(git rev-parse HEAD)" != "$(git rev-parse origin/main)" ] && sudo -u agri git reset --hard origin/main >/dev/null && sudo -u agri /home/agri/agriradius-pro/.venv/bin/pip install -q -r requirements.txt && systemctl restart agriradius
EOF
chmod 644 /etc/cron.d/agriradius-deploy

systemctl daemon-reload
systemctl enable agriradius >/dev/null 2>&1 || true
systemctl restart agriradius
systemctl enable caddy >/dev/null 2>&1 || true
systemctl restart caddy

echo ""
echo "================ SETUP DONE ================"
echo "Next: put secrets at /home/agri/agriradius-pro/.streamlit/secrets.toml"
echo "then: sudo systemctl restart agriradius"
