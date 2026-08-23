#!/usr/bin/env bash
set -Eeuo pipefail

source_root=${1:?usage: deploy_lab.sh SOURCE_ROOT COMMIT_SHA}
commit_sha=${2:?usage: deploy_lab.sh SOURCE_ROOT COMMIT_SHA}
install_root=/opt/bonsai-lab-agent
releases="$install_root/releases"
release="$releases/$commit_sha"
previous=$(readlink -f "$install_root/current" 2>/dev/null || true)
unit_backup=$(mktemp -d /run/bonsai-lab-units.XXXXXX)
switched=0
building=0

[[ $EUID -eq 0 ]] || { echo "deploy_lab.sh must run as root" >&2; exit 1; }
[[ $commit_sha =~ ^[0-9a-f]{40}$ ]] || { echo "invalid commit sha" >&2; exit 1; }
source_root=$(readlink -f "$source_root")
[[ -f "$source_root/lab_agent/pyproject.toml" ]] || { echo "invalid source tree" >&2; exit 1; }
[[ $(git -C "$source_root" rev-parse HEAD) == "$commit_sha" ]] || { echo "checkout does not match commit" >&2; exit 1; }

rollback() {
  status=$?
  if (( switched )) && [[ -n $previous && -d $previous ]]; then
    ln -sfn "$previous" "$install_root/.current.rollback"
    mv -Tf "$install_root/.current.rollback" "$install_root/current"
    for unit in bonsai-df-runtime bonsai-k2-proxy bonsai-evaluator bonsai-lab-agent; do
      [[ -f "$unit_backup/$unit.service" ]] && install -m 0644 "$unit_backup/$unit.service" "/etc/systemd/system/$unit.service"
    done
    systemctl daemon-reload
    systemctl restart bonsai-k2-proxy bonsai-evaluator bonsai-lab-agent || true
  fi
  if (( building )) && [[ $release == "$releases/"* ]]; then
    rm -rf -- "$release"
  fi
  rm -rf -- "$unit_backup"
  exit "$status"
}
trap rollback ERR INT TERM

for unit in bonsai-df-runtime bonsai-k2-proxy bonsai-evaluator bonsai-lab-agent; do
  [[ -f "/etc/systemd/system/$unit.service" ]] && cp -a "/etc/systemd/system/$unit.service" "$unit_backup/$unit.service"
done

install -d -m 0755 "$releases"
if [[ ! -d $release ]]; then
  [[ -x "$install_root/venv/bin/python" ]] || { echo "offline seed venv is missing" >&2; exit 1; }
  building=1
  install -d -m 0755 "$release/venv" "$release/source"
  cp -a "$install_root/venv/." "$release/venv/"
  cp -a "$source_root/lab_agent/." "$release/source/"
  chmod -R u+w "$release/venv"
  "$release/venv/bin/python" -m pip install --no-deps --no-build-isolation --disable-pip-version-check --force-reinstall "$release/source"
  printf '%s\n' "$commit_sha" >"$release/DEPLOYED_COMMIT"
  chmod -R a-w "$release"
  building=0
fi

install -m 0644 "$source_root/lab_agent/systemd/bonsai-lab-agent.service" /etc/systemd/system/bonsai-lab-agent.service
install -m 0644 "$source_root/lab_agent/systemd/bonsai-evaluator.service" /etc/systemd/system/bonsai-evaluator.service
install -m 0644 "$source_root/lab_agent/systemd/bonsai-df-runtime.service" /etc/systemd/system/bonsai-df-runtime.service
install -m 0644 "$source_root/lab_agent/deploy/bonsai-k2-proxy.service" /etc/systemd/system/bonsai-k2-proxy.service
install -d -m 0755 /srv/df-bonsai/current/hack/scripts
find "$source_root/lab_agent/bonsai_lab_agent/dfhack" -maxdepth 1 -type f -name '*.lua' -exec install -m 0644 {} /srv/df-bonsai/current/hack/scripts/ \;

ln -sfn "$release" "$install_root/.current.new"
mv -Tf "$install_root/.current.new" "$install_root/current"
switched=1
systemctl daemon-reload
systemctl restart bonsai-k2-proxy bonsai-evaluator bonsai-lab-agent
systemctl is-active --quiet bonsai-df-runtime bonsai-k2-proxy bonsai-evaluator bonsai-lab-agent
"$release/venv/bin/python" -c 'from importlib.metadata import version; print("bonsai-lab-agent=" + version("bonsai-lab-agent"))'
for command in bonsai-lab-agent bonsai-evaluator bonsai-k2-proxy; do
  test -x "$release/venv/bin/$command"
done

switched=0
trap - ERR INT TERM
rm -rf -- "$unit_backup"
install -m 0755 "$source_root/infra/ci/deploy_lab.sh" /usr/local/sbin/bonsai-deploy-lab
mapfile -t stale_releases < <(find "$releases" -mindepth 1 -maxdepth 1 -type d ! -path "$release" -printf '%T@ %p\n' | sort -nr | tail -n +6 | cut -d' ' -f2-)
for stale in "${stale_releases[@]}"; do
  stale=$(readlink -f "$stale")
  [[ $stale == "$releases/"* ]] || { echo "refusing unsafe cleanup target: $stale" >&2; exit 1; }
  rm -rf -- "$stale"
done
echo "deployed lab $commit_sha"
