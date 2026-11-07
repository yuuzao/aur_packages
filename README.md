# aur_packages

严谨程度：项目说明。

> **自用说明**：本仓库为个人自用的 Arch Linux 软件包构建配置与 `pacman` 二进制软件源仓库。部分软件包的附属配置（如 systemd 服务默认监听端口、环境变量、登录用户绑定及 `PATH` 路径）针对个人本机环境定制，在其他机器上直接安装可能不完全适用。

## 项目介绍

本仓库集中维护个人自用的 Arch Linux `PKGBUILD` 与 `.SRCINFO`，并通过 GitHub Actions 自动跟踪上游版本更新、构建 `x86_64` 二进制包、使用 OpenPGP 子密钥签名后发布至本仓库的 `repo-x86_64` Release（数据库名称为 `personal`）。

## 内容索引

| 路径 | 说明 |
| :--- | :--- |
| [`dagu-bin/`](dagu-bin/) | `dagu` 工作流编排引擎预编译包及本机 `systemd` 服务配置 |
| [`deepseek-harness-bin/`](deepseek-harness-bin/) | DeepSeek Harness CLI 与 Web UI 预编译运行时及 `systemd` 服务配置 |
| [`llm-compare-bin/`](llm-compare-bin/) | 多模型与 ACP 智能体本地对比工作台预编译包 |
| [`super-productivity-bin/`](super-productivity-bin/) | Super Productivity 任务与时间管理桌面端预编译包 |
| [`workbuddy/`](workbuddy/) | WorkBuddy 桌面端预编译包 |
| [`repo-signing.asc`](repo-signing.asc) | `personal` 二进制仓库 OpenPGP 签名公钥（指纹：`5502F1B80D58187904CD60711D0FB4152310B9B1`） |
| [`repository.toml`](repository.toml) | 二进制软件源目标 Release、架构与签名公钥指纹配置 |
| [`nvchecker.toml`](nvchecker.toml) | 上游版本自动检测配置 |
| [`Dockerfile`](Dockerfile) | 隔离验证软件包安装与启动的 Arch Linux 测试容器定义 |
