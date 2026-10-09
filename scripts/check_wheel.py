"""确认发布 wheel 含完整控制台资源，防止源码可用但安装后页面缺失。"""

from pathlib import Path
from zipfile import ZipFile

wheels = list(Path("dist").glob("*.whl"))
if len(wheels) != 1:
    raise SystemExit("Expected exactly one wheel in dist/")
with ZipFile(wheels[0]) as archive:
    for source in Path("src/ssh_mcp/static").rglob("*"):
        if source.is_file():
            packaged = source.relative_to("src").as_posix()
            if archive.read(packaged) != source.read_bytes():
                raise SystemExit(f"Wheel resource differs: {packaged}")
print("Wheel console resources verified")
