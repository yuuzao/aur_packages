# syntax=docker/dockerfile:1
# 干净的 Arch Linux 测试容器，用于隔离验证 *.pkg.tar.zst 安装与启动。
FROM archlinux:base-devel

RUN pacman-key --init && \
    pacman-key --populate archlinux && \
    pacman -Syu --noconfirm --noprogressbar --needed \
      archlinux-keyring \
      git \
      sudo && \
    useradd -m -s /bin/bash tester && \
    printf 'tester ALL=(ALL) NOPASSWD: ALL\n' > /etc/sudoers.d/tester && \
    chmod 440 /etc/sudoers.d/tester

WORKDIR /work
CMD ["/bin/bash"]
