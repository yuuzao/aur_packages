#!/usr/bin/env python3
"""检测 deepseek-ai/deepseek-harness 的最新 RC/正式版 Release Tag，
若公开分发仓库尚无对应预编译产物，则在 Arch Linux x86_64 容器中编译并发布 Release。
"""

from __future__ import annotations

import functools
import json
import logging
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_TOML = REPO_ROOT / "repository.toml"
PKGBUILD_PATH = REPO_ROOT / "deepseek-harness-bin" / "PKGBUILD"
UPSTREAM_GIT_URL = "https://github.com/deepseek-ai/deepseek-harness.git"
# 仅匹配正式版 dsh-vX.Y.Z 与 RC 版 dsh-vX.Y.Z-rc.N，排除 alpha 等其他标签
TAG_RE = re.compile(r"^refs/tags/(dsh-v(\d+\.\d+\.\d+(?:-rc\.\d+)?))$")
PKGVER_RE = re.compile(r"^pkgver=(.*)$", re.MULTILINE)


def setup_logging() -> None:
    raw = os.environ.get("LOG_LEVEL")
    if raw is None or raw == "":
        raise SystemExit("LOG_LEVEL is not set")
    name = raw.upper()
    if name == "WARN":
        name = "WARNING"
    if name not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
        raise SystemExit(f"unsupported LOG_LEVEL: {raw}")
    logging.basicConfig(
        level=getattr(logging, name),
        format="%(levelname)s %(message)s",
    )


def run(cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> str:
    logging.debug("run: %s", " ".join(cmd))
    completed = subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.stderr:
        logging.debug("stderr: %s", completed.stderr.rstrip())
    if completed.returncode != 0:
        logging.error("stdout: %s", completed.stdout)
        logging.error("stderr: %s", completed.stderr)
        raise SystemExit(f"command failed ({completed.returncode}): {' '.join(cmd)}")
    return completed.stdout


def vercmp(ver1: str, ver2: str) -> int:
    if shutil.which("vercmp"):
        out = run(["vercmp", ver1, ver2]).strip()
        return int(out)
    out = run(["docker", "run", "--rm", "archlinux:base-devel", "vercmp", ver1, ver2]).strip()
    return int(out)


def sort_pkgvers(pkgvers: list[str]) -> list[str]:
    if shutil.which("vercmp"):
        return sorted(pkgvers, key=functools.cmp_to_key(vercmp))
    helper = (
        "import functools, json, subprocess, sys\n"
        "items = json.loads(sys.argv[1])\n"
        "def cmp(a, b):\n"
        "    return int(subprocess.check_output(['vercmp', a, b], text=True).strip())\n"
        "print(json.dumps(sorted(items, key=functools.cmp_to_key(cmp))))\n"
    )
    out = run(
        [
            "docker",
            "run",
            "--rm",
            "archlinux:base-devel",
            "python3",
            "-c",
            helper,
            json.dumps(pkgvers),
        ]
    ).strip()
    return json.loads(out)


def current_pkgbuild_pkgver() -> str:
    if not PKGBUILD_PATH.is_file():
        raise SystemExit(f"missing {PKGBUILD_PATH}")
    text = PKGBUILD_PATH.read_text(encoding="utf-8")
    match = PKGVER_RE.search(text)
    if match is None:
        raise SystemExit("deepseek-harness-bin/PKGBUILD missing pkgver=")
    val = match.group(1).split("#", 1)[0].strip().strip("'\"")
    if not val:
        raise SystemExit("deepseek-harness-bin/PKGBUILD pkgver is empty")
    return val


def latest_upstream_tag() -> tuple[str, str]:
    raw = run(["git", "ls-remote", "--tags", "--refs", UPSTREAM_GIT_URL, "refs/tags/dsh-v*"])
    candidates: dict[str, str] = {}
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        match = TAG_RE.match(parts[1])
        if match is None:
            continue
        tag_name = match.group(1)
        raw_ver = match.group(2)
        pkgver = raw_ver.replace("-rc.", "rc.")
        candidates[pkgver] = tag_name
    if not candidates:
        raise SystemExit("no matching dsh-v* RC/stable tags found in upstream repository")
    sorted_pkgvers = sort_pkgvers(list(candidates.keys()))
    best_pkgver = sorted_pkgvers[-1]
    return candidates[best_pkgver], best_pkgver


def release_exists(target_repo: str, release_tag: str, asset_name: str) -> bool:
    completed = subprocess.run(
        ["gh", "release", "view", release_tag, "--repo", target_repo, "--json", "assets", "--jq", ".assets[].name"],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        return False
    assets = set(completed.stdout.splitlines())
    return asset_name in assets


def require_readable_tarball(path: Path) -> None:
    try:
        st = path.stat()
    except OSError as exc:
        raise SystemExit(f"cannot stat tarball {path}: {exc}") from exc
    if not stat.S_ISREG(st.st_mode):
        raise SystemExit(
            f"tarball is not a regular file: {path} mode={st.st_mode:o} uid={st.st_uid}"
        )
    if st.st_size == 0:
        raise SystemExit(f"tarball is empty: {path} mode={st.st_mode:o} uid={st.st_uid}")
    if not os.access(path, os.R_OK):
        raise SystemExit(
            f"tarball is not readable: {path} mode={st.st_mode:o} uid={st.st_uid}"
        )


def build_linux_tarball(upstream_tag: str, pkgver: str, out_dir: Path) -> Path:
    tarball_name = f"deepseek-harness-v{pkgver}-linux-x64.tar.gz"
    # /out 是宿主机上模式 0700 的临时目录。容器里 chown 这个挂载点会改掉宿主机属主，
    # runner 随后读不到产物，退出时也删不掉目录。产物先写在容器自己的 /tmp，再由 root 安装到 /out。
    script = f"""set -euo pipefail
pacman-key --init
pacman-key --populate archlinux
pacman -Syu --noconfirm --needed archlinux-keyring base-devel git libarchive nodejs npm pnpm python sudo
useradd -m builder

runuser -u builder -- bash -ce '
  set -euo pipefail
  export PATH="/usr/bin:$PATH"
  export NODE_DISABLE_COMPILE_CACHE=1
  export DSH_TELEMETRY_DISABLED=1
  workdir=$(mktemp -d /tmp/dsh-build-XXXXXX)
  trap "rm -rf \\"$workdir\\"" EXIT
  cd "$workdir"

  git clone --branch "{upstream_tag}" --depth 1 "{UPSTREAM_GIT_URL}" deepseek-harness
  cd deepseek-harness

  node -e "const fs=require(\\"fs\\"); const p=JSON.parse(fs.readFileSync(\\"package.json\\",\\"utf8\\")); delete p.scripts.postinstall; fs.writeFileSync(\\"package.json\\", JSON.stringify(p,null,2)+\\"\\\\n\\")"
  export pnpm_config_store_dir="$workdir/.pnpm-store"
  pnpm install --frozen-lockfile --store-dir "$pnpm_config_store_dir"
  pnpm run build:official

  rm -rf dist/aur-dsh dist/aur-vendor
  pnpm run release:pack --family vendor --out dist/aur-vendor
  pnpm run release:pack --family dsh --out dist/aur-dsh

  node /work/.github/scripts/deepseek-harness/aur-package.mjs "$workdir"

  cd "$workdir/npm-root"
  npm install --include=optional --os=linux --cpu=x64 --libc=glibc --no-audit --no-fund --package-lock=false

  rm -rf node_modules/node-pty/prebuilds/darwin-* \\
         node_modules/node-pty/prebuilds/win32-* \\
         node_modules/node-pty/prebuilds/linux-arm* \\
         node_modules/node-pty/third_party/conpty

  node /work/.github/scripts/deepseek-harness/check-runtime.mjs "$workdir/npm-root"
  node "$workdir/npm-root/node_modules/@deepseek-ai/dsh/lib/bin.js" --version

  cp "$workdir/deepseek-harness/LICENSE" "$workdir/npm-root/LICENSE"
  tar -C "$workdir/npm-root" -czf /tmp/deepseek-harness-linux-x64.tar.gz node_modules LICENSE
'
install -m 644 /tmp/deepseek-harness-linux-x64.tar.gz "/out/{tarball_name}"
test -s "/out/{tarball_name}"
"""
    run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{REPO_ROOT}:/work:ro",
            "-v",
            f"{out_dir}:/out",
            "archlinux:base-devel",
            "bash",
            "-c",
            script,
        ]
    )
    tarball_path = out_dir / tarball_name
    require_readable_tarball(tarball_path)
    return tarball_path


def main() -> int:
    setup_logging()
    if not os.environ.get("GH_TOKEN"):
        raise SystemExit("GH_TOKEN is not set")
    with REPOSITORY_TOML.open("rb") as fh:
        repo_cfg = tomllib.load(fh)
    target_repo = repo_cfg["repository"]

    current_ver = current_pkgbuild_pkgver()
    upstream_tag, latest_ver = latest_upstream_tag()
    logging.info("deepseek-harness: current=%s, upstream_latest=%s (%s)", current_ver, latest_ver, upstream_tag)

    cmp_res = vercmp(latest_ver, current_ver)
    if cmp_res < 0:
        raise SystemExit(
            f"upstream tag {upstream_tag} ({latest_ver}) is older than current PKGBUILD ({current_ver})"
        )

    release_tag = f"v{latest_ver}"
    asset_name = f"deepseek-harness-{release_tag}-linux-x64.tar.gz"
    if release_exists(target_repo, release_tag, asset_name):
        logging.info("release %s with %s already exists in %s; skipping prebuild", release_tag, asset_name, target_repo)
        return 0

    logging.info("building %s from upstream tag %s in Linux x86_64 container", asset_name, upstream_tag)
    with tempfile.TemporaryDirectory(prefix="dsh-prebuild-") as tmp:
        out_dir = Path(tmp)
        tarball = build_linux_tarball(upstream_tag, latest_ver, out_dir)
        run(
            [
                "gh",
                "release",
                "create",
                release_tag,
                str(tarball),
                "--repo",
                target_repo,
                "--title",
                f"deepseek-harness {release_tag} (Linux x86_64)",
                "--notes",
                f"Prebuilt Linux x86_64 runtime for deepseek-harness-bin (from upstream tag `{upstream_tag}`).",
                "--latest",
            ]
        )
    logging.info("published %s to %s", release_tag, target_repo)
    return 0


if __name__ == "__main__":
    sys.exit(main())
