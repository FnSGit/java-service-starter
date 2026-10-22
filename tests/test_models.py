"""JavaConfig / MavenConfig 路径解析测试.

覆盖缺陷：配置中的 ~ 路径不被展开，导致静默回退到 PATH 上的
错误 JDK（uccb-epm 项目配置 ~/.jdks/ms-17.0.20.1 实际用了 Java 25，
maven-compiler-plugin:3.8.0 不兼容 javac 25，构建失败）。
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from java_service_starter.models import JavaConfig, MavenConfig


def _fake_java(tmp_path: Path) -> Path:
    java_bin = tmp_path / "bin" / "java"
    java_bin.parent.mkdir(parents=True)
    java_bin.write_text("#!/bin/sh\n")
    return java_bin


# ------------------------------------------------------------------ ~ 展开


def test_resolve_java_bin_expands_tilde(tmp_path: Path, monkeypatch) -> None:
    """java.path 中的 ~ 必须展开为用户主目录."""
    monkeypatch.setenv("HOME", str(tmp_path))
    java_bin = _fake_java(tmp_path)

    config = JavaConfig(path="~/bin/java", version=17)

    assert config.resolve_java_bin() == java_bin


def test_resolve_java_home_expands_tilde(tmp_path: Path, monkeypatch) -> None:
    """resolve_java_home 同样需要展开 ~，否则 Maven 编译用错 JDK."""
    monkeypatch.setenv("HOME", str(tmp_path))
    _fake_java(tmp_path)

    config = JavaConfig(path="~/bin/java", version=17)

    assert config.resolve_java_home() == tmp_path


def test_resolve_mvn_bin_expands_tilde(tmp_path: Path, monkeypatch) -> None:
    """maven.path 中的 ~ 必须展开."""
    monkeypatch.setenv("HOME", str(tmp_path))
    mvn = tmp_path / "bin" / "mvn"
    mvn.parent.mkdir(parents=True)
    mvn.write_text("#!/bin/sh\n")

    config = MavenConfig(path="~/bin/mvn", settings=None)

    assert config.resolve_mvn_bin() == mvn


# ------------------------------------------------------------------ 禁止静默回退


def test_resolve_java_bin_raises_on_invalid_path() -> None:
    """配置了 java.path 但路径不存在时必须报错.

    静默回退 PATH 中的 java 会导致用错 JDK 版本构建，
    产生难以定位的编译失败（如 javac TypeTag::UNKNOWN）。
    """
    config = JavaConfig(path="/nonexistent/jdk/bin/java", version=17)

    with pytest.raises(RuntimeError, match="java.path"):
        config.resolve_java_bin()


def test_resolve_java_home_raises_on_invalid_path() -> None:
    """java.path 无效时 resolve_java_home 也不能静默回退环境变量."""
    config = JavaConfig(path="/nonexistent/jdk/bin/java", version=17)

    with pytest.raises(RuntimeError, match="java.path"):
        config.resolve_java_home()


def test_resolve_mvn_bin_raises_on_invalid_path() -> None:
    """配置了 maven.path 但路径不存在时必须报错，不能静默回退."""
    config = MavenConfig(path="/nonexistent/mvn", settings=None)

    with pytest.raises(RuntimeError, match="maven.path"):
        config.resolve_mvn_bin()


# ------------------------------------------------------------------ 既有行为保持


def test_resolve_java_bin_falls_back_to_path_java_when_unset() -> None:
    """未配置 path 时回退 PATH 中的 java（既有行为，防止回归）."""
    config = JavaConfig(path=None, version=None)

    java = shutil.which("java")
    assert java is not None
    assert config.resolve_java_bin() == Path(java)


def test_resolve_java_home_returns_none_when_unset(monkeypatch) -> None:
    """未配置 path 且无 JAVA_HOME 时返回 None（既有行为，防止回归）."""
    monkeypatch.delenv("JAVA_HOME", raising=False)
    config = JavaConfig(path=None, version=None)

    assert config.resolve_java_home() is None
