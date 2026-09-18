"""宿主机 ERP 转发：监听 0.0.0.0:13306 → 172.20.0.114:3306。

Docker Desktop 的 NAT 在宿主机 WLAN 地址变化后会失效，容器无法直连内网 ERP；
本进程在宿主机上做 TCP 转发，容器经 host.docker.internal:13306 访问 ERP。
用法：python scripts/erp_port_forward.py
"""
from __future__ import annotations

import asyncio
import logging
import os

LISTEN_HOST = os.getenv("ERP_FORWARD_LISTEN_HOST", "0.0.0.0")
LISTEN_PORT = int(os.getenv("ERP_FORWARD_LISTEN_PORT", "13306"))
TARGET_HOST = os.getenv("ERP_FORWARD_TARGET_HOST", "172.20.0.114")
TARGET_PORT = int(os.getenv("ERP_FORWARD_TARGET_PORT", "3306"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("erp-forward")


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while chunk := await reader.read(65536):
            writer.write(chunk)
            await writer.drain()
    except (ConnectionResetError, BrokenPipeError, asyncio.IncompleteReadError):
        pass
    finally:
        writer.close()


async def _handle(client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter) -> None:
    peer = client_writer.get_extra_info("peername")
    try:
        target_reader, target_writer = await asyncio.open_connection(TARGET_HOST, TARGET_PORT)
    except OSError as exc:
        logger.warning("ERP 连接失败 %s -> %s:%s (%s)", peer, TARGET_HOST, TARGET_PORT, exc)
        client_writer.close()
        return
    logger.info("转发 %s -> %s:%s", peer, TARGET_HOST, TARGET_PORT)
    await asyncio.gather(
        _pipe(client_reader, target_writer),
        _pipe(target_reader, client_writer),
        return_exceptions=True,
    )


async def main() -> None:
    server = await asyncio.start_server(_handle, LISTEN_HOST, LISTEN_PORT)
    logger.info("ERP 转发已启动: %s:%s -> %s:%s", LISTEN_HOST, LISTEN_PORT, TARGET_HOST, TARGET_PORT)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
