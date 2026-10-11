#!/bin/sh
# 部署前只读检查。不安装软件、不创建文件、不读取凭据、不修改或重启现有服务。
set -u

printf '\n系统与资源\n'
uname -sm
if [ -r /etc/os-release ]; then
    sed -n '/^PRETTY_NAME=/p' /etc/os-release
fi
df -h / /tmp
if command -v free >/dev/null 2>&1; then free -h; fi

printf '\n容器与运行环境\n'
if command -v docker >/dev/null 2>&1; then
    docker --version
    docker compose version 2>/dev/null || printf 'Docker Compose 插件不可用\n'
    docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Ports}}' ||
        printf '无法读取 Docker 状态，请核实权限和服务状态\n'
else
    printf '未找到 Docker\n'
fi
if command -v python3 >/dev/null 2>&1; then python3 --version; fi
if command -v nginx >/dev/null 2>&1; then nginx -v 2>&1; fi
if command -v caddy >/dev/null 2>&1; then caddy version; fi

printf '\n候选端口监听（80、443、8000、18080）\n'
if command -v ss >/dev/null 2>&1; then
    ss -ltnp '( sport = :80 or sport = :443 or sport = :8000 or sport = :18080 )' ||
        printf '监听检查失败，不能据此判断端口空闲\n'
else
    printf '未找到 ss，尚不能判断端口占用\n'
fi

printf '\n已有部署目录（只检查是否存在）\n'
for target in /opt/ssh-mcp /etc/ssh-mcp /var/lib/ssh-mcp; do
    if [ -e "$target" ]; then
        printf '%s 已存在，部署前核实用途，不覆盖\n' "$target"
    else
        printf '%s 不存在\n' "$target"
    fi
done
printf '\n检查结束。以上结果不代表 HTTPS、SSH 凭据或客户端已经验收。\n'
