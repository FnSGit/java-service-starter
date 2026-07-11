"""Java 进程管理模块."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from .models import JavaConfig, MavenConfig, ProjectConfig, ServiceConfig
from .state import StateManager

console = Console()


def find_pid(port: int) -> int | None:
    """查找占用指定端口的 Java 进程 PID.

    检测策略（按优先级）：
    1. ss/netstat 检查端口是否在监听 → 再通过 lsof/fuser 获取 PID
    2. ps + grep 匹配 server.port 参数
    """
    # 先确认端口是否在监听
    if not _port_listening(port):
        return None

    # 通过 lsof 获取 PID
    try:
        result = subprocess.run(
            ["lsof", "-ti", f"tcp:{port}"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            return int(result.stdout.strip().splitlines()[0])
    except FileNotFoundError:
        pass

    # 通过 fuser 获取 PID
    try:
        result = subprocess.run(
            ["fuser", f"{port}/tcp"],
            capture_output=True,
            text=True,
        )
        if result.stdout.strip():
            return int(result.stdout.strip().split()[0])
    except FileNotFoundError:
        pass

    # 通过 ps + grep 匹配
    try:
        result = subprocess.run(
            ["ps", "-ef"],
            capture_output=True,
            text=True,
        )
        for line in result.stdout.splitlines():
            if "java" in line and f"server.port={port}" in line:
                parts = line.split()
                if len(parts) >= 2:
                    return int(parts[1])
    except Exception:
        pass

    # 端口在监听但无法获取 PID，返回 -1 表示"运行中（PID未知）"
    return -1


def _port_listening(port: int) -> bool:
    """检查端口是否在监听."""
    for cmd in [
        ["ss", "-tuln"],
        ["netstat", "-tuln"],
    ]:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0 and f":{port}" in result.stdout:
                # 精确匹配端口号（避免 10023 匹配到 100230）
                for line in result.stdout.splitlines():
                    # ss 格式: LISTEN  0  128  *:10023  *:*
                    # netstat 格式: tcp  0  0  0.0.0.0:10023  0.0.0.0:*  LISTEN
                    if f":{port} " in line or f":{port}\t" in line or line.rstrip().endswith(f":{port}"):
                        return True
        except FileNotFoundError:
            continue
    return False


def is_running(port: int) -> bool:
    """检查服务是否在运行."""
    return find_pid(port) is not None


def find_java_processes(port: int) -> list[tuple[int, float]]:
    """查找匹配 server.port 参数的 Java 进程.

    Returns:
        [(pid, elapsed_seconds)] — 进程存活时间从 /proc 计算.
    """
    import os

    processes: list[tuple[int, float]] = []
    try:
        result = subprocess.run(
            ["ps", "-eo", "pid,etime,args"],
            capture_output=True,
            text=True,
        )
        for line in result.stdout.splitlines():
            if "java" in line and f"server.port={port}" in line:
                parts = line.split(None, 2)
                if len(parts) >= 2:
                    pid = int(parts[0])
                    etime_str = parts[1]
                    elapsed = _parse_etime(etime_str)
                    processes.append((pid, elapsed))
    except Exception:
        pass

    return processes


def _parse_etime(etime_str: str) -> float:
    """解析 ps etime 格式为秒数.

    格式示例: '1:23' (1分23秒), '1:23:45' (1时23分45秒), '2-3:04:05' (2天3时4分5秒).
    """
    try:
        if "-" in etime_str:
            # 天-时:分:秒
            day_part, time_part = etime_str.split("-", 1)
            days = int(day_part)
            time_parts = time_part.split(":")
            if len(time_parts) == 3:
                h, m, s = int(time_parts[0]), int(time_parts[1]), int(time_parts[2])
            elif len(time_parts) == 2:
                h = 0
                m, s = int(time_parts[0]), int(time_parts[1])
            else:
                h, m, s = 0, 0, int(time_parts[0])
            return days * 86400 + h * 3600 + m * 60 + s

        time_parts = etime_str.split(":")
        if len(time_parts) == 3:
            h, m, s = int(time_parts[0]), int(time_parts[1]), int(time_parts[2])
            return h * 3600 + m * 60 + s
        elif len(time_parts) == 2:
            m, s = int(time_parts[0]), int(time_parts[1])
            return m * 60 + s
        else:
            return int(time_parts[0])
    except (ValueError, IndexError):
        return 0.0


def get_service_status(port: int) -> tuple[str, int | None, float]:
    """获取服务状态.

    Returns:
        (status, pid, elapsed_seconds)
        status: "running" | "starting" | "zombie" | "stopped"
    """
    # 端口监听 → 运行中
    pid = find_pid(port)
    if pid is not None and pid > 0:
        return "running", pid, 0.0

    # 查找 Java 进程但端口未监听
    processes = find_java_processes(port)
    if processes:
        # 取最新的进程
        pid, elapsed = processes[0]
        if elapsed >= 120:
            return "zombie", pid, elapsed
        return "starting", pid, elapsed

    return "stopped", None, 0.0


def clear_service(project: ProjectConfig, service: ServiceConfig, state: StateManager | None = None) -> None:
    """清理服务模块的编译产物（删除整个 target 目录）."""
    target_dir = project.root / service.module / "target"

    if target_dir.exists():
        import shutil
        shutil.rmtree(target_dir)
        console.print(f"[green]已清理: {target_dir}[/green]")
    else:
        console.print(f"[dim]target 目录不存在: {target_dir}[/dim]")

    # 清除编译记录
    if state:
        state.clear_compile_record(service.module)
        console.print("[dim]已清除编译记录[/dim]")


def stop_service(port: int, timeout: int = 30) -> bool:
    """停止服务.

    Args:
        port: 服务端口号.
        timeout: 等待进程结束的最大秒数.

    Returns:
        是否成功停止.
    """
    pid = find_pid(port)
    if pid is None:
        console.print(f"[dim]服务未运行 (端口 {port})[/dim]")
        return True

    console.print(f"[yellow]停止服务 (PID: {pid}, 端口 {port})...[/yellow]")

    try:
        import os
        os.kill(pid, 15)  # SIGTERM
    except ProcessLookupError:
        console.print("[dim]进程已退出[/dim]")
        return True

    # 等待进程结束
    for _ in range(timeout):
        if find_pid(port) is None:
            console.print("[green]服务已停止[/green]")
            return True
        time.sleep(1)

    # 强制终止
    try:
        os.kill(pid, 9)  # SIGKILL
        console.print("[red]强制终止进程[/red]")
    except ProcessLookupError:
        pass

    return find_pid(port) is None


def _resolve_maven_classpath(project_root: Path, module: str, maven: MavenConfig, java_config: JavaConfig | None = None) -> str | None:
    """通过 mvn dependency:build-classpath 获取 Maven 解析的 classpath 顺序."""
    from .maven import resolve_mvn_invocation

    mvn_bin = maven.resolve_mvn_bin()
    classpath_file = project_root / module / "target" / ".maven-classpath.txt"
    cwd, pl_args = resolve_mvn_invocation(project_root, module)

    cmd = [str(mvn_bin), "dependency:build-classpath",
           *pl_args,
           "-DincludeScope=runtime",
           f"-Dmdep.outputFile={classpath_file}",
           "-U",
           "-q"]
    if maven.settings:
        cmd.extend(["-s", maven.settings])

    env = _build_mvn_env(java_config)

    try:
        result = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=60)
        if result.returncode == 0 and classpath_file.exists():
            cp = classpath_file.read_text(encoding="utf-8").strip()
            if cp:
                return cp
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return None


def _build_mvn_env(java_config: JavaConfig | None = None) -> dict[str, str]:
    """构建 Maven 执行的环境变量."""
    import os
    env = os.environ.copy()
    if java_config:
        java_home = java_config.resolve_java_home()
        if java_home:
            env["JAVA_HOME"] = str(java_home)
            env["PATH"] = f"{str(java_home / 'bin')}:{env.get('PATH', '')}"
    return env


def _copy_dependencies(
    project_root: Path, module: str, maven: MavenConfig, java_config: JavaConfig | None = None,
) -> None:
    """拷贝依赖 jar 到 target/lib.

    多模块项目中，reactor 内模块的 jar 可能不在本地仓库，
    需要先 install 依赖模块，再 copy-dependencies。
    单项目/并列项目无 reactor，直接进入模块目录执行。
    """
    from .maven import resolve_mvn_invocation

    mvn_bin = maven.resolve_mvn_bin()
    env = _build_mvn_env(java_config)
    cwd, pl_args = resolve_mvn_invocation(project_root, module)

    # 先 install 依赖模块到本地仓库（reactor 模式下 -am 会自动安装上游模块）
    install_cmd = [str(mvn_bin), "install",
                   *pl_args,
                   "-T", "1C",
                   "-DskipTests"]
    if maven.settings:
        install_cmd.extend(["-s", maven.settings])

    result = subprocess.run(install_cmd, cwd=cwd, env=env, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"安装依赖模块失败 (exit code: {result.returncode})")

    # 再拷贝依赖 jar（copy-dependencies 不支持 -am，这里复用 -pl 但去掉 -am）
    copy_pl_args = [a for a in pl_args if a != "-am"]
    copy_cmd = [str(mvn_bin), "dependency:copy-dependencies",
                *copy_pl_args,
                "-DoutputDirectory=target/lib",
                "-DincludeScope=runtime"]
    if maven.settings:
        copy_cmd.extend(["-s", maven.settings])

    result = subprocess.run(copy_cmd, cwd=cwd, env=env, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"拷贝依赖失败 (exit code: {result.returncode})")


def build_classpath_dev(
    project_root: Path,
    module: str,
    maven: MavenConfig | None = None,
    java_config: JavaConfig | None = None,
) -> str:
    """构建开发模式 classpath.

    优先使用 Maven dependency:build-classpath 获取正确的 jar 加载顺序，
    避免 target/lib 字母排序导致的类冲突。

    Args:
        project_root: 项目根目录.
        module: 服务模块路径.
        maven: Maven 配置（用于获取正确 classpath 顺序）.
        java_config: Java 配置（用于 Maven JAVA_HOME）.

    Returns:
        classpath 字符串.
    """
    module_path = project_root / module
    target_classes = module_path / "target" / "classes"
    target_lib = module_path / "target" / "lib"
    resources = module_path / "src" / "main" / "resources"
    profiles = project_root / "luna-profiles"

    paths: list[str] = []

    if target_classes.exists():
        paths.append(str(target_classes))
    else:
        raise RuntimeError(
            f"未找到编译输出目录: {target_classes}\n"
            f"请先执行编译: mvn compile -pl {module} -am"
        )

    # 优先使用 Maven 解析的 classpath 顺序
    maven_cp = None
    if maven:
        maven_cp = _resolve_maven_classpath(project_root, module, maven, java_config)

    if maven_cp:
        # Maven classpath 用本地仓库路径，替换为 target/lib 下的同名 jar
        lib_jars: dict[str, Path] = {}
        if target_lib.exists():
            for jar in target_lib.glob("*.jar"):
                lib_jars[jar.name] = jar

        for maven_jar_path in maven_cp.split(":"):
            maven_jar_name = Path(maven_jar_path).name
            if maven_jar_name in lib_jars:
                paths.append(str(lib_jars[maven_jar_name]))
            else:
                # Maven 仓库中有但 target/lib 中没有（不应发生），使用原始路径
                paths.append(maven_jar_path)
    elif target_lib.exists():
        # 回退：字母排序（可能存在类冲突）
        for jar in sorted(target_lib.glob("*.jar")):
            paths.append(str(jar))

    if resources.exists():
        paths.append(str(resources))

    if profiles.exists():
        paths.append(str(profiles))

    return ":".join(paths)


def _parse_env_file(path: Path) -> tuple[list[str], dict[str, str]]:
    """解析单个 .env 文件.

    Returns:
        (jvm_opts, sys_envs) - JVM -D 参数列表 和 系统环境变量字典.

    区分规则：
    - 以 spring. / server. / logging. / galaxy. / epm. / platform. / flowable. / sequences. 开头 → JVM -D 参数
    - 其他（如 PAAS_CSE_SC_ENDPOINT、DISTRIBUTED_CACHE_HOST）→ 系统环境变量
    """
    jvm_opts: list[str] = []
    sys_envs: dict[str, str] = {}

    # Spring 配置属性前缀（转为 -D JVM 参数）
    jvm_prefixes = (
        "spring.", "server.", "logging.", "galaxy.",
        "epm.", "platform.", "flowable.", "sequences.",
    )

    if not path.exists():
        return jvm_opts, sys_envs

    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()

            if any(key.startswith(p) for p in jvm_prefixes):
                jvm_opts.append(f"-D{key}={value}")
            else:
                sys_envs[key] = value

    return jvm_opts, sys_envs


def load_env(project: ProjectConfig, env: str) -> tuple[list[str], dict[str, str]]:
    """从环境配置文件加载 JVM 参数和系统环境变量.

    加载顺序（后者覆盖前者）：
    1. 项目根目录 .env
    2. env_dir/.env
    3. env_dir/bootstrap-{env}.env

    Returns:
        (jvm_opts, sys_envs) - 合并后的 JVM 参数 和 系统环境变量.
    """
    all_jvm_opts: list[str] = []
    all_sys_envs: dict[str, str] = {}
    env_dir = project.env_dir or project.root / "env"

    # 项目根目录 .env
    root_env = project.root / ".env"
    if root_env.exists():
        console.print(f"[blue]加载 .env: {root_env}[/blue]")
        jvm, sys = _parse_env_file(root_env)
        all_jvm_opts.extend(jvm)
        all_sys_envs.update(sys)

    # env 目录下的 .env
    dir_env = env_dir / ".env"
    if dir_env.exists():
        console.print(f"[blue]加载 .env: {dir_env}[/blue]")
        jvm, sys = _parse_env_file(dir_env)
        all_jvm_opts.extend(jvm)
        all_sys_envs.update(sys)

    # 环境专属配置文件（支持 bootstrap-{env}.env、{prefix}-{env}.env 等命名）
    env_map = project.scan_envs()
    env_file = env_map.get(env) if env_map else None
    if env_file is None:
        # 兼容旧格式
        env_file = env_dir / f"bootstrap-{env}.env"
    if env_file.exists():
        console.print(f"[blue]加载环境配置: {env_file}[/blue]")
        jvm, sys = _parse_env_file(env_file)
        all_jvm_opts.extend(jvm)
        all_sys_envs.update(sys)
    elif not root_env.exists() and not dir_env.exists():
        console.print(f"[dim]环境配置文件不存在: {env_file}[/dim]")

    return all_jvm_opts, all_sys_envs


def _strip_ansi(text: str) -> str:
    """去除 ANSI 转义序列."""
    import re
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _tail_startup_log(
    process: subprocess.Popen,
    stdout_log: Path,
    service: ServiceConfig,
    env: str,
    start_time: float,
    *,
    debug: bool,
    jmx: bool,
    state: StateManager | None,
    env_jvm_opts: list[str] | None = None,
    env_sys_vars: dict[str, str] | None = None,
) -> None:
    """实时滚动日志，等待服务就绪."""
    from rich.live import Live
    from rich.text import Text

    max_lines = 200  # 保留最近 N 行日志
    log_lines: list[str] = []
    ready = False
    failed = False
    timeout = 120

    # 等待日志文件创建
    for _ in range(10):
        if stdout_log.exists():
            break
        time.sleep(0.5)

    with open(stdout_log, "r", encoding="utf-8", errors="replace") as f:
        with Live(console=console, refresh_per_second=4, vertical_overflow="visible") as live:
            for i in range(timeout * 2):  # 0.5s 间隔
                time.sleep(0.5)

                # 读取新日志行
                new_lines = f.readlines()
                for line in new_lines:
                    clean = _strip_ansi(line.rstrip())
                    log_lines.append(clean)

                # 保留最近 N 行
                if len(log_lines) > max_lines:
                    log_lines = log_lines[-max_lines:]

                # 检查进程是否存活
                if process.poll() is not None:
                    failed = True

                # 检查端口是否监听
                if not failed and is_running(service.port):
                    ready = True

                # 构建显示内容
                elapsed = time.time() - start_time
                status = f"[bold blue]⏳ {service.name} 启动中 ({elapsed:.0f}s)[/bold blue]"
                if ready:
                    status = f"[bold green]✓ {service.name} 启动成功 ({elapsed:.1f}s)[/bold green]"
                elif failed:
                    status = f"[bold red]✗ {service.name} 启动失败[/bold red]"

                text = Text()
                for ln in log_lines[-30:]:  # 显示最近 30 行
                    text.append(ln + "\n")
                text.append(status)

                live.update(text)

                if ready or failed:
                    break

    if failed:
        console.print(f"\n[red]错误: 服务进程已退出[/red]")
        console.print(f"请检查日志: {stdout_log}")
        if state:
            state.record_start(
                service.name, env, process.pid, service.port,
                debug=debug, jmx=jmx,
            )
        raise RuntimeError("服务启动失败")

    if not ready:
        console.print(f"\n[yellow]警告: 服务启动超时 ({timeout}秒)[/yellow]")

    console.print(f"访问地址: http://localhost:{service.port}{service.context_path}")
    _print_env_summary(env, env_jvm_opts, env_sys_vars)

    if state:
        state.record_start(
            service.name, env, process.pid, service.port,
            debug=debug, jmx=jmx,
        )


def _print_env_summary(
    env: str,
    env_jvm_opts: list[str] | None = None,
    env_sys_vars: dict[str, str] | None = None,
) -> None:
    """打印环境配置摘要."""
    console.print(f"\n[bold]环境配置:[/bold] [green]{env}[/green]")
    if env_jvm_opts:
        for opt in env_jvm_opts:
            console.print(f"  {opt}")
    if env_sys_vars:
        for k, v in env_sys_vars.items():
            console.print(f"  {k}={v}")


def start_service(
    project: ProjectConfig,
    service: ServiceConfig,
    env: str,
    *,
    debug: bool = False,
    jmx: bool = False,
    state: StateManager | None = None,
    show_log: bool = False,
) -> None:
    """启动 Java 服务，带进度条和计时.

    Args:
        project: 项目配置.
        service: 服务配置.
        env: 环境名.
        debug: 是否启用远程调试.
        jmx: 是否启用 JMX.
        state: 状态管理器，用于记录启动结果.
        show_log: 是否实时滚动日志（CLI 模式）.
    """
    java_bin = project.java.resolve_java_bin()
    log_dir = project.root / "logs" / f"{service.name}-{env}"
    log_dir.mkdir(parents=True, exist_ok=True)

    # 加载环境配置
    env_jvm_opts, env_sys_vars = load_env(project, env)

    # 构建 JVM 参数
    jvm_opts = project.jvm.build_opts(
        port=service.port,
        env=env,
        log_dir=log_dir,
        debug=debug,
        jmx=jmx,
        extra=env_jvm_opts,
    )

    # 检测是否需要编译
    target_classes = project.root / service.module / "target" / "classes"
    from .watcher import needs_compile
    modules_to_compile = needs_compile(project, service.module, state)
    if not target_classes.exists() or modules_to_compile:
        if not target_classes.exists():
            console.print("[yellow]未找到编译产物，自动编译...[/yellow]")
        else:
            console.print(f"[yellow]检测到 {len(modules_to_compile)} 个模块需要编译[/yellow]")
        from .maven import compile_module
        compile_module(project.root, project.maven, service.module, state, project.java)

    # 确保依赖 jar 可用（target/lib 不存在时拷贝依赖）
    target_lib = project.root / service.module / "target" / "lib"
    if not target_lib.exists():
        console.print("[yellow]拷贝依赖 jar...[/yellow]")
        _copy_dependencies(project.root, service.module, project.maven, project.java)

    # 构建 classpath（使用 Maven 解析的 jar 顺序，避免类冲突）
    classpath = build_classpath_dev(project.root, service.module, project.maven, project.java)

    # 构建启动命令
    cmd = [str(java_bin)] + jvm_opts + ["-classpath", classpath, service.main_class]

    console.print("\n[bold]JVM 参数:[/bold]")
    for opt in jvm_opts:
        console.print(f"  {opt}")

    if env_sys_vars:
        console.print(f"\n[bold]环境变量:[/bold] ({len(env_sys_vars)} 个)")
        for k, v in env_sys_vars.items():
            console.print(f"  {k}={v}")

    console.print(f"\n[bold]主类:[/bold] {service.main_class}")
    console.print(f"[bold]日志目录:[/bold] {log_dir}")

    # 构建进程环境变量（继承当前环境 + 追加 env 文件中的系统变量）
    import os
    proc_env = os.environ.copy()
    proc_env.update(env_sys_vars)

    # 启动进程
    stdout_log = log_dir / "stdout.log"
    start_time = time.time()

    with open(stdout_log, "w", encoding="utf-8") as out:
        process = subprocess.Popen(
            cmd,
            stdout=out,
            stderr=subprocess.STDOUT,
            cwd=project.root,
            env=proc_env,
        )

    console.print(f"\n[green]服务已启动 (PID: {process.pid})[/green]")
    console.print(f"标准输出: {stdout_log}")

    if show_log:
        # 实时滚动日志模式
        _tail_startup_log(
            process, stdout_log, service, env, start_time,
            debug=debug, jmx=jmx, state=state,
            env_jvm_opts=env_jvm_opts, env_sys_vars=env_sys_vars,
        )
        return

    # 默认：进度条模式（TUI 等场景）
    console.print()
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(bar_width=40),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(
            description=f"等待 {service.name}-service 就绪...",
            total=60,
        )

        for i in range(60):
            time.sleep(1)
            progress.update(task, completed=i + 1)  # noqa: B007

            # 检查进程是否存活
            if process.poll() is not None:
                progress.stop()
                console.print("\n[red]错误: 服务进程已退出[/red]")
                console.print(f"请检查日志: {stdout_log}")
                if state:
                    state.record_start(
                        service.name, env, process.pid, service.port,
                        debug=debug, jmx=jmx,
                    )
                raise RuntimeError("服务启动失败")

            # 检查端口是否监听
            if is_running(service.port):
                progress.update(task, completed=60)
                break
        else:
            console.print(f"\n[yellow]警告: 服务启动超时 (60秒)[/yellow]")

    duration = time.time() - start_time
    console.print(f"\n[bold green]服务启动完成 ({duration:.1f}s)[/bold green]")
    console.print(f"访问地址: http://localhost:{service.port}{service.context_path}")
    _print_env_summary(env, env_jvm_opts, env_sys_vars)

    # 记录启动状态
    if state:
        state.record_start(
            service.name, env, process.pid, service.port,
            debug=debug, jmx=jmx,
        )


