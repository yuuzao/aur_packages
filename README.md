# aur_packages

严谨程度：项目说明。只描述仓库用途和通用约定，不枚举当前收录的软件包。

本仓库用于集中管理 Arch Linux 的 PKGBUILD。每个软件包一个目录，目录名与 `pkgname` 一致，目录内保存 `PKGBUILD`、`.SRCINFO` 以及构建所需的附属文件。具体有哪些包，以仓库里的目录为准。

## 关联仓库

| 仓库 | 可见性 | 职责 |
| :--- | :--- | :--- |
| `yuuzao/aur_packages`（本仓库） | 私有 | 保存 PKGBUILD、版本检测与构建发布流水线；不存放构建产物。 |
| `yuuzao/aur_packages-repo` | 公开 | 仅作 pacman 二进制仓库分发：git 内容只有 `README.md` 与公钥 `repo-signing.asc`，包、签名和数据库索引全部作为 Release `repo-x86_64` 的附件。 |

本仓库的发布任务通过 `REPO_PUBLISH_TOKEN` 向公开仓库的 Release 上传附件，pacman 客户端从该 Release 匿名下载。公开仓库及其 Release 需预先单独创建，流水线不负责创建；每次运行先以 `REPO_PUBLISH_TOKEN` 通过 GitHub API 查询该 Release，失败即终止，不进入构建。两个仓库都不向 AUR 推送。

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
- 已在 `nvchecker.toml` 中跟踪的软件包，其 `pkgver`、`pkgrel=1`、校验和与 `.SRCINFO` 中对应字段由 CI 写入默认分支，本地不手工修改；本地只改打包内容，并同时增加 `pkgrel`。修改前先 `git pull --rebase`，避免在过期基线上提交。
- 二进制包只由 CI 构建和发布，不从本地上传到公开 Release。
- 向 AUR 发布时，使用该软件包自己的 AUR Git 远程，不要把本仓库根目录当作单个 AUR 包推送。

## 自动更新版本

GitHub Actions 读取根目录 `nvchecker.toml`，用各软件包目录里 `PKGBUILD` 的 `pkgver` 作为当前版本，向对应上游探测是否有更新。有更新时直接在默认分支写入 `pkgver`、`pkgrel=1`、各架构校验和以及 `.SRCINFO`，然后构建并发布二进制包，不向 AUR 推送。

`nvchecker.toml` 里每个表的名字必须等于软件包目录名。探测规则写在该文件的注释中。

判定规则：

- 当前收录的包均取上游 GitHub 标记为 latest 的 release（不含 pre-release），去掉 tag 前缀 `v` 后比较；每次只跟进最新版本，中间版本不补。
- 新版本必须经 `vercmp` 判定大于当前 `pkgver`，且 `PKGBUILD` 中的 `pkgver` 必须与生成的旧版本记录一致，否则报错终止。
- 任一软件包探测或生成校验和失败，整次运行终止，所有软件包的更新均不提交。

工作流每天 UTC 06:17 运行，也可在仓库 Actions 里手动 `Run workflow`。日志级别由环境变量 `LOG_LEVEL` 控制，取值：`debug`、`info`、`warning`、`error`。

## 二进制仓库发布

默认分支的软件包或流水线配置变更、每日版本检测和手动运行均会执行 x86_64 构建。构建任务不持有签名或发布凭据；独立发布任务使用专用签名子密钥，将产物发布到 `repository.toml` 指定的公开 GitHub Release。手动运行可关闭上游版本检测，仅发布当前提交。

发布目标为 `yuuzao/aur_packages-repo` 的 `repo-x86_64`，数据库名称为 `personal`。同名同版本的包复用已经发布且验签通过的文件；修改打包内容必须增加 `pkgrel`。索引从当前项目的全部构建产物生成，旧版本文件保留，已删除的软件包不再进入新索引。发布拒绝版本降级，先上传包和签名，再替换索引；索引替换失败会尝试恢复旧索引。GitHub 替换附件期间存在短暂下载窗口。

Actions 使用以下仓库 Secrets：

- `REPO_SIGNING_KEY`：ASCII-armored 签名私有子密钥，不包含主私钥。
- `REPO_SIGNING_PASSPHRASE`：签名子密钥口令。
- `REPO_PUBLISH_TOKEN`：仅授权公开分发仓库、具有 Contents 读写权限的 fine-grained PAT。

公钥指纹在 `repository.toml` 中固定，签名子密钥到期前需续期并更新 Secret 和公开公钥。默认 `GITHUB_TOKEN` 仅用于当前私有仓库的版本更新。
