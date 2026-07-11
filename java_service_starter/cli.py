"""命令行入口."""

import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .java_runner import clear_service, get_service_status, is_running, start_service, stop_service
from .models import ProjectConfig
from .state import StateManager

console = Console()


def _resolve_config_path(config_arg: str | None) -> Path:
    """解析配置文件路径."""
    if config_arg:
        p = Path(config_arg).expanduser().resolve()
        if p.exists():
            return p
        raise FileNotFoundError(f"配置文件不存在: {p}")

    candidates = [
        Path.cwd() / ".java-service-starter" / "config.yaml",
        Path.cwd() / "java-service-starter.yaml",
        Path.cwd() / "config" / "java-service-starter.yaml",
    ]
    for c in candidates:
        if c.exists():
            return c

    raise FileNotFoundError(
        "未找到配置文件。请在项目根目录下执行 'jss init'，或指定 -c/--config 参数"
    )


def _load_project(config_path: Path) -> tuple[ProjectConfig, StateManager]:
    """加载项目配置和状态."""
    project = ProjectConfig.from_yaml(config_path)
    state = StateManager(project.root, project.name)
    return project, state


def cmd_start(args: argparse.Namespace) -> int:
    """处理 start 命令."""
    config_path = _resolve_config_path(args.config)
    project, state = _load_project(config_path)
    service = project.get_service(args.service)

    if is_running(service.port):
        console.print(
            f"[yellow]警告: {args.service}-service 已在运行 (端口 {service.port})[/yellow]"
        )
        if not args.force:
            answer = console.input("是否停止并重启? [y/N]: ")
            if answer.lower() != "y":
                return 0
        stop_service(service.port)

    console.print(Panel.fit(f"启动服务: {args.service}-service", style="bold blue"))
    start_service(project, service, args.env, debug=args.debug, jmx=args.jmx, state=state, show_log=True)
    return 0


def cmd_restart(args: argparse.Namespace) -> int:
    """处理 restart 命令."""
    config_path = _resolve_config_path(args.config)
    project, state = _load_project(config_path)
    service = project.get_service(args.service)

    last_args = state.get_last_start_args(args.service)
    env = args.env or (last_args["env"] if last_args else "dev")
    debug = args.debug or (last_args.get("debug", False) if last_args else False)
    jmx = args.jmx or (last_args.get("jmx", False) if last_args else False)

    console.print(
        Panel.fit(
            f"快速重启: {args.service}-service (env={env})",
            style="bold blue",
        )
    )
    stop_service(service.port)

    start_service(project, service, env, debug=debug, jmx=jmx, state=state, show_log=True)
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    """处理 stop 命令."""
    config_path = _resolve_config_path(args.config)
    project, _ = _load_project(config_path)
    service = project.get_service(args.service)
    stop_service(service.port)
    return 0


def cmd_clear(args: argparse.Namespace) -> int:
    """处理 clear 命令 — 清理编译产物并重新编译."""
    config_path = _resolve_config_path(args.config)
    project, state = _load_project(config_path)
    service = project.get_service(args.service)

    console.print(Panel.fit(f"清理: {args.service}-service", style="bold yellow"))
    clear_service(project, service, state)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """列出项目服务及其运行状态."""
    config_path = _resolve_config_path(args.config)
    project, state = _load_project(config_path)

    # 可选过滤单个服务
    services = (
        {args.service: project.get_service(args.service)}
        if args.service
        else project.services
    )

    table = Table(title=f"{project.name} - 服务列表", show_lines=True)
    table.add_column("服务", style="bold cyan")
    table.add_column("端口", justify="right")
    table.add_column("PID", justify="right")
    table.add_column("环境", style="bold green")
    table.add_column("状态")

    for name, svc in services.items():
        status_str, pid, elapsed = get_service_status(svc.port)
        last_args = state.get_last_start_args(name)

        if status_str == "running":
            env_str = last_args.get("env", "-") if last_args else "-"
            status = f"[green]运行中[/green]"
        elif status_str == "starting":
            env_str = last_args.get("env", "-") if last_args else "-"
            status = f"[yellow]启动中 ({elapsed:.0f}s)[/yellow]"
        elif status_str == "zombie":
            env_str = last_args.get("env", "-") if last_args else "-"
            status = f"[red]僵尸进程 ({elapsed:.0f}s)[/red]"
        else:
            env_str = ""
            status = "[dim]未运行[/dim]"

        pid_str = str(pid) if pid else "-"
        table.add_row(name, str(svc.port), pid_str, env_str, status)

    console.print(table)
    return 0


def cmd_envs(args: argparse.Namespace) -> int:
    """列出项目可用的环境配置."""
    config_path = _resolve_config_path(args.config)
    project, _ = _load_project(config_path)

    env_map = project.scan_envs()

    if not env_map:
        console.print("[yellow]未找到环境配置文件[/yellow]")
        console.print("[dim]请在 env/ 目录下创建 bootstrap-{env}.env 或 {prefix}-{env}.env 文件[/dim]")
        return 0

    table = Table(title=f"{project.name} - 环境配置", show_lines=True)
    table.add_column("环境", style="bold green")
    table.add_column("配置文件")

    for env_name, env_path in env_map.items():
        table.add_row(env_name, env_path.name)

    console.print(table)
    return 0


def cmd_logs(args: argparse.Namespace) -> int:
    """查看服务日志."""
    config_path = _resolve_config_path(args.config)
    project, state = _load_project(config_path)
    service = project.get_service(args.service)

    # 从上次启动参数获取环境名
    last_args = state.get_last_start_args(args.service)
    env = args.env or (last_args["env"] if last_args else "dev")

    log_file = project.root / "logs" / f"{service.name}-{env}" / "stdout.log"
    if not log_file.exists():
        console.print(f"[red]日志文件不存在: {log_file}[/red]")
        return 1

    lines = args.lines
    with open(log_file, encoding="utf-8", errors="replace") as f:
        all_lines = f.readlines()

    tail_lines = all_lines[-lines:]
    console.print(Panel.fit(
        f"[bold]{service.name}-{env}[/bold] 日志 (最近 {len(tail_lines)} 行)",
        style="blue",
    ))
    for line in tail_lines:
        console.print(line.rstrip())

    return 0


def cmd_history(args: argparse.Namespace) -> int:
    """处理 history 命令."""
    config_path = _resolve_config_path(args.config)
    project, state = _load_project(config_path)

    console.print(Panel.fit("历史记录", style="bold blue"))

    console.print("\n[bold]最近编译记录:[/bold]")
    if state.state.compile_history:
        for module, record in sorted(
            state.state.compile_history.items(),
            key=lambda x: x[1].timestamp,
            reverse=True,
        )[:10]:
            status = "[green]成功[/green]" if record.success else "[red]失败[/red]"
            from datetime import datetime

            time_str = datetime.fromtimestamp(record.timestamp).strftime("%m-%d %H:%M")
            console.print(f"  {module:40} {status}  {time_str}  ({record.duration:.1f}s)")
    else:
        console.print("  无记录")

    console.print("\n[bold]最近启动记录:[/bold]")
    if state.state.start_history:
        for record in reversed(state.state.start_history[-10:]):
            from datetime import datetime

            time_str = datetime.fromtimestamp(record.timestamp).strftime("%m-%d %H:%M")
            debug_tag = " [dim]debug[/dim]" if record.debug else ""
            jmx_tag = " [dim]jmx[/dim]" if record.jmx else ""
            console.print(
                f"  {record.service:10}  env={record.env}  PID={record.pid}  "
                f"端口={record.port}{debug_tag}{jmx_tag}  {time_str}"
            )
    else:
        console.print("  无记录")

    return 0


def _write_config_template(
    config_file: Path,
    *,
    project_root: Path,
    services: dict,
    java_path: str,
    maven_settings: str,
    env_dir: Path | None,
) -> None:
    """生成带注释的模板配置文件，所有属性都写入且注明作用."""
    svc_lines = []
    for name, svc in services.items():
        svc_lines.append(f"  {name}:")
        svc_lines.append(f"    main_class: {svc['main_class']}")
        svc_lines.append(f"    module: {svc['module']}")
        svc_lines.append(f"    port: {svc['port']}")
        svc_lines.append(f"    context_path: {svc['context_path']}")

    env_dir_line = f"env_dir: {env_dir}\n\n" if env_dir else "# env_dir: /path/to/env  # 环境配置文件目录，存放 bootstrap-{env}.env 或 {prefix}-{env}.env 文件\n\n"

    content = f"""\
# Java Service Starter 配置文件
# 由 jss init 自动生成，请根据项目需要修改

# 项目基本信息
project:
  name: {project_root.name}
  root: {project_root}

# Java 运行环境配置
# path: java 可执行文件路径（如 /usr/bin/java8），为空则自动检测 JAVA_HOME
# version: Java 大版本号，用于选择正确的 JDK
java:
  path: {java_path or '""'}
  version: 8

# Maven 构建配置
# path: mvn 可执行文件路径，为空则从 PATH 查找
# settings: Maven settings.xml 路径（如 ~/.m2/settings-sit.xml），为空则用默认
# skip_tests: 编译时是否跳过测试
maven:
  path: ""
  settings: {maven_settings or '""'}
  skip_tests: true

# JVM 参数配置
# base_opts: 基础 JVM 参数
# gc_opts: 垃圾回收参数
# memory: 堆内存设置
# metaspace: 元空间设置
# heap_dump_on_oom: OOM 时自动生成堆转储
# debug_port: 远程调试端口
# jmx_port: JMX 监控端口
jvm:
  base_opts:
    - -Djava.awt.headless=true
    - -Djava.net.preferIPv4Stack=true
  gc_opts:
    - -XX:+UseG1GC
    - -XX:MaxGCPauseMillis=200
  memory: "-Xms2g -Xmx2g -Xmn512m"
  metaspace: "-XX:MetaspaceSize=512m -XX:MaxMetaspaceSize=1024m"
  heap_dump_on_oom: true
  debug_port: 8000
  jmx_port: 1099

{env_dir_line}\
# 服务模块配置
# 每个服务包含:
#   main_class: Spring Boot 启动类全限定名
#   module: Maven 模块路径（相对于项目根目录）
#   port: 服务端口号
#   context_path: 上下文路径
services:
{chr(10).join(svc_lines)}
"""

    with open(config_file, "w", encoding="utf-8") as f:
        f.write(content)


def cmd_init(args: argparse.Namespace) -> int:
    """初始化项目配置（命令行版向导）."""
    project_root = Path(args.project).expanduser().resolve()

    if not project_root.exists():
        console.print(f"[red]目录不存在: {project_root}[/red]")
        return 1

    # 不再强制要求根目录有 pom.xml
    # 支持三种结构：
    # 1. 单独立项目（根目录有 pom + src/main/java）
    # 2. Maven 多模块项目（根有聚合 pom，子模块有各自 pom）
    # 3. 多独立项目并列（根目录无 pom，子目录各为独立项目）
    # 由 ProjectScanner 统一识别，扫描结果为空时再报错

    console.print(Panel.fit(f"初始化项目: {project_root.name}", style="bold blue"))

    from .scanner import ProjectScanner

    scanner = ProjectScanner(project_root)
    services = scanner.scan()

    if not services:
        console.print("[red]未找到任何服务模块[/red]")
        console.print("[dim]需要满足以下任一结构：[/dim]")
        console.print("[dim]  1. 单项目：当前目录有 pom.xml + src/main/java + Spring Boot 主类[/dim]")
        console.print("[dim]  2. 多模块：当前目录有聚合 pom.xml，子模块有各自 pom.xml[/dim]")
        console.print("[dim]  3. 并列项目：子目录各为独立 Maven 项目[/dim]")
        return 1

    console.print(f"\n[green]找到 {len(services)} 个服务模块:[/green]")
    for svc in services:
        status = "[green]完整[/green]" if svc.is_complete() else "[yellow]需补充[/yellow]"
        console.print(
            f"  {svc.name:20} 端口:{svc.port or '?':>6}  "
            f"主类:{svc.main_class or '?'}  {status}"
        )

    java_path = args.java_path or ""
    maven_settings = args.maven_settings or ""

    services_yaml = {}
    for svc in services:
        services_yaml[svc.name] = {
            "main_class": svc.main_class or "",
            "module": svc.module_path,
            "port": svc.port or 8080,
            "context_path": svc.context_path or f"/{svc.name.upper()}",
        }

    config_dir = project_root / ".java-service-starter"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "config.yaml"

    _write_config_template(
        config_file,
        project_root=project_root,
        services=services_yaml,
        java_path=java_path,
        maven_settings=maven_settings,
        env_dir=project_root / "env" if (project_root / "env").exists() else None,
    )

    console.print(f"\n[bold green]配置已保存: {config_file}[/bold green]")
    return 0


def main() -> int:
    """主入口."""
    parser = argparse.ArgumentParser(
        prog="jss",
        description="通用 Java Maven 项目一键编译启动器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  jss init .                    # 初始化项目配置
  jss status                    # 查看服务运行状态
  jss status ps                 # 查看指定服务状态
  jss envs                      # 查看可用环境
  jss start ps sit5             # 启动服务（自动编译）
  jss restart ps                # 快速重启
  jss stop ps                   # 停止服务
  jss clear ps                  # 清理编译产物（下次启动自动编译）
  jss logs ps                   # 查看服务日志（最近500行）
  jss logs ps sit5 -n 100       # 查看指定环境最近100行
  jss history                   # 查看历史
        """,
    )
    parser.add_argument("-c", "--config", help="配置文件路径")

    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # init 命令
    init_parser = subparsers.add_parser("init", help="初始化项目配置")
    init_parser.add_argument("project", nargs="?", default=".", help="项目根目录 (默认: 当前目录)")
    init_parser.add_argument("--java-path", help="Java 可执行文件路径")
    init_parser.add_argument("--maven-settings", help="Maven settings.xml 路径")

    # status 命令
    status_parser = subparsers.add_parser("status", help="查看服务运行状态")
    status_parser.add_argument("service", nargs="?", help="服务名称 (查看指定服务)")

    # envs 命令
    subparsers.add_parser("envs", help="查看可用环境配置")

    # start 命令
    start_parser = subparsers.add_parser("start", help="启动服务")
    start_parser.add_argument("service", help="服务名称")
    start_parser.add_argument("env", nargs="?", default="dev", help="环境 (默认: dev)")
    start_parser.add_argument("-d", "--debug", action="store_true", help="启用远程调试")
    start_parser.add_argument("-j", "--jmx", action="store_true", help="启用 JMX")
    start_parser.add_argument("-f", "--force", action="store_true", help="强制重启")

    # restart 命令
    restart_parser = subparsers.add_parser("restart", help="快速重启")
    restart_parser.add_argument("service", help="服务名称")
    restart_parser.add_argument("env", nargs="?", help="环境")
    restart_parser.add_argument("-d", "--debug", action="store_true", help="启用远程调试")
    restart_parser.add_argument("-j", "--jmx", action="store_true", help="启用 JMX")

    # stop 命令
    stop_parser = subparsers.add_parser("stop", help="停止服务")
    stop_parser.add_argument("service", help="服务名称")

    # clear 命令
    clear_parser = subparsers.add_parser("clear", help="清理编译产物")
    clear_parser.add_argument("service", help="服务名称")

    # logs 命令
    logs_parser = subparsers.add_parser("logs", help="查看服务日志")
    logs_parser.add_argument("service", help="服务名称")
    logs_parser.add_argument("env", nargs="?", help="环境 (默认: 上次启动的环境)")
    logs_parser.add_argument("-n", "--lines", type=int, default=500, help="显示行数 (默认: 500)")

    # history 命令
    subparsers.add_parser("history", help="查看编译/启动历史")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    try:
        match args.command:
            case "init":
                return cmd_init(args)
            case "status":
                return cmd_status(args)
            case "envs":
                return cmd_envs(args)
            case "start":
                return cmd_start(args)
            case "restart":
                return cmd_restart(args)
            case "stop":
                return cmd_stop(args)
            case "clear":
                return cmd_clear(args)
            case "logs":
                return cmd_logs(args)
            case "history":
                return cmd_history(args)
            case _:
                parser.print_help()
                return 1
    except Exception as e:
        console.print(f"[bold red]错误: {e}[/bold red]")
        return 1


if __name__ == "__main__":
    sys.exit(main())
