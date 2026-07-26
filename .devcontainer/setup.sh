#!/usr/bin/env bash
# Devcontainer setup: everything the agents need to build and test python-for-ai.
set -euo pipefail

echo "Installing system dependencies (OCR + Chromium + mc + Postgres)..."
sudo apt-get update
sudo apt-get install -y chromium poppler-utils tesseract-ocr tesseract-ocr-hun tesseract-ocr-eng mc \
  postgresql postgresql-contrib pipx

echo "Installing uv..."
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

echo "Syncing each sub-project's isolated .venv..."
for pyproject in */pyproject.toml; do
  dir="$(dirname "$pyproject")"
  echo "  -> $dir"
  (cd "$dir" && uv sync)
done

echo "Installing pgAdmin (desktop mode, no login) via pipx..."
pipx ensurepath >/dev/null 2>&1 || true
export PATH="$HOME/.local/bin:$PATH"
pipx install pgadmin4
# passlib (a pgAdmin dependency) still imports the old pkg_resources API,
# which setuptools >=81 dropped entirely — pin an older setuptools in the
# pipx-managed venv so the import keeps working. --force is required: pgadmin4
# already pulls in a >=81 setuptools transitively, so a plain `inject` sees
# "setuptools already present" and silently no-ops without it.
pipx inject pgadmin4 "setuptools<81" --force

# Desktop mode has no interactive login, so pgAdmin gates any saved/passfile
# server connection behind an "Unlock Saved Passwords" master-password
# dialog on every launch. There's nothing worth protecting in a throwaway
# devcontainer DB, so disable the vault outright and let the graphtrek
# server (registered below) connect straight from ~/.pgpass with no prompt.
PGADMIN_SITE_PKG=$(find /usr/local/py-utils/venvs/pgadmin4/lib -maxdepth 3 -path '*/site-packages/pgadmin4' | head -1)
cat > "$PGADMIN_SITE_PKG/config_local.py" <<'EOF'
MASTER_PASSWORD_REQUIRED = False
USE_OS_SECRET_STORAGE = False
EOF

echo "Starting PostgreSQL and creating the ${DB_NAME} role/database..."
sudo service postgresql start
ready=0
for i in $(seq 1 30); do
  if pg_isready >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
if [ "$ready" -ne 1 ]; then
  echo "PostgreSQL did not become ready within 30s" >&2
  sudo pg_lsclusters >&2
  sudo tail -n 40 /var/log/postgresql/postgresql-*-main.log >&2 2>/dev/null || true
  exit 1
fi
# `sudo -u postgres` needs a password here (sudoers only grants passwordless
# root, not arbitrary target users) — `sudo su - postgres -c ...` becomes
# root first (passwordless) then `su`s to postgres, which root can always do.
sudo su - postgres -c "psql -tAc \"SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'\"" | grep -q 1 || \
  sudo su - postgres -c "psql -c \"CREATE ROLE \\\"${DB_USER}\\\" LOGIN PASSWORD '${DB_PWD}' SUPERUSER;\""
sudo su - postgres -c "psql -tAc \"SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'\"" | grep -q 1 || \
  sudo su - postgres -c "createdb -O '${DB_USER}' '${DB_NAME}'"

# Lets pgAdmin (and any psql/psycopg client) authenticate as DB_USER without
# a password prompt — this is what the graphtrek server registration below
# relies on instead of an encrypted saved password.
echo "localhost:5432:*:${DB_USER}:${DB_PWD}" > ~/.pgpass
chmod 600 ~/.pgpass

echo "Applying invoice-core Alembic migrations..."
(cd invoice-core && uv run alembic upgrade head)

echo "Installing OpenCode and agent-browser..."
# Chrome for Testing has no Linux ARM64 builds, so Chromium is installed via
# apt above (alongside the OCR deps); agent-browser finds it via
# AGENT_BROWSER_EXECUTABLE_PATH (containerEnv).
npm install -g opencode-ai agent-browser

echo "Adding the agent-browser skill for OpenCode..."
npx -y skills add vercel-labs/agent-browser -a opencode -y

echo "Verifying the installs..."
uv --version
opencode --version
agent-browser doctor
mc --version | head -1
pg_isready
command -v pgadmin4
bash .devcontainer/start-services.sh
pgadmin_ready=0
for i in $(seq 1 20); do
  if curl -sS -o /dev/null -w "pgAdmin HTTP %{http_code}\n" http://localhost:5050/ --max-time 2; then
    pgadmin_ready=1
    break
  fi
  sleep 1
done
if [ "$pgadmin_ready" -ne 1 ]; then
  echo "pgAdmin did not become ready within 20s" >&2
  tail -n 40 /tmp/pgadmin4.log >&2 2>/dev/null || true
  exit 1
fi

echo "Registering the graphtrek server in pgAdmin's browser tree..."
# Only after the readiness check above do we know pgadmin4 has booted once
# and created its own sqlite config DB (~/.pgadmin/pgadmin4.db) to load into.
cat > /tmp/pgadmin-servers.json <<EOF
{
  "Servers": {
    "1": {
      "Name": "${DB_NAME} (local)",
      "Group": "Servers",
      "Host": "localhost",
      "Port": 5432,
      "MaintenanceDB": "${DB_NAME}",
      "Username": "${DB_USER}",
      "SSLMode": "prefer",
      "PassFile": "/home/vscode/.pgpass"
    }
  }
}
EOF
/usr/local/py-utils/venvs/pgadmin4/bin/python "$PGADMIN_SITE_PKG/setup.py" load-servers \
  /tmp/pgadmin-servers.json --user pgadmin4@pgadmin.org \
  --sqlite-path /home/vscode/.pgadmin/pgadmin4.db --replace

echo "Setup complete."
