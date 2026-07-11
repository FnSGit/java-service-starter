"""Maven 编译管理模块."""

import os
import subprocess
import time
from pathlib import Path

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from .models import JavaConfig, MavenConfig
from .state import StateManager

console = Console()


def _build_env(java_config: JavaConfig | None = None) -> dict[str, str]:
    """构建 Maven 编译的环境变量."""
    env = os.environ.copy()

    if java_config:
        java_home = java_config.resolve_java_home()
        if java_home:
            env["JAVA_HOME"] = str(java_home)
            java_bin_dir = str(java_home / "bin")
            env["PATH"] = f"{java_bin_dir}:{env.get('PATH', '')}"

    return env


def resolve_mvn_invocation(project_root: Path, module: str) -> tuple[Path, list[str]]:
    """根据项目结构决定 Maven 调用的 cwd 与 reactor 参数.

    返回 (cwd, pl_args)：
    - 多模块项目（根目录有 pom.xml 且 module 不为 "."）：cwd=root, pl_args=["-pl", module, "-am"]
    - 单项目或并列项目（根无聚合 pom，或 module="."）：cwd=root/module, pl_args=[]

    判定依据是根目录是否存在 pom.xml，避免对 reactor 内模块以外的项目使用 -pl 失败。
    """
    if module in (".", ""):
        return project_root, []

    if (project_root / "pom.xml").exists():
        return project_root, ["-pl", module, "-am"]

    return project_root / module, []


def compile_module(
    project_root: Path,
    maven: MavenConfig,
    module: str,
    state: StateManager | None = None,
    java_config: JavaConfig | None = None,
    goal: str = "compile",
) -> None:
    """执行 Maven 编译，实时显示输出.

    Args:
        project_root: 项目根目录.
        maven: Maven 配置.
        module: 目标模块路径.
        state: 状态管理器.
        java_config: Java 配置.
        goal: Maven 目标，默认 compile。clear 后重建用 package.

    Raises:
        RuntimeError: 编译失败.
    """
    mvn_bin = maven.resolve_mvn_bin()
    cwd, pl_args = resolve_mvn_invocation(project_root, module)
    args = maven.build_compile_args(module, goal=goal)
    # reactor 参数置于 goal 之后，settings/skipTests 之前
    cmd = [str(mvn_bin), args[0], *pl_args, *args[1:]]
    env = _build_env(java_config)

    console.print(Panel.fit(
        f"[bold]编译命令[/bold]\n{' '.join(cmd)}\n[dim]cwd: {cwd}[/dim]",
        style="blue",
    ))

    start_time = time.time()

    # 实时输出 Maven 编译日志
    result = subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        text=True,
    )

    duration = time.time() - start_time

    if result.returncode != 0:
        console.print(f"\n[bold red]编译失败 ({duration:.1f}s)[/bold red]")
        console.print(f"[red]退出码: {result.returncode}[/red]")
        raise RuntimeError(f"Maven 编译失败 (exit code: {result.returncode})")

    console.print(f"\n[bold green]编译成功 ({duration:.1f}s)[/bold green]")
    if state:
        state.record_compile(module, success=True, duration=duration)


def auto_compile(
    project_root: Path,
    maven: MavenConfig,
    module: str,
    modules_to_compile: list[str],
    state: StateManager | None = None,
    java_config: JavaConfig | None = None,
) -> None:
    """智能编译：按需编译指定模块."""
    if not modules_to_compile:
        console.print("[dim]所有模块均为最新，跳过编译[/dim]")
        return

    console.print(
        f"[yellow]检测到 {len(modules_to_compile)} 个模块需要编译:[/yellow]"
    )
    for mod in modules_to_compile:
        console.print(f"  - {mod}")

    compile_module(project_root, maven, module, state, java_config)