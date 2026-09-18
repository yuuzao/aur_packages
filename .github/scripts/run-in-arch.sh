#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${LOG_LEVEL:-}" ]]; then
  echo "LOG_LEVEL is not set" >&2
  exit 1
fi
if [[ -z "${GITHUB_TOKEN:-}" ]]; then
  echo "GITHUB_TOKEN is not set" >&2
  exit 1
fi
if [[ "${LOG_LEVEL}" == "debug" ]]; then
  set -x
fi

pacman-key --init
pacman-key --populate archlinux
pacman -Syu --noconfirm --needed \
  archlinux-keyring \
  nvchecker \
  pacman-contrib \
  python \
  sudo

useradd -m builder
install -d -o builder -g builder /tmp/makepkg-srcdest
chmod -R a+rwX /work

python3 /work/.github/scripts/update_pkgver.py
