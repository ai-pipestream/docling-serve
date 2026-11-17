"""The e2e gRPC harness starts its own server and reports startup failures."""

from __future__ import annotations

import sys
import time

import pytest

from tests.e2e_grpc_harness import (
    GrpcE2EServerError,
    e2e_grpc_target_scope,
    port_accepts_bind,
    subprocess_env,
)


def _port_of(target: str) -> int:
    return int(target.rsplit(":", 1)[1])


def test_e2e_grpc_target_scope_starts_health_and_releases_port(monkeypatch):
    """Unset target: a real Health RPC succeeds, then the port is free.

    A leaked ``DOCLING_SERVE_ARTIFACTS_PATH`` in the live environment must
    not be what the server uses. That is the full-suite failure mode.
    """
    monkeypatch.delenv("DOCLING_E2E_GRPC_TARGET", raising=False)
    monkeypatch.setenv(
        "DOCLING_SERVE_ARTIFACTS_PATH",
        "/tmp/not-a-docling-artifacts-dir",
    )
    port = None
    with e2e_grpc_target_scope() as target:
        port = _port_of(target)
        assert target.startswith("127.0.0.1:")
        assert port_accepts_bind(port) is False
    assert port is not None
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not port_accepts_bind(port):
        time.sleep(0.1)
    assert port_accepts_bind(port)


def test_subprocess_env_ignores_artifacts_path_set_during_the_suite(monkeypatch):
    leaked = "/tmp/not-a-docling-artifacts-dir"
    monkeypatch.setenv("DOCLING_SERVE_ARTIFACTS_PATH", leaked)
    assert subprocess_env().get("DOCLING_SERVE_ARTIFACTS_PATH") != leaked


def test_unreachable_explicit_grpc_target_raises_clear_error(monkeypatch):
    """An explicit dead target fails naming that target, not a bare RPC error."""
    monkeypatch.setenv("DOCLING_E2E_GRPC_TARGET", "127.0.0.1:1")
    with pytest.raises(GrpcE2EServerError) as excinfo:
        with e2e_grpc_target_scope(ready_timeout=2):
            pass
    message = str(excinfo.value)
    assert message.startswith(
        "DOCLING_E2E_GRPC_TARGET=127.0.0.1:1 did not become ready"
    )
    assert "InactiveRpcError" not in message


def test_grpc_subprocess_exit_includes_stderr(monkeypatch):
    """A process that dies before Health reports its stderr."""
    monkeypatch.delenv("DOCLING_E2E_GRPC_TARGET", raising=False)

    def exit_immediately(port: int) -> list[str]:
        del port
        script = (
            "import sys; sys.stderr.write('boom-from-stderr\\n'); "
            "sys.stderr.flush(); raise SystemExit(3)"
        )
        return [sys.executable, "-c", script]

    monkeypatch.setattr(
        "tests.e2e_grpc_harness.grpc_serve_command",
        exit_immediately,
    )
    with pytest.raises(GrpcE2EServerError) as excinfo:
        with e2e_grpc_target_scope(ready_timeout=5):
            pass
    message = str(excinfo.value)
    assert "exited with code 3" in message
    assert "boom-from-stderr" in message
    assert "server stderr:" in message
    assert "InactiveRpcError" not in message
