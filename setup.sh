#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
target="${1:-backend}"  # backend | raspi

install_reqs() {
  local pattern="$1"
  local found=0
  while IFS= read -r req; do
    found=1
    echo "Installing from $req"
    python -m pip install -r "$req" --no-build-isolation
  done < <(find "$repo_root" -path "$pattern" -name requirements.txt | sort)
  if [ "$found" -eq 0 ]; then
    echo "No requirements.txt matched pattern $pattern"
  fi
}

if [ "$target" = "backend" ]; then
  echo "Setting up for backend..."
  echo "Ensuring setuptools is installed..."
  python -m pip install setuptools
  echo "Initializing Detic submodules..."
  (cd "$repo_root/visual/Detic" && git submodule update --init --recursive)
  echo "Installing all requirements (excluding pi_hardware)..."
  while IFS= read -r req; do
    echo "Installing from $req"
    python -m pip install -r "$req" --no-build-isolation
  done < <(find "$repo_root" -name requirements.txt ! -path "$repo_root/pi_hardware/*" | sort)
elif [ "$target" = "raspi" ]; then
  echo "Setting up for raspi (pi_hardware only)..."
  install_reqs "$repo_root/pi_hardware/*"
else
  echo "Unknown target: $target (use 'backend' or 'raspi')"
  exit 1
fi

echo "Setup complete."
