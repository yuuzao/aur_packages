#!/usr/bin/env python3
"""Sign packages and publish a pacman repository to a fixed GitHub release."""

import argparse
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import tomllib
from pathlib import Path

IMAGE = "archlinux:base-devel"


def run(args, **kwargs):
    print("+", " ".join(map(str, args)), flush=True)
    return subprocess.run(args, check=True, **kwargs)


def output(args):
    return subprocess.check_output(args, text=True)


def versions(database):
    result = {}
    with tarfile.open(database) as archive:
        for member in archive.getmembers():
            if member.name.endswith("/desc"):
                fields = archive.extractfile(member).read().decode().split("\n\n")
                data = {
                    part.splitlines()[0]: part.splitlines()[1:]
                    for part in fields
                    if part
                }
                result[data["%NAME%"][0]] = data["%VERSION%"][0]
    return result


def prepare(config, packages, work, gh, gpg):
    published = json.loads(output(gh + ["view", config["release"], "--json", "assets"]))
    assets = {asset["name"] for asset in published["assets"]}
    names = (packages / "packages.txt").read_text().splitlines()
    if not names or len(names) != len(set(names)):
        raise SystemExit("Package manifest is empty or contains duplicates")
    fresh = []
    for name in names:
        if not re.fullmatch(r"[A-Za-z0-9@+_.:-]+\.pkg\.tar\.zst", name):
            raise SystemExit(f"Invalid package filename: {name}")
        if not name.endswith(("-x86_64.pkg.tar.zst", "-any.pkg.tar.zst")):
            raise SystemExit(f"Unsupported architecture: {name}")
        target = work / name
        if name in assets:
            if name + ".sig" not in assets:
                raise SystemExit(f"Published package has no signature: {name}")
            run(
                gh
                + [
                    "download",
                    config["release"],
                    "--pattern",
                    name,
                    "--pattern",
                    name + ".sig",
                    "--dir",
                    str(work),
                ]
            )
        else:
            shutil.copyfile(packages / name, target)
            run(
                gpg
                + [
                    "--local-user",
                    config["signing_fingerprint"],
                    "--detach-sign",
                    str(target),
                ]
            )
            fresh.append(name)
        run(gpg + ["--verify", str(target) + ".sig", str(target)])
    return names, fresh, assets


def make_database(config, names, work, backup, gh, assets):
    database = config["database"]
    for name in (database + ".db", database + ".files"):
        if name in assets:
            run(
                gh
                + [
                    "download",
                    config["release"],
                    "--pattern",
                    name,
                    "--dir",
                    str(backup),
                ]
            )
    # Mount only public artifacts. No private keys or publishing credentials enter Docker.
    run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{work}:/repo",
            "-w",
            "/repo",
            IMAGE,
            "repo-add",
            database + ".db.tar.gz",
            *names,
        ]
    )
    old = backup / (database + ".db")
    if old.exists():
        old_versions = versions(old)
        for name, version in versions(work / (database + ".db.tar.gz")).items():
            if name in old_versions:
                comparison = output(
                    [
                        "docker",
                        "run",
                        "--rm",
                        IMAGE,
                        "vercmp",
                        version,
                        old_versions[name],
                    ]
                ).strip()
                if int(comparison) < 0:
                    raise SystemExit(
                        f"Refusing downgrade: {name} {old_versions[name]} -> {version}"
                    )
    # Release assets must be real files, not repo-add symlinks.
    for extension in ("db", "files"):
        target = work / f"{database}.{extension}"
        target.unlink()
        shutil.copyfile(work / f"{database}.{extension}.tar.gz", target)


def publish(config, fresh, work, backup, gh):
    tag = config["release"]
    for name in fresh:
        run(gh + ["upload", tag, str(work / (name + ".sig")), "--clobber"])
        run(gh + ["upload", tag, str(work / name)])
    run(gh + ["upload", tag, str(work / "repo-signing.asc"), "--clobber"])
    # Keep old versioned packages so clients holding old indexes can still download.
    indexes = [config["database"] + ".files", config["database"] + ".db"]
    try:
        for name in indexes:
            run(gh + ["upload", tag, str(work / name), "--clobber"])
    except subprocess.CalledProcessError:
        for name in indexes:
            previous = backup / name
            if previous.exists():
                restored = subprocess.run(
                    gh + ["upload", tag, str(previous), "--clobber"], check=False
                )
                if restored.returncode:
                    print(f"ERROR: restore failed for {name}", flush=True)
        raise
    notes = work / "release-notes.md"
    notes.write_text(
        f"Signed pacman repository for {config['architecture']}.\n\n"
        f"Public key fingerprint: `{config['signing_fingerprint']}`\n\n"
        "Import and locally trust `repo-signing.asc` before enabling this repository.\n\n"
        f"```ini\n[{config['database']}]\nSigLevel = Required DatabaseOptional\n"
        f"Server = https://github.com/{config['repository']}/releases/download/repo-$arch\n```\n\n"
        "Versioned packages are retained for clients using older indexes.\n"
    )
    run(
        gh
        + [
            "edit",
            tag,
            "--title",
            f"Signed pacman repository ({config['architecture']})",
            "--notes-file",
            str(notes),
            "--prerelease=false",
            "--latest=false",
        ]
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packages", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("repository.toml"))
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Prepare and verify without modifying GitHub",
    )
    args = parser.parse_args()
    config = tomllib.loads(args.config.read_text())
    if config["architecture"] != "x86_64":
        raise SystemExit("Only x86_64 build runners are configured")
    fingerprint = config["signing_fingerprint"]
    if not re.fullmatch(r"[A-F0-9]{40}", fingerprint):
        raise SystemExit("Expected a full OpenPGP fingerprint")
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", config["database"]):
        raise SystemExit("Invalid database name")
    for key in ("REPO_SIGNING_KEY", "REPO_SIGNING_PASSPHRASE"):
        if not os.environ.get(key):
            raise SystemExit(f"Missing {key}")
    gh = ["gh", "release", "--repo", config["repository"]]
    # The distribution repository/release is provisioned separately, never guessed.
    with tempfile.TemporaryDirectory(prefix="pacman-publish-") as temp:
        root = Path(temp)
        home = root / "gnupg"
        home.mkdir(mode=0o700)
        work = root / "public"
        work.mkdir()
        backup = root / "backup"
        backup.mkdir()
        password = root / "passphrase"
        password.touch(mode=0o600)
        password.write_text(os.environ.pop("REPO_SIGNING_PASSPHRASE"))
        gpg = [
            "gpg",
            "--homedir",
            str(home),
            "--batch",
            "--pinentry-mode",
            "loopback",
            "--passphrase-file",
            str(password),
        ]
        try:
            run(gpg + ["--import"], input=os.environ.pop("REPO_SIGNING_KEY"), text=True)
            listing = output(gpg + ["--with-colons", "--list-keys"])
            fingerprints = [
                line.split(":")[9]
                for line in listing.splitlines()
                if line.startswith("fpr:")
            ]
            if not fingerprints or fingerprints[0] != fingerprint:
                raise SystemExit("Signing key does not match configured fingerprint")
            run(gpg + ["--import-ownertrust"], input=f"{fingerprint}:6:\n", text=True)
            names, fresh, assets = prepare(
                config, args.packages.resolve(), work, gh, gpg
            )
            make_database(config, names, work, backup, gh, assets)
            with (work / "repo-signing.asc").open("w") as stream:
                run(gpg + ["--armor", "--export", fingerprint], stdout=stream)
            if args.dry_run:
                print(
                    f"Validated {len(names)} packages; {len(fresh)} new; no remote changes."
                )
            else:
                publish(config, fresh, work, backup, gh)
        finally:
            subprocess.run(
                ["gpgconf", "--homedir", str(home), "--kill", "all"], check=False
            )


if __name__ == "__main__":
    main()
