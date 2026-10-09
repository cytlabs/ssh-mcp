# 可复现安装与构建

## 锁定范围

- `uv.lock` 记录 Python 运行、测试和构建依赖及发行文件哈希，覆盖项目声明的 Python 3.10+；CI 实测 3.10、3.12、3.13。
- `package-lock.json` 记录前端测试的直接及传递依赖和完整性哈希。使用 `npm ci`，不在 CI 重新解析版本。
- uv 使用 `0.12.23`；构建后端及其依赖放入 `build` 依赖组，打包使用 `--no-isolation`，避免构建时另行解析后端。
- Docker 的 Python 基础镜像固定为清单摘要，构建和运行阶段使用同一基础镜像。生产环境只安装运行依赖与 wheel，测试依赖不进入最终虚拟环境。
- Python 库的 `pyproject.toml` 保留兼容范围，部署/测试的精确版本由锁文件决定。

这保证指定源码和平台下依赖选择可重现，不宣称不同机器产生逐字节相同镜像。GitHub 托管运行器、工作流 Action 主版本、Node 24 的补丁版本与独立代理 Caddy 仍可能更新；CI 记录实际版本，代理并不属于应用 Python 锁文件。

## 开发和原生部署

开发检查：

```sh
python -m pip install uv==0.12.23
uv sync --locked --extra dev --group build
uv run --no-sync ruff check .
SSH_MCP_REQUIRE_INTEGRATION=1 uv run --no-sync python -m unittest discover -s tests -v
uv run --no-sync python -m build --no-isolation
uv run --no-sync python scripts/check_wheel.py
uv run --no-sync pip-audit
npm ci
npm audit
npm run test:ui
npx playwright install --with-deps chromium
npm run test:browser
```

从已验收源码构建 wheel 后，可为生产建立独立环境，仅安装哈希校验的运行依赖与本次 wheel：

```sh
uv export --locked --no-dev --no-emit-project -o /tmp/ssh-mcp-requirements.txt
uv venv /opt/ssh-mcp/.venv
uv pip install --python /opt/ssh-mcp/.venv/bin/python --require-hashes -r /tmp/ssh-mcp-requirements.txt
uv pip install --python /opt/ssh-mcp/.venv/bin/python --no-deps dist/*.whl
```

部署账户、配置、HTTPS 和数据目录仍按 [部署说明](deployment.md) 设置。
构建前清理或使用空的 `dist/`，资源检查要求目录中只有本次 wheel。

## 更新依赖

有意更新时执行 `uv lock --upgrade`；只改指定依赖使用 `uv lock --upgrade-package 包名`。
前端通过 `npm install --save-dev 包名@版本` 同时更新声明和锁文件。提交前检查差异、许可证与审计结果。
更新 uv 时，同步 CI、Dockerfile 和文档中的版本。更新基础镜像时重新核实镜像摘要并完成容器测试。

所有更新必须通过三版本 Python 测试、浏览器、依赖审计、wheel 资源检查和容器构建；不忽略失败的审计项。
正常 CI 使用 `--locked`，声明与锁文件不同步会失败。

## 构建证据

CI 上传各 Python 版本的 `python-版本-build` 产物，包含：提交号、Python/uv 版本、安装依赖列表、锁文件及安装包 SHA-256、wheel 和源码包。
容器任务记录基础镜像与最终镜像信息；浏览器任务记录 Node/npm 版本并上传截图。
这些证明自动化构建通过，不替代生产部署或真实 AI 客户端验收。
