"""java_runner classpath 解析与依赖拷贝行为测试.

覆盖两个已确认缺陷：
1. dependency:build-classpath 60s 超时后静默回退字母序 classpath（类冲突风险）
2. copy-dependencies 不清空 target/lib，残留旧 jar 造成类冲突
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from java_service_starter.java_runner import (
    _copy_dependencies,
    _resolve_maven_classpath,
    build_classpath_dev,
)
from java_service_starter.models import JavaConfig, MavenConfig

JAVA = JavaConfig(path=None, version=None)


def _make_project(tmp_path: Path) -> Path:
    """创建最小项目结构: <root>/svc/target."""
    module_dir = tmp_path / "svc"
    (module_dir / "target").mkdir(parents=True)
    return tmp_path


def _fake_maven(tmp_path: Path) -> MavenConfig:
    """创建指向假 mvn 脚本的 MavenConfig."""
    mvn = tmp_path / "mvn"
    mvn.write_text("#!/bin/sh\n")
    return MavenConfig(path=str(mvn), settings=None, skip_tests=True)


# ---------------------------------------------------------------- 缺陷 1: classpath 解析


def test_resolve_maven_classpath_allows_long_builds(tmp_path: Path, monkeypatch) -> None:
    """大型多模块项目 build-classpath 可能超过 60s，超时应放宽到 300s."""
    root = _make_project(tmp_path)
    maven = _fake_maven(tmp_path)
    cp_file = root / "svc" / "target" / ".maven-classpath.txt"
    cp_file.write_text("/repo/a.jar:/repo/b.jar\n")

    captured: dict = {}

    def fake_run(_cmd, **_kwargs):
        captured.update(_kwargs)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    cp = _resolve_maven_classpath(root, "svc", maven, JAVA)

    assert cp == "/repo/a.jar:/repo/b.jar"
    assert captured["timeout"] >= 300


def test_resolve_maven_classpath_timeout_raises_instead_of_silent_none(
    tmp_path: Path, monkeypatch
) -> None:
    """超时后必须报错，不能静默返回 None 让调用方回退字母序."""
    root = _make_project(tmp_path)
    maven = _fake_maven(tmp_path)

    def fake_run(_cmd, **_kwargs):
        raise subprocess.TimeoutExpired(_cmd, _kwargs.get("timeout", 60))

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="classpath"):
        _resolve_maven_classpath(root, "svc", maven, JAVA)


def test_build_classpath_dev_never_falls_back_to_alphabetical_when_maven_fails(
    tmp_path: Path, monkeypatch
) -> None:
    """Maven classpath 解析失败时必须中止，而不是静默使用字母序（类冲突风险）."""
    root = _make_project(tmp_path)
    maven = _fake_maven(tmp_path)
    (root / "svc" / "target" / "classes").mkdir()
    lib = root / "svc" / "target" / "lib"
    lib.mkdir()
    (lib / "b.jar").write_text("")
    (lib / "a.jar").write_text("")

    def fake_run(_cmd, **_kwargs):
        raise subprocess.TimeoutExpired(_cmd, _kwargs.get("timeout", 60))

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(RuntimeError):
        build_classpath_dev(root, "svc", maven, JAVA)


def test_build_classpath_dev_alphabetical_only_without_maven_config(tmp_path: Path) -> None:
    """未配置 Maven 时保留字母序回退（无顺序信息来源），防止回归."""
    root = _make_project(tmp_path)
    (root / "svc" / "target" / "classes").mkdir()
    lib = root / "svc" / "target" / "lib"
    lib.mkdir()
    (lib / "b.jar").write_text("")
    (lib / "a.jar").write_text("")

    cp = build_classpath_dev(root, "svc", None, JAVA)

    jars = [Path(p).name for p in cp.split(":") if p.endswith(".jar")]
    assert jars == ["a.jar", "b.jar"]


# ---------------------------------------------------------------- 缺陷 3: copy 不清空 lib


def test_copy_dependencies_clears_stale_jars(tmp_path: Path, monkeypatch) -> None:
    """copy-dependencies 不会清理 outputDirectory，拷贝前必须清空 target/lib 旧 jar."""
    root = _make_project(tmp_path)
    maven = _fake_maven(tmp_path)
    lib = root / "svc" / "target" / "lib"
    lib.mkdir()
    stale = lib / "stale-old-1.0.jar"
    stale.write_text("stale")

    calls: list[list[str]] = []

    def fake_run(_cmd, **_kwargs):
        calls.append([str(c) for c in _cmd])
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    _copy_dependencies(root, "svc", maven, JAVA)

    assert not stale.exists(), "旧 jar 必须在拷贝前清空"
    assert any("copy-dependencies" in " ".join(c) for c in calls)


def test_copy_dependencies_without_existing_lib(tmp_path: Path, monkeypatch) -> None:
    """target/lib 不存在时直接拷贝，不报错（防止回归）."""
    root = _make_project(tmp_path)
    maven = _fake_maven(tmp_path)

    def fake_run(_cmd, **_kwargs):
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    _copy_dependencies(root, "svc", maven, JAVA)
