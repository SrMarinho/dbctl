"""Unit tests for dbctl.docker: the ONLY process-spawning module."""

from __future__ import annotations

import subprocess

import pytest

from dbctl.docker import _execute, compose, container_running, exec_in, run
from dbctl.errors import DockerError


def test_execute_dry_run_prints_and_returns_empty(monkeypatch, capsys) -> None:
    monkeypatch.setenv("DBCTL_DRY_RUN", "1")
    out = _execute(["docker", "ps"], input=None, capture=True, env=None, cwd=None)
    assert out == ""
    captured = capsys.readouterr()
    assert "dry-run: docker ps" in captured.out


def test_execute_success(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):  # noqa: ANN001, ANN202
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="hello\n", stderr="")

    monkeypatch.setattr("dbctl.docker.subprocess.run", fake_run)
    out = _execute(["echo", "hi"], input=None, capture=True, env=None, cwd=None)
    assert out == "hello"
    assert calls == [["echo", "hi"]]


def test_execute_failure_raises_docker_error(monkeypatch) -> None:
    def fake_run(cmd, **kwargs):  # noqa: ANN001, ANN202
        return subprocess.CompletedProcess(cmd, 2, stdout="", stderr="boom")

    monkeypatch.setattr("dbctl.docker.subprocess.run", fake_run)
    with pytest.raises(DockerError, match="exit 2"):
        _execute(["false"], input=None, capture=True, env=None, cwd=None)


def test_execute_binary_missing(monkeypatch) -> None:
    def fake_run(cmd, **kwargs):  # noqa: ANN001, ANN202
        raise FileNotFoundError

    monkeypatch.setattr("dbctl.docker.subprocess.run", fake_run)
    with pytest.raises(DockerError, match="binary not found"):
        _execute(["nope"], input=None, capture=True, env=None, cwd=None)


def test_execute_forwards_env_and_cwd(monkeypatch) -> None:
    seen: dict = {}

    def fake_run(cmd, **kwargs):  # noqa: ANN001, ANN202
        seen.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("dbctl.docker.subprocess.run", fake_run)
    _execute(["x"], input="stdin-data", capture=False, env={"K": "v"}, cwd="/tmp")
    assert seen["input"] == "stdin-data"
    assert seen["cwd"] == "/tmp"
    assert seen["env"]["K"] == "v"


def test_exec_in_builds_docker_exec_with_env(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_execute(cmd, **kwargs):  # noqa: ANN001, ANN202
        calls.append(cmd)
        return ""

    monkeypatch.setattr("dbctl.docker._execute", fake_execute)
    exec_in("pg", ["psql", "-c", "x"], env={"PGPASSWORD": "secret"}, capture=True)
    assert calls == [["docker", "exec", "-e", "PGPASSWORD=secret", "pg", "psql", "-c", "x"]]


def test_exec_in_with_stdin_adds_i_flag(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_execute(cmd, **kwargs):  # noqa: ANN001, ANN202
        calls.append(cmd)
        return ""

    monkeypatch.setattr("dbctl.docker._execute", fake_execute)
    exec_in("web", ["odoo", "shell"], input="code")
    assert "-i" in calls[0]


def test_compose_builds_flags_and_cwd(monkeypatch) -> None:
    calls: list[list[str]] = []
    cwds: list[str | None] = []

    def fake_execute(cmd, **kwargs):  # noqa: ANN001, ANN202
        calls.append(cmd)
        cwds.append(kwargs.get("cwd"))
        return ""

    monkeypatch.setattr("dbctl.docker._execute", fake_execute)
    from pathlib import Path

    compose(Path("/proj"), ["docker-compose.yml", "override.yaml"], ["up", "-d"])
    assert calls == [
        ["docker", "compose", "-f", "docker-compose.yml", "-f", "override.yaml", "up", "-d"]
    ]
    assert cwds == ["/proj"]


def test_run_forwards(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_execute(cmd, **kwargs):  # noqa: ANN001, ANN202
        calls.append(cmd)
        return "out"

    monkeypatch.setattr("dbctl.docker._execute", fake_execute)
    assert run(["git", "status"], capture=True) == "out"
    assert calls == [["git", "status"]]


def test_container_running_true_when_inspect_says_true(monkeypatch) -> None:
    monkeypatch.setattr("dbctl.docker.run", lambda *a, **k: "true")
    assert container_running("pg") is True


def test_container_running_false_on_error(monkeypatch) -> None:
    def boom(*a, **k):  # noqa: ANN001, ANN202
        raise DockerError("nope")

    monkeypatch.setattr("dbctl.docker.run", boom)
    assert container_running("pg") is False
