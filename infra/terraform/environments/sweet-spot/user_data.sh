#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# APIWeaver Host Bootstrapper (Ubuntu 24.04 LTS ARM64 Graviton)
# ==============================================================================

export DEBIAN_FRONTEND=noninteractive

echo "[1/6] Configuring 2 GB swap space for memory spike safety..."
if [ ! -f /swapfile ]; then
    fallocate -l 2G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
    sysctl vm.swappiness=10
    echo 'vm.swappiness=10' > /etc/sysctl.d/99-swappiness.conf
fi

echo "[2/6] Updating packages and installing prerequisites..."
apt-get update -y
apt-get install -y \
    ca-certificates \
    curl \
    gnupg \
    git \
    unzip \
    jq \
    snapd

# Ensure AWS SSM agent is running for browser terminal & SSM Run Command
snap install amazon-ssm-agent --classic || true
systemctl enable snap.amazon-ssm-agent.amazon-ssm-agent.service || true
systemctl start snap.amazon-ssm-agent.amazon-ssm-agent.service || true

echo "[3/6] Installing Docker Engine & Compose v2 (ARM64)..."
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  tee /etc/apt/sources.list.d/docker.list > /dev/null

apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

echo "[4/6] Configuring Docker log rotation to prevent disk bloat..."
mkdir -p /etc/docker
cat <<EOF > /etc/docker/daemon.json
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
EOF
systemctl restart docker
systemctl enable docker

echo "[5/6] Preparing deployment directories..."
mkdir -p /opt/apiweaver/nginx
mkdir -p /opt/apiweaver/certbot/conf
mkdir -p /opt/apiweaver/certbot/www

# Give ubuntu user docker group access
usermod -aG docker ubuntu || true

echo "[6/6] APIWeaver host bootstrap completed successfully at $(date -u)"
