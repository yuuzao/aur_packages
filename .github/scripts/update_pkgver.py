#!/usr/bin/env python3
"""根据 nvchecker.toml 探测上游版本，并写回 PKGBUILD / .SRCINFO。"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
NVCHECKER_TOML = REPO_ROOT / "nvchecker.toml"
SUM_BLOCK_RE = re.compile(
    r"^[ \t]*[a-z0-9]+sums(?:_[a-zA-Z0-9_]+)?\+?=\((?:.|\n)*?\)[ \t]*(?:#.*)?\n?",
    re.MULTILINE,
)
PKGVER_RE = re.compile(r"^pkgver=(.*)$", re.MULTILINE)
PKGREL_RE = re.compile(r"^pkgrel=(.*)$", re.MULTILINE)
PKGNAME_RE = re.compile(r"^pkgname=(.*)$", re.MULTILINE)
ARCH_RE = re.compile(r"^arch=\(([^)]*)\)", re.MULTILINE)


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


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if value is None or value == "":
        raise SystemExit(f"{name} is not set")
    return value


def load_nvchecker_config() -> dict:
    if not NVCHECKER_TOML.is_file():
        raise SystemExit(f"missing {NVCHECKER_TOML}")
    with NVCHECKER_TOML.open("rb") as fh:
        data = tomllib.load(fh)
    if "__config__" not in data:
        raise SystemExit("nvchecker.toml missing [__config__]")
    names = [key for key in data if key != "__config__"]
    if not names:
        raise SystemExit("nvchecker.toml has no package tables")
    return data


def unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def read_pkgbuild(pkg: str) -> tuple[Path, str]:
    path = REPO_ROOT / pkg / "PKGBUILD"
    if not path.is_file():
        raise SystemExit(f"{pkg}: PKGBUILD not found")
    return path, path.read_text(encoding="utf-8")


def pkgver_from_pkgbuild(pkg: str, text: str) -> str:
    match = PKGVER_RE.search(text)
    if match is None:
        raise SystemExit(f"{pkg}: pkgver= line missing")
    pkgver = unquote(match.group(1).split("#", 1)[0].strip())
    if pkgver == "":
        raise SystemExit(f"{pkg}: pkgver is empty")
    return pkgver


def assert_pkgname(pkg: str, text: str) -> None:
    match = PKGNAME_RE.search(text)
    if match is None:
        raise SystemExit(f"{pkg}: pkgname= line missing")
    raw = match.group(1).strip()
    if raw.startswith("("):
        raise SystemExit(f"{pkg}: split pkgname is not supported by the updater")
    pkgname = unquote(raw.split("#", 1)[0].strip())
    if pkgname != pkg:
        raise SystemExit(f"{pkg}: pkgname={pkgname} does not match directory")


def pkgbuild_arches(pkg: str, text: str) -> list[str]:
    match = ARCH_RE.search(text)
    if match is None:
        raise SystemExit(f"{pkg}: arch= line missing")
    arches = re.findall(r"['\"]([^'\"]+)['\"]", match.group(1))
    if not arches:
        raise SystemExit(f"{pkg}: arch= has no quoted architectures")
    return arches


def replace_once(pkg: str, text: str, pattern: re.Pattern[str], field: str, value: str) -> str:
    matches = pattern.findall(text)
    if len(matches) != 1:
        raise SystemExit(f"{pkg}: expected exactly 1 {field}= line, got {len(matches)}")
    updated, count = pattern.subn(f"{field}={value}", text, count=1)
    if count != 1:
        raise SystemExit(f"{pkg}: failed to replace {field}")
    return updated


def write_oldver(config: dict) -> None:
    relative = config["__config__"].get("oldver")
    if not relative:
        raise SystemExit("nvchecker.toml [__config__].oldver is missing")
    oldver_path = (NVCHECKER_TOML.parent / relative).resolve()
    oldver_path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, dict[str, str]] = {}
    for pkg in config:
        if pkg == "__config__":
            continue
        _path, text = read_pkgbuild(pkg)
        assert_pkgname(pkg, text)
        data[pkg] = {"version": pkgver_from_pkgbuild(pkg, text)}
    payload = {"version": 2, "data": data}
    oldver_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    logging.info("wrote oldver for %s", ", ".join(sorted(data)))


def write_keyfile(token: str) -> Path:
    path = REPO_ROOT / ".nvchecker" / "keyfile.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    if any(ch in token for ch in '"\\\n'):
        raise SystemExit("GITHUB_TOKEN contains characters that cannot be stored in keyfile.toml")
    path.write_text(f'[keys]\ngithub = "{token}"\n', encoding="utf-8")
    return path


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


def vercmp_newer(newver: str, oldver: str) -> None:
    output = run(["vercmp", newver, oldver]).strip()
    if output != "1":
        raise SystemExit(f"vercmp {newver} {oldver} => {output}, expected 1")


def parse_updates(raw: str) -> list[dict]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"nvcmp JSON parse failed: {exc}") from exc
    if not isinstance(payload, list):
        raise SystemExit("nvcmp JSON must be a list")
    updates = []
    for item in payload:
        if not isinstance(item, dict):
            raise SystemExit(f"nvcmp item is not an object: {item}")
        for key in ("name", "oldver", "newver", "delta"):
            if key not in item:
                raise SystemExit(f"nvcmp item missing {key}: {item}")
        if not isinstance(item["name"], str) or item["name"] == "":
            raise SystemExit(f"nvcmp name is invalid: {item}")
        if not isinstance(item["oldver"], str) or item["oldver"] == "":
            raise SystemExit(f"{item['name']}: oldver is invalid: {item['oldver']!r}")
        if not isinstance(item["newver"], str) or item["newver"] == "":
            raise SystemExit(f"{item['name']}: newver is invalid: {item['newver']!r}")
        if item["delta"] != "new":
            raise SystemExit(
                f"{item['name']}: unexpected delta={item['delta']} "
                f"({item['oldver']} -> {item['newver']})"
            )
        updates.append(item)
    return updates


def extract_sum_blocks(text: str) -> dict[str, str]:
    blocks: dict[str, str] = {}
    for match in SUM_BLOCK_RE.finditer(text):
        block = match.group(0).rstrip() + "\n"
        name_match = re.match(r"[ \t]*([a-z0-9]+sums(?:_[a-zA-Z0-9_]+)?)", block)
        if name_match is None:
            raise SystemExit(f"cannot parse checksum block: {block}")
        blocks[name_match.group(1)] = block
    if not blocks:
        raise SystemExit("makepkg -g produced no checksum arrays")
    return blocks


def replace_sum_blocks(pkg: str, text: str, blocks: dict[str, str], arch_order: list[str]) -> str:
    matches = list(SUM_BLOCK_RE.finditer(text))
    if not matches:
        raise SystemExit(f"{pkg}: PKGBUILD has no checksum arrays")
    start = matches[0].start()
    end = matches[-1].end()
    ordered: list[str] = []
    for key, block in blocks.items():
        if "_" not in key:
            ordered.append(block)
    for arch in arch_order:
        found = False
        for key, block in blocks.items():
            if key.endswith(f"_{arch}"):
                ordered.append(block)
                found = True
        if not found:
            raise SystemExit(f"{pkg}: missing checksum array for {arch}")
    unknown = [
        key
        for key in blocks
        if "_" in key and not any(key.endswith(f"_{arch}") for arch in arch_order)
    ]
    if unknown:
        raise SystemExit(f"{pkg}: unexpected checksum arrays {unknown}")
    return text[:start] + "".join(ordered) + text[end:]


def builder_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = "/home/builder"
    env["SRCDEST"] = "/tmp/makepkg-srcdest"
    if extra:
        env.update(extra)
    return env


def as_builder(cmd: list[str], *, cwd: Path, extra_env: dict[str, str] | None = None) -> str:
    env_args: list[str] = []
    merged = builder_env(extra_env)
    for key in ("HOME", "SRCDEST", "CARCH"):
        if key in merged:
            env_args.append(f"{key}={merged[key]}")
    wrapped = ["runuser", "-u", "builder", "--", "env", *env_args, *cmd]
    return run(wrapped, cwd=cwd, env=merged)


def collect_checksums(pkg: str, pkgdir: Path, arches: list[str]) -> dict[str, str]:
    merged: dict[str, str] = {}
    for arch in arches:
        logging.info("%s: generating checksums for %s", pkg, arch)
        output = as_builder(["makepkg", "-g"], cwd=pkgdir, extra_env={"CARCH": arch})
        blocks = extract_sum_blocks(output)
        merged.update(blocks)
    return merged


def bump_package(pkg: str, oldver: str, newver: str) -> None:
    if oldver is None or newver is None:
        raise SystemExit(f"{pkg}: oldver/newver is null")
    vercmp_newer(newver, oldver)
    pkgdir = REPO_ROOT / pkg
    path, text = read_pkgbuild(pkg)
    current = pkgver_from_pkgbuild(pkg, text)
    if current != oldver:
        raise SystemExit(f"{pkg}: PKGBUILD pkgver={current} != nvchecker oldver={oldver}")
    arches = pkgbuild_arches(pkg, text)
    text = replace_once(pkg, text, PKGVER_RE, "pkgver", newver)
    text = replace_once(pkg, text, PKGREL_RE, "pkgrel", "1")
    path.write_text(text, encoding="utf-8")
    logging.info("%s: pkgver %s -> %s, pkgrel=1", pkg, oldver, newver)

    checksums = collect_checksums(pkg, pkgdir, arches)
    text = path.read_text(encoding="utf-8")
    path.write_text(replace_sum_blocks(pkg, text, checksums, arches), encoding="utf-8")

    srcinfo = as_builder(["makepkg", "--printsrcinfo"], cwd=pkgdir)
    if srcinfo.strip() == "":
        raise SystemExit(f"{pkg}: makepkg --printsrcinfo produced empty output")
    (pkgdir / ".SRCINFO").write_text(srcinfo, encoding="utf-8")

    final = pkgver_from_pkgbuild(pkg, path.read_text(encoding="utf-8"))
    if final != newver:
        raise SystemExit(f"{pkg}: pkgver after bump is {final}, expected {newver}")


def updated_list_path() -> Path:
    path = REPO_ROOT / ".nvchecker" / "updated-packages.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def main() -> int:
    setup_logging()
    token = require_env("GITHUB_TOKEN")
    config = load_nvchecker_config()
    write_oldver(config)
    write_keyfile(token)

    run(
        [
            "nvchecker",
            "--failures",
            "-c",
            str(NVCHECKER_TOML),
        ],
        cwd=REPO_ROOT,
    )
    nvcmp_raw = run(
        ["nvcmp", "-c", str(NVCHECKER_TOML), "--json", "--newer"],
        cwd=REPO_ROOT,
    )
    logging.debug("nvcmp: %s", nvcmp_raw.strip())
    updates = parse_updates(nvcmp_raw.strip() or "[]")
    if not updates:
        logging.info("no package updates")
        updated_list_path().write_text("", encoding="utf-8")
        return 0

    lines = []
    for item in updates:
        bump_package(item["name"], item["oldver"], item["newver"])
        lines.append(f"{item['name']} {item['newver']}")
    updated_list_path().write_text("\n".join(lines) + "\n", encoding="utf-8")
    logging.info("updated: %s", ", ".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
