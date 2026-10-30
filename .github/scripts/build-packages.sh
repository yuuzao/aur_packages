#!/usr/bin/env bash
# Run inside archlinux:base-devel with source at /work and output at /out.
set -euo pipefail
pacman -Syu --noconfirm --noprogressbar --needed archlinux-keyring sudo
useradd -m -s /bin/bash builder
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
    runuser -u builder -- env PKGDEST=/out makepkg --syncdeps --cleanbuild --noconfirm --noprogressbar
  )
done
packages=(/out/*.pkg.tar.zst)
((${#packages[@]})) || { echo 'No package produced' >&2; exit 1; }

for pkgfile in "${packages[@]}"; do
  pkgname=$(pacman -Qp "${pkgfile}" | awk '{print $1}')
  echo "Testing installation and upgrade of ${pkgname} (${pkgfile##*/})"
  runuser -u builder -- sudo pacman -U --noconfirm --noprogressbar "${pkgfile}"
  runuser -u builder -- sudo pacman -U --noconfirm --noprogressbar "${pkgfile}"
  pacman -Qk "${pkgname}"

  mapfile -t bins < <(pacman -Qlq "${pkgname}" | grep -E '^/usr/bin/[^/]+$' || true)
  for bin in "${bins[@]}"; do
    test -x "${bin}" || { echo "Executable check failed: ${bin}" >&2; exit 1; }
  done

  if pacman -Qlq "${pkgname}" | grep -q '^/usr/share/applications/.*\.desktop$'; then
    echo "Skipping headless startup check for desktop application ${pkgname}"
  else
    for bin in "${bins[@]}"; do
      echo "Testing CLI startup: ${bin}"
      runuser -u builder -- "${bin}" --version >/dev/null 2>&1 \
        || runuser -u builder -- "${bin}" version >/dev/null 2>&1 \
        || runuser -u builder -- "${bin}" --help >/dev/null 2>&1 \
        || { echo "Startup check failed for ${bin}" >&2; exit 1; }
    done
  fi
done

printf '%s\n' "${packages[@]##*/}" > /out/packages.txt
chmod -R a+rX /out
