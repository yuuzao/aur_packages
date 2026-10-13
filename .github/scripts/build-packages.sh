#!/usr/bin/env bash
# Run inside archlinux:base-devel with source at /work and output at /out.
set -euo pipefail
pacman -Syu --noconfirm --needed archlinux-keyring sudo
useradd -m builder
printf 'builder ALL=(ALL) NOPASSWD: /usr/bin/pacman\n' > /etc/sudoers.d/builder
chmod 440 /etc/sudoers.d/builder
chown -R builder:builder /work /out
shopt -s nullglob
packages=(/work/*/PKGBUILD)
((${#packages[@]})) || { echo 'No PKGBUILD found' >&2; exit 1; }
for pkgbuild in "${packages[@]}"; do
  echo "Building ${pkgbuild%/PKGBUILD}"
  (
    cd "${pkgbuild%/PKGBUILD}"
    runuser -u builder -- env PKGDEST=/out makepkg --syncdeps --cleanbuild --noconfirm
  )
done
packages=(/out/*.pkg.tar.zst)
((${#packages[@]})) || { echo 'No package produced' >&2; exit 1; }
printf '%s\n' "${packages[@]##*/}" > /out/packages.txt
chmod -R a+rX /out
