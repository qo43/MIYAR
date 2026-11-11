#!/usr/bin/env bash
# One-click start for Windows + WSL. Called by start-dashboard.bat.
# Installs into WSL's Linux filesystem (~/.cybernext) for speed; the project
# folder itself (and results/) stays on the Windows side where you can see it.
set -euo pipefail
cd "$(dirname "$0")/.."
HOME_DIR="$HOME/.cybernext"
VENV="$HOME_DIR/venv"
NODE_DIR="$HOME_DIR/node"

say() { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }
need_apt=()
command -v python3 >/dev/null || need_apt+=(python3)
python3 -c "import venv, ensurepip" 2>/dev/null || need_apt+=(python3-venv)
command -v git >/dev/null || need_apt+=(git)
dpkg -s libpango-1.0-0 >/dev/null 2>&1 || need_apt+=(libpango-1.0-0 libpangoft2-1.0-0)
node_ok=0
if command -v node >/dev/null; then
  [ "$(node -p 'process.versions.node.split(".")[0]')" -ge 20 ] && node_ok=1
fi

if [ ${#need_apt[@]} -gt 0 ] || [ $node_ok -eq 0 ]; then
  say "Missing system packages: ${need_apt[*]} $( [ $node_ok -eq 0 ] && echo 'nodejs>=20')"
  read -r -p "Install them now with sudo? [y/N] " ans
  if [[ "$ans" =~ ^[Yy]$ ]]; then
    sudo apt-get update
    [ ${#need_apt[@]} -gt 0 ] && sudo apt-get install -y "${need_apt[@]}"
    if [ $node_ok -eq 0 ]; then
      curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
      sudo apt-get install -y nodejs
    fi
  else
    echo "Install them, then run this again."; exit 1
  fi
fi

mkdir -p "$HOME_DIR"
if [ ! -x "$VENV/bin/python" ]; then
  say "Creating Python environment (first run only)"
  python3 -m venv "$VENV"
fi
STAMP="$HOME_DIR/.deps-$(sha1sum requirements.txt requirements-pdf.txt package-lock.json | sha1sum | cut -c1-12)"
if [ ! -f "$STAMP" ]; then
  say "Installing Python packages"
  "$VENV/bin/pip" install -q --upgrade pip
  "$VENV/bin/pip" install -q -r requirements.txt -r requirements-pdf.txt
  say "Installing pinned promptfoo"
  mkdir -p "$NODE_DIR" && cp package.json package-lock.json "$NODE_DIR/"
  (cd "$NODE_DIR" && npm ci --no-audit --no-fund --silent)
  touch "$STAMP"
fi
export PROMPTFOO_BIN="$NODE_DIR/node_modules/.bin/promptfoo"
[ -f .env ] || cp .env.example .env
set -a; source .env; set +a

if [ ! -f benchmark/external/absher.json ]; then
  read -r -p "Download the Absher Saudi-dialect benchmark (17,840 questions)? [y/N] " ans
  [[ "$ans" =~ ^[Yy]$ ]] && "$VENV/bin/python" -m benchmark.importers.absher || true
fi

say "Starting dashboard on http://localhost:8501  (close this window to stop)"
(sleep 4; cmd.exe /c start http://localhost:8501 >/dev/null 2>&1 || true) &
exec "$VENV/bin/python" -m streamlit run dashboard/app.py --server.headless true --server.port 8501
