# aur_packages

严谨程度：项目说明。只描述仓库用途和通用约定，不枚举当前收录的软件包。

本仓库用于集中管理 Arch Linux 的 PKGBUILD。每个软件包一个目录，目录名与 `pkgname` 一致，目录内保存 `PKGBUILD`、`.SRCINFO` 以及构建所需的附属文件。具体有哪些包，以仓库里的目录为准。

## 构建

需要安装 `base-devel`，进入软件包目录后执行：

```bash
cd <pkgname>
makepkg -si
```

更新 `.SRCINFO`：

```bash
makepkg --printsrcinfo > .SRCINFO
```

## 约定

- 一个目录只对应一个 `pkgname`（split package 仍放在同一目录，由 `PKGBUILD` 内的 `pkgname` 数组声明）。
- 不提交 `pkg/`、`src/` 以及 `*.pkg.tar.*` 等构建产物。
- 上游源码在构建时按 `PKGBUILD` 的 `source` 下载，不在本仓库镜像完整上游树。
- 向 AUR 发布时，使用该软件包自己的 AUR Git 远程，不要把本仓库根目录当作单个 AUR 包推送。
