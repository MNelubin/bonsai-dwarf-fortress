#!/usr/bin/env bash
set -euo pipefail

ctid=124

if ! pct config "$ctid" | grep -q '^dev0: /dev/net/tun'; then
    pct set "$ctid" --dev0 /dev/net/tun
fi

if ! pct status "$ctid" | grep -q 'status: running'; then
    pct start "$ctid"
fi

for _ in $(seq 1 30); do
    if pct exec "$ctid" -- true >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

pct exec "$ctid" -- bash -s <<'GUEST'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get -y full-upgrade
apt-get install -y --no-install-recommends \
    acl \
    bash-completion \
    build-essential \
    ca-certificates \
    curl \
    file \
    gh \
    git \
    htop \
    jq \
    less \
    locales \
    lsof \
    nano \
    openssh-server \
    postgresql-client \
    procps \
    python3 \
    python3-dev \
    python3-pip \
    python3-venv \
    ripgrep \
    rsync \
    shellcheck \
    sqlite3 \
    sudo \
    tar \
    tmux \
    tree \
    unzip \
    wget \
    xz-utils \
    zip \
    zstd

sed -i 's/^# *en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen
locale-gen en_US.UTF-8
update-locale LANG=en_US.UTF-8

install -d -m 0755 /usr/share/keyrings
curl --fail --silent --show-error --location --retry 3 \
    https://pkgs.tailscale.com/stable/debian/trixie.noarmor.gpg \
    --output /usr/share/keyrings/tailscale-archive-keyring.gpg
curl --fail --silent --show-error --location --retry 3 \
    https://pkgs.tailscale.com/stable/debian/trixie.tailscale-keyring.list \
    --output /etc/apt/sources.list.d/tailscale.list
apt-get update
apt-get install -y --no-install-recommends tailscale

systemctl enable --now ssh tailscaled

if ! id bonsai >/dev/null 2>&1; then
    useradd --system --create-home --home-dir /srv/bonsai-control --shell /usr/sbin/nologin bonsai
fi
install -d -o bonsai -g bonsai -m 0750 \
    /srv/bonsai-control \
    /srv/bonsai-control/artifacts \
    /srv/bonsai-control/backups \
    /srv/bonsai-control/logs \
    /srv/bonsai-control/repo \
    /srv/bonsai-control/state
install -d -o root -g bonsai -m 0750 /etc/bonsai-control

apt-get clean

echo '=== guest base ==='
. /etc/os-release
echo "$PRETTY_NAME"
python3 --version
git --version
gh --version | head -1
psql --version
tailscale version | head -2
systemctl is-active ssh tailscaled
id bonsai
ip -br -4 addr
ip route
GUEST

echo '=== final CT config ==='
pct config "$ctid"
