"""Tenant-local transport to the fixed host public-only egress proxy.

This stdlib-only file is also installed as a root-owned standalone script in
the managed workload. It runs through native sandbox exec, in that workload's
network namespace, and never chooses a destination from browser input.
"""

import argparse
import asyncio
import os
import socket
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path


async def relay(reader, writer, port, supervisor_host="10.200.0.1", supervisor_port=3128):
    upstream = None
    tasks = []
    try:
        async with asyncio.timeout(10):
            remote, upstream = await asyncio.open_connection(supervisor_host, supervisor_port)
            upstream.write(
                f"CONNECT host.openshell.internal:{port} HTTP/1.1\r\n"
                f"Host: host.openshell.internal:{port}\r\n\r\n".encode()
            )
            await upstream.drain()
            response = await remote.readuntil(b"\r\n\r\n")
            if response.split(b"\r\n", 1)[0].split()[1:2] != [b"200"]:
                return

        async def pipe(source, destination):
            while data := await source.read(65536):
                destination.write(data)
                await destination.drain()

        tasks = [asyncio.create_task(pipe(reader, upstream)),
                 asyncio.create_task(pipe(remote, writer))]
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    except (OSError, TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
        pass
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for connection in (writer, upstream):
            if connection is not None:
                connection.close()
                with suppress(OSError):
                    await connection.wait_closed()


async def serve(port):
    server = await asyncio.start_server(lambda r, w: relay(r, w, port), "127.0.0.1", port)
    async with server:
        await server.serve_forever()


def ready(port):
    """Prove the bridge reaches the public proxy's private-address rejection."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2) as client:
            client.sendall(b"CONNECT 127.0.0.1:80 HTTP/1.1\r\nHost: 127.0.0.1:80\r\n\r\n")
            return client.recv(4096).startswith(b"HTTP/1.1 403 ")
    except OSError:
        return False


def ensure(port):
    root = Path("/sandbox/.openclaw/runtime")
    root.mkdir(mode=0o700, exist_ok=True)
    if root.is_symlink() or root.stat().st_uid != os.getuid():
        raise RuntimeError("Unsafe browser bridge state directory")
    pidfile = root / "browser-egress.pid"
    if pidfile.is_symlink():
        raise RuntimeError("Unsafe browser bridge process record")
    arguments = [str(Path(__file__).resolve()), "--serve", "--port", str(port)]
    if pidfile.is_file():
        try:
            pid = int(pidfile.read_text())
            process = Path("/proc") / str(pid)
            command = process.joinpath("cmdline").read_bytes().split(b"\0")
            actual = [item.decode() for item in command if item]
            if (process.stat().st_uid == os.getuid() and actual[1:] == arguments
                    and os.path.samefile(process / "ns/net", "/proc/self/ns/net")):
                if not ready(port):
                    raise RuntimeError("Browser bridge cannot reach public egress")
                return
        except (ValueError, OSError):
            pass
    log = os.open(root / "browser-egress.log", os.O_WRONLY | os.O_CREAT | os.O_APPEND
                  | os.O_NOFOLLOW, 0o600)
    try:
        process = subprocess.Popen(
            [sys.executable, *arguments], stdin=subprocess.DEVNULL,
            stdout=log, stderr=log, close_fds=True, start_new_session=True,
        )
    finally:
        os.close(log)
    for _ in range(20):
        if process.poll() is not None:
            raise RuntimeError("Browser bridge could not start")
        if ready(port):
            descriptor = os.open(pidfile, os.O_WRONLY | os.O_CREAT | os.O_TRUNC
                                 | os.O_NOFOLLOW, 0o600)
            with os.fdopen(descriptor, "w") as output:
                output.write(str(process.pid))
            return
        time.sleep(0.25)
    process.terminate()
    process.wait(timeout=5)
    raise RuntimeError("Browser bridge readiness timed out")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--serve", action="store_true")
    mode.add_argument("--ensure", action="store_true")
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Invalid browser bridge port")
    if args.serve:
        asyncio.run(serve(args.port))
    else:
        ensure(args.port)
        print("BROWSER_EGRESS_READY")


if __name__ == "__main__":
    main()
