#!/usr/bin/env bash
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get -y full-upgrade
apt-get install -y --no-install-recommends \
    acl \
    bash-completion \
    build-essential \
    bzip2 \
    ca-certificates \
    cmake \
    curl \
    file \
    git \
    htop \
    jq \
    less \
    lib32gcc-s1 \
    lib32stdc++6 \
    lsof \
    nano \
    ninja-build \
    openssh-server \
    pkg-config \
    procps \
    python3 \
    python3-dev \
    python3-pip \
    python3-venv \
    ripgrep \
    rsync \
    screen \
    shellcheck \
    sqlite3 \
    strace \
    sudo \
    tar \
    tmux \
    tree \
    unzip \
    wget \
    xz-utils \
    zip \
    zstd

systemctl enable --now ssh

if ! id steam >/dev/null 2>&1; then
    useradd --create-home --home-dir /srv/steam --shell /bin/bash steam
fi

install -d -o steam -g steam -m 0750 /srv/steam
install -d -o steam -g steam -m 0750 /opt/steamcmd
install -d -o steam -g steam -m 0750 \
    /srv/df-bonsai \
    /srv/df-bonsai/steam-library \
    /srv/df-bonsai/staging \
    /srv/df-bonsai/releases \
    /srv/df-bonsai/state \
    /srv/df-bonsai/backups \
    /srv/df-bonsai/logs

steamcmd_archive='/tmp/steamcmd_linux.tar.gz'
curl --fail --location --retry 3 \
    'https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz' \
    --output "$steamcmd_archive"
sha256sum "$steamcmd_archive" > /opt/steamcmd/steamcmd_linux.tar.gz.sha256
tar -xzf "$steamcmd_archive" -C /opt/steamcmd
chown -R steam:steam /opt/steamcmd /srv/steam /srv/df-bonsai

runuser -u steam -- env HOME=/srv/steam /opt/steamcmd/steamcmd.sh +quit

ln -sfn /opt/steamcmd/steamcmd.sh /usr/local/bin/steamcmd

apt-get clean

printf 'Debian: '
. /etc/os-release
printf '%s\n' "$PRETTY_NAME"
printf 'SteamCMD archive: '
cat /opt/steamcmd/steamcmd_linux.tar.gz.sha256
printf 'Steam user: '
id steam
printf 'Filesystem: '
df -h /srv/df-bonsai | tail -n 1
