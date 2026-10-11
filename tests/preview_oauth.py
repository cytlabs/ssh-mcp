"""本机 HTTPS 浏览器验收夹具：临时自签名证书和空服务器清单。"""
import asyncio
import datetime
import ipaddress
import os
import tempfile
from pathlib import Path

import uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from ssh_mcp.config import Config
from ssh_mcp.server import create_http_app


async def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=1))
                .not_valid_after(now + datetime.timedelta(hours=1))
                .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
                .sign(key, hashes.SHA256()))
        (root / "cert.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        (root / "key.pem").write_bytes(key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        os.environ["SSH_MCP_ADMIN_TOKEN"] = "browser-fixture-only-not-a-real-secret-" + "x" * 32
        os.environ.pop("SSH_MCP_TOKEN", None)
        app = create_http_app(Config(servers=(), auth_mode="oauth", public_url="https://127.0.0.1:18766"), root / "inventory.sqlite3")
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=18766,
            ssl_certfile=str(root / "cert.pem"), ssl_keyfile=str(root / "key.pem"), log_level="error", access_log=False))
        task = asyncio.create_task(server.serve())
        while not server.started:
            if task.done():
                await task
                raise RuntimeError("预览服务启动失败")
            await asyncio.sleep(0.02)
        print("ready", flush=True)
        await task


if __name__ == "__main__":
    asyncio.run(main())
