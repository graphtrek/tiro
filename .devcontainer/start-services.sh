#!/usr/bin/env bash
# Runs on every devcontainer start (postStartCommand) — postgresql and
# pgadmin4 are plain processes with no init system to supervise them, so
# they need to be (re)started explicitly each time the container starts,
# unlike postCreateCommand's one-time role/database setup in setup.sh.
set -uo pipefail

sudo service postgresql start >/dev/null 2>&1

export PATH="$HOME/.local/bin:$PATH"
# PGADMIN_SERVER_MODE=OFF is pgAdmin's own documented switch (read in
# pgAdmin4.py before config.py loads) for desktop/no-login mode — it also
# routes pgAdmin's data dir to ~/.pgadmin instead of the root-owned
# /var/lib/pgadmin, which is what makes this work unprivileged at all.
export PGADMIN_SERVER_MODE=OFF
if ! curl -sS -o /dev/null --max-time 1 http://localhost:5050/ 2>/dev/null; then
  nohup pgadmin4 >/tmp/pgadmin4.log 2>&1 &
  disown
fi

true
