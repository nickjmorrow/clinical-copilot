#!/usr/bin/env bash
#
# Deploy to one server over SSH. Safe to re-run: every step checks before it acts,
# so the first run sets the server up and every later run is a redeploy.
#
#   scripts/deploy.sh root@203.0.113.5                        # https://203-0-113-5.sslip.io
#   scripts/deploy.sh root@203.0.113.5 copilot.example.com     # your domain, DNS already pointed
#
# On a fresh Ubuntu 24.04 server, the first run:
#   1. installs Docker and Caddy — from Ubuntu's own packages, no curl-to-shell —
#      adds swap, and opens only SSH, HTTP and HTTPS in the firewall;
#   2. writes .env.prod there: a generated database password, a free local port,
#      and the ANTHROPIC_API_KEY from your local .env (sent over SSH, never echoed);
#   3. copies the code and the Synthea export (rsync, so later runs send only
#      what changed), builds, starts, and seeds an empty database;
#   4. puts Caddy in front, which gets and renews the HTTPS certificate itself.
#
# With no domain, the site is served at <ip-with-dashes>.sslip.io: a DNS name that
# resolves to the IP inside it, so HTTPS works before you own a domain. Pass a
# domain once its A record points at the server to switch.
#
# SEVERAL PROJECTS CAN SHARE ONE SERVER. Everything this script creates there is
# named after APP (default: this repository's folder name), so a second project
# deployed with its own copy of this script gets its own directory, its own
# Compose project — and with it its own containers, network and database volume —
# its own local port, and its own site file in the one Caddy they share. Neither
# can overwrite the other. Without domains they cannot both have the bare
# sslip.io name, so give the second one a name of its own:
#
#   APP=other-app scripts/deploy.sh root@203.0.113.5 other.203-0-113-5.sslip.io
set -euo pipefail

target="${1:?usage: [APP=name] scripts/deploy.sh user@host [domain]}"
host="${target#*@}"
domain="${2:-${host//./-}.sslip.io}"

cd "$(dirname "$0")/.."

app="${APP:-$(basename "$PWD")}"
if [[ ! "$app" =~ ^[a-z0-9][a-z0-9-]*$ ]]; then
  echo "APP must be lowercase letters, digits and dashes, not '$app'." >&2
  exit 1
fi
remote_dir="/opt/$app"
# -p overrides the `name:` inside the compose file, which two projects copied
# from the same template may well share — and a shared Compose project name
# would make the second deploy replace the first one's containers.
compose="docker compose -p $app -f docker-compose.prod.yml --env-file .env.prod"
ssh_opts=(-o StrictHostKeyChecking=accept-new -o ConnectTimeout=15)

say() { printf '\n\033[1m── %s\033[0m\n' "$*"; }
remote() { ssh "${ssh_opts[@]}" "$target" "$@"; }

say "Server: $target  ·  App: $app  ·  Site: https://$domain"

say "Provisioning"
remote 'bash -s' <<'PROVISION'
set -euo pipefail
if ! command -v docker >/dev/null; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -q
  apt-get install -yq docker.io docker-compose-v2 docker-buildx rsync ufw
  systemctl enable --now docker
  # The image builds and the first seed are the memory peaks. Without swap, a
  # small machine OOM-kills a build instead of letting it run slowly.
  if ! swapon --show | grep -q .; then
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
  fi
  ufw allow OpenSSH
  ufw allow 80/tcp
  ufw allow 443/tcp
  ufw --force enable
else
  echo "already provisioned"
fi

# Caddy from its own repository, not Ubuntu's. The Ubuntu package is an old
# release rebuilt with a much newer Go, and it panics and exits on every live
# reload — every site on the server down until someone starts it again. This
# also upgrades a server that was provisioned before this block existed.
# --force-confold keeps the Caddyfile below rather than the package's default.
if [[ ! -f /etc/apt/sources.list.d/caddy-stable.list ]]; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get install -yq debian-keyring debian-archive-keyring apt-transport-https curl gpg
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key |
    gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt \
    > /etc/apt/sources.list.d/caddy-stable.list
  chmod o+r /usr/share/keyrings/caddy-stable-archive-keyring.gpg \
    /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -q
  apt-get install -yq -o Dpkg::Options::=--force-confold caddy
fi

# One Caddy for every project on the server: the main Caddyfile only imports a
# file per site, and each project writes its own. Replaced once — Ubuntu ships a
# default that serves a placeholder page on :80 — and the original kept as .bak.
mkdir -p /etc/caddy/sites
if ! grep -qxF 'import /etc/caddy/sites/*.caddy' /etc/caddy/Caddyfile 2>/dev/null; then
  if [[ -f /etc/caddy/Caddyfile ]]; then cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.bak; fi
  echo 'import /etc/caddy/sites/*.caddy' > /etc/caddy/Caddyfile
fi
PROVISION

say "Configuration"
if remote "test -f $remote_dir/.env.prod"; then
  echo ".env.prod is already on the server — left exactly as it is"
else
  key="$(grep -E '^ANTHROPIC_API_KEY=' .env | cut -d= -f2- || true)"
  if [[ -z "$key" || "$key" == "sk-ant-..." ]]; then
    echo "No ANTHROPIC_API_KEY in .env to send; add one there first." >&2
    exit 1
  fi

  # The first local port no other project on this server has claimed or is
  # listening on. Recorded in this project's .env.prod and kept from then on.
  free_port="$(remote 'bash -s' <<'PORT'
taken="$(cat /opt/*/.env.prod 2>/dev/null | sed -n 's/^PUBLIC_PORT=//p')"
for port in $(seq 8080 8179); do
  if ! grep -qx "$port" <<<"$taken" && ! ss -Hltn "sport = :$port" | grep -q .; then
    echo "$port"
    exit 0
  fi
done
exit 1
PORT
)"

  # umask 077: the file holds the API key and the database password, so only
  # root on the server can read it.
  remote "mkdir -p $remote_dir && umask 077 && cat > $remote_dir/.env.prod" <<ENV
POSTGRES_USER=app
POSTGRES_PASSWORD=$(openssl rand -hex 24)
POSTGRES_DB=app
ANTHROPIC_API_KEY=$key
PUBLIC_ORIGIN=https://$domain
# Caddy, on this machine, is the only thing that reaches nginx.
PUBLIC_BIND_ADDRESS=127.0.0.1
PUBLIC_PORT=$free_port
LOG_LEVEL=info
ENV
  echo "wrote .env.prod (local port $free_port; database password generated; API key from your .env)"
fi
port="$(remote "sed -n 's/^PUBLIC_PORT=//p' $remote_dir/.env.prod")"

say "Copying the code and the dataset"
# .env.prod is excluded so --delete can never remove the server's copy. Only
# options old enough for macOS's openrsync (rsync 2.6.9-compatible), which has
# no --info or --human-readable.
rsync -az --delete --stats -e "ssh ${ssh_opts[*]}" \
  --exclude .git --exclude .env --exclude .env.prod --exclude .DS_Store \
  --exclude node_modules --exclude .venv --exclude dist \
  --exclude __pycache__ --exclude .pytest_cache --exclude .ruff_cache \
  ./ "$target:$remote_dir/"

say "Building and starting (the first build takes a few minutes)"
remote "cd $remote_dir && $compose up --build -d --remove-orphans"

say "Seeding"
patients="$(remote "cd $remote_dir && $compose exec -T db psql -U app -d app -tAc 'select count(*) from patients'")"
patients="${patients//[[:space:]]/}"
if [[ "$patients" == "0" ]]; then
  remote "cd $remote_dir && $compose run --rm worker python -m app.seed" | tail -1
else
  echo "already seeded ($patients patients)"
fi

say "HTTPS"
# This project's site only — /etc/caddy/sites/$app.caddy — so deploying one
# project never touches another's. flush_interval -1 passes Server-Sent Events
# through as they are written. HSTS lives here because Caddy is the only thing
# that knows the site is HTTPS.
#
# A live reload, which drops no connections for this site or any other. If it
# fails — or Caddy is not running a moment later, which is how the Ubuntu
# package's crash-on-reload looked, since it reported success first — fall
# back to a restart rather than leave every site on the server down.
remote "cat > /etc/caddy/sites/$app.caddy && caddy validate --config /etc/caddy/Caddyfile >/dev/null && { systemctl reload caddy || systemctl restart caddy; } && sleep 2 && { systemctl is-active --quiet caddy || systemctl restart caddy; }" <<SITE
$domain {
	reverse_proxy 127.0.0.1:$port {
		flush_interval -1
	}
	header Strict-Transport-Security "max-age=31536000"
}
SITE

say "Checking"
for _ in $(seq 1 36); do
  if curl -fsS --max-time 5 "https://$domain/api/health" >/dev/null 2>&1; then
    echo "Live: https://$domain"
    exit 0
  fi
  sleep 5
done
echo "Not answering on https://$domain after 3 minutes." >&2
echo "Caddy's log: ssh $target journalctl -u caddy -n 50" >&2
exit 1
