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

## 自动更新版本

GitHub Actions 读取根目录 `nvchecker.toml`，用各软件包目录里 `PKGBUILD` 的 `pkgver` 作为当前版本，向对应上游探测是否有更新。有更新时直接在默认分支写入 `pkgver`、`pkgrel=1`、各架构校验和以及 `.SRCINFO`，然后构建并发布二进制包，不向 AUR 推送。

`nvchecker.toml` 里每个表的名字必须等于软件包目录名。探测规则写在该文件的注释中。

工作流每天 UTC 06:17 运行，也可在仓库 Actions 里手动 `Run workflow`。日志级别由环境变量 `LOG_LEVEL` 控制，取值：`debug`、`info`、`warning`、`error`。

## 二进制仓库发布

默认分支的软件包或流水线配置变更、每日版本检测和手动运行均会执行 x86_64 构建。构建任务不持有签名或发布凭据；独立发布任务使用专用签名子密钥，将产物发布到 `repository.toml` 指定的公开 GitHub Release。手动运行可关闭上游版本检测，仅发布当前提交。

发布目标为 `yuuzao/aur_packages-repo` 的 `repo-x86_64`，数据库名称为 `personal`。同名同版本的包复用已经发布且验签通过的文件；修改打包内容必须增加 `pkgrel`。索引从当前项目的全部构建产物生成，旧版本文件保留，已删除的软件包不再进入新索引。发布拒绝版本降级，先上传包和签名，再替换索引；索引替换失败会尝试恢复旧索引。GitHub 替换附件期间存在短暂下载窗口。

Actions 使用以下仓库 Secrets：

- `REPO_SIGNING_KEY`：ASCII-armored 签名私有子密钥，不包含主私钥。
- `REPO_SIGNING_PASSPHRASE`：签名子密钥口令。
- `REPO_PUBLISH_TOKEN`：仅授权公开分发仓库、具有 Contents 读写权限的 fine-grained PAT。

公钥指纹在 `repository.toml` 中固定，签名子密钥到期前需续期并更新 Secret 和公开公钥。默认 `GITHUB_TOKEN` 仅用于当前私有仓库的版本更新。
