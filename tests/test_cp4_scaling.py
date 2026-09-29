"""Regression test for the multi-instance Compose topology used in CP4."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
import uuid

import httpx
import pytest


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.mark.docker
def test_compose_can_scale_three_agents_behind_gateway(repo_root):
    """Three agent replicas must start without competing for one host port."""
    if shutil.which("docker") is None:
        pytest.skip("Docker CLI is not installed")

    project = f"day12-cp4-{uuid.uuid4().hex[:8]}"
    agent_port = _free_port()
    redis_port = _free_port()
    env = os.environ.copy()
    env.update(
        {
            "AGENT_API_KEY": "cp4-scaling-test-key",
            "AGENT_PORT": str(agent_port),
            "REDIS_PORT": str(redis_port),
        }
    )
    base = ["docker", "compose", "-p", project]

    try:
        started = subprocess.run(
            [*base, "up", "-d", "--build", "--scale", "agent=3"],
            cwd=repo_root,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert started.returncode == 0, started.stdout + started.stderr

        ids = subprocess.run(
            [*base, "ps", "-q", "agent"],
            cwd=repo_root,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()
        assert len(ids) == 3

        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                response = httpx.get(f"http://127.0.0.1:{agent_port}/health", timeout=2)
                if response.status_code == 200:
                    assert response.json()["status"] == "ok"
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        else:
            pytest.fail("Compose gateway did not become healthy within 30 seconds")
    finally:
        subprocess.run(
            [*base, "down", "--volumes", "--remove-orphans"],
            cwd=repo_root,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
