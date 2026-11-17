"""Start docling-serve-grpc for the end-to-end client tests.

When ``DOCLING_E2E_GRPC_TARGET`` is set, that address is used and probed.
When it is unset, a subprocess runs ``python -m docling_serve.grpc`` on a
free port. Readiness is a successful Health RPC. A failure raises
``GrpcE2EServerError`` with the target and, for a process we started, its
stderr. Callers never see a bare connection error.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import NoReturn

import grpc

from docling_serve.grpc.gen.ai.docling.serve.v1 import (
    docling_serve_pb2 as serve_pb2,
    docling_serve_pb2_grpc as serve_pb2_grpc,
)

# Captured at import, which is before tests mutate os.environ. The server
# subprocess must not inherit DOCLING_SERVE_ARTIFACTS_PATH written by another
# test (that path is a tmp dir and model warmup then exits).
_LAUNCH_ENV = dict(os.environ)

DEFAULT_READY_TIMEOUT_S = 180.0
_STDERR_TAIL = 16_000
_HEALTH_ATTEMPT_S = 1.0
_POLL_SLEEP_S = 0.25


class GrpcE2EServerError(RuntimeError):
    """The e2e gRPC server did not become ready, or exited."""


def subprocess_env() -> dict[str, str]:
    """Environment pytest was launched with, not the live ``os.environ``."""
    return dict(_LAUNCH_ENV)


def grpc_call_metadata() -> list[tuple[str, str]]:
    """Metadata for Health and Convert when an API key is configured."""
    api_key = os.environ.get("DOCLING_SERVE_API_KEY", "")
    if not api_key:
        return []
    return [("x-api-key", api_key)]


def grpc_serve_command(port: int) -> list[str]:
    """Command that serves gRPC on 127.0.0.1 and this port."""
    return [
        sys.executable,
        "-m",
        "docling_serve.grpc",
        "run",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]


def reserve_port() -> int:
    """Return an ephemeral TCP port on 127.0.0.1."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def port_accepts_bind(port: int) -> bool:
    """True when nothing is listening on 127.0.0.1:port."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", port))
    except OSError:
        return False
    else:
        return True
    finally:
        sock.close()


class ManagedGrpcServer:
    """A docling-serve-grpc subprocess and the log it writes."""

    def __init__(self, proc: subprocess.Popen[bytes], target: str, log_path: Path):
        self.proc = proc
        self.target = target
        self.log_path = log_path

    @classmethod
    def start(cls, port: int | None = None) -> ManagedGrpcServer:
        chosen = reserve_port() if port is None else port
        log = tempfile.NamedTemporaryFile(
            prefix="docling-e2e-grpc-",
            suffix=".log",
            delete=False,
        )
        log_path = Path(log.name)
        proc = subprocess.Popen(
            grpc_serve_command(chosen),
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=subprocess_env(),
        )
        log.close()
        return cls(proc, f"127.0.0.1:{chosen}", log_path)

    def poll(self) -> int | None:
        return self.proc.poll()

    def stderr_text(self) -> str:
        try:
            text = self.log_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return f"<could not read server log: {exc}>"
        if len(text) > _STDERR_TAIL:
            return text[-_STDERR_TAIL:]
        return text

    def stop(self) -> None:
        if self.proc.poll() is None:
            _terminate_process_group(self.proc)
        self.log_path.unlink(missing_ok=True)


def wait_until_healthy(
    target: str,
    timeout_s: float,
    server: ManagedGrpcServer | None = None,
) -> serve_pb2.HealthResponse:
    """Call Health until status is ok, or raise ``GrpcE2EServerError``."""
    deadline = time.monotonic() + timeout_s
    last_error = "no health response"
    while time.monotonic() < deadline:
        if server is not None and server.poll() is not None:
            raise GrpcE2EServerError(_exited_message(server))
        try:
            return call_health(target, timeout=_HEALTH_ATTEMPT_S)
        except grpc.RpcError as exc:
            code = exc.code()
            name = code.name if code is not None else "UNKNOWN"
            last_error = f"{name}: {exc.details() or ''}".rstrip()
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        time.sleep(_POLL_SLEEP_S)
    if server is not None and server.poll() is not None:
        raise GrpcE2EServerError(_exited_message(server))
    return _raise_not_ready(target, timeout_s, last_error, server)


def call_health(target: str, timeout: float) -> serve_pb2.HealthResponse:
    """One Health RPC. Raises ``grpc.RpcError`` when the peer is down."""
    channel = grpc.insecure_channel(target)
    try:
        grpc.channel_ready_future(channel).result(timeout=timeout)
        stub = serve_pb2_grpc.DoclingServeServiceStub(channel)
        response = stub.Health(
            serve_pb2.HealthRequest(),
            timeout=timeout,
            metadata=grpc_call_metadata(),
        )
    finally:
        channel.close()
    if response.status != "ok":
        raise RuntimeError(f"Health status={response.status!r}")
    return response


@contextmanager
def e2e_grpc_target_scope(
    ready_timeout: float | None = None,
) -> Iterator[str]:
    """Yield a ready ``host:port``. Stop a server this scope started."""
    timeout_s = DEFAULT_READY_TIMEOUT_S if ready_timeout is None else ready_timeout
    explicit = os.environ.get("DOCLING_E2E_GRPC_TARGET", "").strip()
    if explicit:
        wait_until_healthy(explicit, timeout_s)
        yield explicit
        return

    server = ManagedGrpcServer.start()
    try:
        wait_until_healthy(server.target, timeout_s, server)
        yield server.target
    finally:
        server.stop()


def _exited_message(server: ManagedGrpcServer) -> str:
    code = server.proc.returncode
    stderr = server.stderr_text().strip() or "<empty>"
    return (
        f"docling-serve-grpc on {server.target} exited with code {code} "
        f"before it was ready.\nserver stderr:\n{stderr}"
    )


def _raise_not_ready(
    target: str,
    timeout_s: float,
    last_error: str,
    server: ManagedGrpcServer | None,
) -> NoReturn:
    if server is None:
        prefix = f"DOCLING_E2E_GRPC_TARGET={target}"
        stderr = ""
    else:
        prefix = f"docling-serve-grpc on {target}"
        body = server.stderr_text().strip() or "<empty>"
        stderr = f"\nserver stderr:\n{body}"
    raise GrpcE2EServerError(
        f"{prefix} did not become ready within {timeout_s:.0f}s ({last_error}).{stderr}"
    )


def _terminate_process_group(proc: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        proc.wait(timeout=10)
