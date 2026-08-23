#!/usr/bin/env bash
set -Eeuo pipefail

source_root=${1:?usage: deploy_control.sh SOURCE_ROOT COMMIT_SHA}
commit_sha=${2:?usage: deploy_control.sh SOURCE_ROOT COMMIT_SHA}
install_root=/opt/bonsai-control
releases="$install_root/releases"
release="$releases/$commit_sha"
previous=$(readlink -f "$install_root/current" 2>/dev/null || true)
unit_backup=$(mktemp -d /run/bonsai-control-units.XXXXXX)
switched=0
building=0

[[ $EUID -eq 0 ]] || { echo "deploy_control.sh must run as root" >&2; exit 1; }
[[ $commit_sha =~ ^[0-9a-f]{40}$ ]] || { echo "invalid commit sha" >&2; exit 1; }
source_root=$(readlink -f "$source_root")
[[ -f "$source_root/control_plane/pyproject.toml" ]] || { echo "invalid source tree" >&2; exit 1; }
[[ $(git -C "$source_root" rev-parse HEAD) == "$commit_sha" ]] || { echo "checkout does not match commit" >&2; exit 1; }

rollback() {
  status=$?
  if (( switched )) && [[ -n $previous && -d $previous ]]; then
    ln -sfn "$previous" "$install_root/.current.rollback"
    mv -Tf "$install_root/.current.rollback" "$install_root/current"
    for unit in bonsai-api bonsai-orchestrator bonsai-promoter; do
      [[ -f "$unit_backup/$unit.service" ]] && install -m 0644 "$unit_backup/$unit.service" "/etc/systemd/system/$unit.service"
    done
    systemctl daemon-reload
    systemctl restart bonsai-api bonsai-orchestrator bonsai-promoter || true
  fi
  if (( building )) && [[ $release == "$releases/"* ]]; then
    rm -rf -- "$release"
  fi
  rm -rf -- "$unit_backup"
  exit "$status"
}
trap rollback ERR INT TERM

for unit in bonsai-api bonsai-orchestrator bonsai-promoter; do
  [[ -f "/etc/systemd/system/$unit.service" ]] && cp -a "/etc/systemd/system/$unit.service" "$unit_backup/$unit.service"
done

install -d -m 0755 "$releases"
if [[ ! -d $release ]]; then
  [[ -x "$install_root/venv/bin/python" ]] || { echo "offline seed venv is missing" >&2; exit 1; }
  building=1
  install -d -m 0755 "$release/venv"
  cp -a "$install_root/venv/." "$release/venv/"
  chmod -R u+w "$release/venv"
  "$release/venv/bin/python" -m pip install --no-deps --no-build-isolation --disable-pip-version-check --force-reinstall "$source_root/control_plane"
  printf '%s\n' "$commit_sha" >"$release/DEPLOYED_COMMIT"
  chmod -R a-w "$release"
  building=0
fi

install -m 0644 "$source_root/control_plane/systemd/bonsai-api.service" /etc/systemd/system/bonsai-api.service
install -m 0644 "$source_root/control_plane/systemd/bonsai-orchestrator.service" /etc/systemd/system/bonsai-orchestrator.service
install -m 0644 "$source_root/control_plane/systemd/bonsai-promoter.service" /etc/systemd/system/bonsai-promoter.service

ln -sfn "$release" "$install_root/.current.new"
mv -Tf "$install_root/.current.new" "$install_root/current"
switched=1
systemctl daemon-reload
systemctl restart bonsai-api
set -a
. /etc/bonsai-control/app.env
set +a
for _ in {1..20}; do
  curl -fsS --max-time 3 "http://$BONSAI_BIND_HOST:$BONSAI_BIND_PORT/health" >/dev/null && break
  sleep 1
done
curl -fsS --max-time 3 "http://$BONSAI_BIND_HOST:$BONSAI_BIND_PORT/health" >/dev/null
systemctl restart bonsai-orchestrator bonsai-promoter
systemctl is-active --quiet bonsai-api bonsai-orchestrator bonsai-promoter
"$release/venv/bin/python" -c 'from importlib.metadata import version; print("bonsai-control=" + version("bonsai-control"))'

switched=0
trap - ERR INT TERM
rm -rf -- "$unit_backup"
install -m 0755 "$source_root/infra/ci/deploy_control.sh" /usr/local/sbin/bonsai-deploy-control
mapfile -t stale_releases < <(find "$releases" -mindepth 1 -maxdepth 1 -type d ! -path "$release" -printf '%T@ %p\n' | sort -nr | tail -n +6 | cut -d' ' -f2-)
for stale in "${stale_releases[@]}"; do
  stale=$(readlink -f "$stale")
  [[ $stale == "$releases/"* ]] || { echo "refusing unsafe cleanup target: $stale" >&2; exit 1; }
  rm -rf -- "$stale"
done
echo "deployed control $commit_sha"
