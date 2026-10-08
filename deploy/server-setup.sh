#!/usr/bin/env bash
# One-time setup for the Oracle Cloud Always Free Ubuntu server. Run as the ubuntu user:
#   curl -fsSL https://raw.githubusercontent.com/AlexanderGiannak/hive-work/main/deploy/server-setup.sh | bash
# Then: cd ~/hivework, cp .env.example .env, fill in the server-only values,
# and run: docker compose --profile prod up -d --build
set -euo pipefail

REPO="${REPO:-https://github.com/AlexanderGiannak/hive-work.git}"

echo "== Docker"
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER"
fi

echo "== Firewall"
# Oracle's Ubuntu images block everything but SSH in iptables, on top of the
# cloud security list. Open 80 and 443 here too (and in the VCN security list in the console).
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo apt-get install -y iptables-persistent >/dev/null
sudo netfilter-persistent save

echo "== Swap (helps the 12 GB box ride out spikes)"
if ! swapon --show | grep -q swapfile; then
  sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
  sudo mkswap /swapfile && sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
fi

echo "== Repo"
[ -d ~/hivework ] || git clone "$REPO" ~/hivework

echo "Done. Log out and back in so the docker group applies."
