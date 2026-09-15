"""User-space TCP relay for Docker Desktop to reach an intranet ERP endpoint.

The Windows host owns the intranet route while Docker Desktop runs inside a
separate Linux VM. Bind the relay on the host, then point containers at
host.docker.internal:<listen-port>.
"""

from __future__ import annotations

import argparse
import asyncio
import logging


async def bridge(reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
                 target_host: str, target_port: int) -> None:
    peer = writer.get_extra_info("peername")
    try:
        remote_reader, remote_writer = await asyncio.open_connection(target_host, target_port)

        async def copy(source: asyncio.StreamReader, destination: asyncio.StreamWriter) -> None:
            try:
                while chunk := await source.read(64 * 1024):
                    destination.write(chunk)
                    await destination.drain()
            finally:
                destination.close()

        await asyncio.gather(copy(reader, remote_writer), copy(remote_reader, writer))
    except OSError as exc:
        logging.warning("ERP relay connection failed for %s: %s", peer, exc)
    finally:
        writer.close()
        await writer.wait_closed()


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--listen-host", default="0.0.0.0")
    parser.add_argument("--listen-port", type=int, default=13306)
    parser.add_argument("--target-host", default="172.20.0.114")
    parser.add_argument("--target-port", type=int, default=3306)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    server = await asyncio.start_server(
        lambda r, w: bridge(r, w, args.target_host, args.target_port),
        args.listen_host,
        args.listen_port,
    )
    sockets = ", ".join(str(sock.getsockname()) for sock in server.sockets or [])
    logging.info("ERP relay listening on %s -> %s:%s", sockets, args.target_host, args.target_port)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
