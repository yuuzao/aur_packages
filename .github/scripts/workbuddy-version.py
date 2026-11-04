#!/usr/bin/env python3
"""打印已发布 Linux x64 deb 的最新 WorkBuddy 版本。

下载历史页按新到旧列出各平台构建号。Linux deb 与同一次构建的 Windows 包共用
「版本号-提交哈希」。copilot 的 Linux 更新接口会落后于这个页面，不能当作最新版本。
pkgver 不能包含连字符，因此构建号和提交哈希之间的连字符改成下划线。
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request

HISTORY_URL = "https://www.workbuddy.cn/docs/workbuddy/Download-History"
DEB_URL = (
    "https://download.codebuddy.cn/workbuddy/saas/linux-x64-deb/"
    "WorkBuddy-linux-x64-deb-{version}.deb"
)
VERSION_RE = re.compile(
    r"WorkBuddy-win32-x64-user-([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+-[0-9a-f]+)\.exe"
)
TIMEOUT_SECONDS = 30
MIN_DEB_BYTES = 1_000_000


def request(url: str, method: str) -> urllib.request.addinfourl:
    req = urllib.request.Request(
        url,
        method=method,
        headers={"User-Agent": "aur-packages-nvchecker"},
    )
    try:
        return urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS)
    except urllib.error.HTTPError:
        raise
    except Exception as exc:
        raise SystemExit(f"request failed: {method} {url}: {exc}") from exc


def history_versions() -> list[str]:
    with request(HISTORY_URL, "GET") as response:
        html = response.read().decode("utf-8")
    versions: list[str] = []
    for match in VERSION_RE.finditer(html):
        version = match.group(1)
        if version not in versions:
            versions.append(version)
    if not versions:
        raise SystemExit(f"no WorkBuddy build ids in {HISTORY_URL}")
    return versions


def linux_deb_exists(version: str) -> bool:
    url = DEB_URL.format(version=version)
    try:
        response = request(url, "HEAD")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False
        raise SystemExit(f"request failed: HEAD {url}: HTTP {exc.code}") from exc
    with response:
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip()
        length_text = response.headers.get("Content-Length")
    if content_type != "application/x-debian-package":
        raise SystemExit(f"unexpected content type for {url}: {content_type!r}")
    if length_text is None or length_text == "":
        raise SystemExit(f"missing content length for {url}")
    length = int(length_text)
    if length < MIN_DEB_BYTES:
        raise SystemExit(f"unexpected deb size for {url}: {length}")
    return True


def main() -> None:
    for version in history_versions():
        if linux_deb_exists(version):
            print(version.replace("-", "_"))
            return
    raise SystemExit("download history has no published Linux x64 deb")


if __name__ == "__main__":
    main()
