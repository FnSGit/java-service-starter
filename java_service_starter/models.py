"""数据模型定义."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Self


@dataclass(frozen=True, slots=True)
class ServiceConfig:
    """单个服务配置."""

    name: str
    main_class: str
    module: str
    port: int
    context_path: str


@dataclass(frozen=True, slots=True)
class JavaConfig:
    """Java 配置."""

    path: str | None
    version: int | None

    def resolve_java_bin(self) -> Path:
        """解析 Java 可执行文件路径."""
        if self.path:
            p = Path(self.path)
            if p.is_file() and p.exists():
                return p
            # 可能是目录，追加 bin/java
            p = p / "bin" / "java"
            if p.exists():
                return p

        import shutil

        java = shutil.which("java")
        if java:
            return Path(java)

        raise RuntimeError(
            "未找到 Java 可执行文件。请配置 java.path 或设置 JAVA_HOME 环境变量。"
        )

    def resolve_java_home(self) -> Path | None:
        """解析 JAVA_HOME 目录.

        用于 Maven 编译时确保使用正确版本的 Java。
        优先级：java.path 推导 > JAVA_HOME 环境变量 > None
        """
        if self.path:
            p = Path(self.path).resolve()  # 解析符号链接
            # 如果是 bin/java，取其父目录的父目录
            if p.is_file() and p.name == "java":
                return p.parent.parent
            # 如果是 bin 目录
            if p.is_dir() and p.name == "bin":
                return p.parent
            # 如果是 JDK 根目录
            if (p / "bin" / "java").exists():
                return p

        import os

        env_home = os.environ.get("JAVA_HOME")
        if env_home:
            return Path(env_home)

        return None


@dataclass(frozen=True, slots=True)
class JvmConfig:
    """JVM 参数配置."""

    base_opts: list[str] = field(default_factory=list)
    gc_opts: list[str] = field(default_factory=list)
    memory: str = "-Xms2g -Xmx2g"
    metaspace: str | None = None
    heap_dump_on_oom: bool = True
    debug_port: int = 8000
    jmx_port: int = 1099

    def build_opts(
        self,
        *,
        port: int,
        env: str,
        log_dir: Path,
        debug: bool = False,
        jmx: bool = False,
        extra: list[str] | None = None,
    ) -> list[str]:
        """构建完整 JVM 参数列表."""
        opts: list[str] = []
        opts.extend(self.base_opts)
        opts.extend(self.gc_opts)
        opts.extend(self.memory.split())
        if self.metaspace:
            opts.extend(self.metaspace.split())
        if self.heap_dump_on_oom:
            opts.append("-XX:+HeapDumpOnOutOfMemoryError")
            opts.append(f"-XX:HeapDumpPath={log_dir}")

        opts.append(f"-Dserver.port={port}")
        opts.append(f"-Dspring.profiles.active={env}")
        opts.append(f"-Dgalaxy.profile={env}")
        opts.append(f"-Dlogging.file.path={log_dir}")

        if debug:
            opts.append(
                f"-agentlib:jdwp=transport=dt_socket,server=y,suspend=n,address={self.debug_port}"
            )
        if jmx:
            opts.extend([
                f"-Dcom.sun.management.jmxremote.port={self.jmx_port}",
                "-Dcom.sun.management.jmxremote.ssl=false",
                "-Dcom.sun.management.jmxremote.authenticate=false",
            ])

        if extra:
            opts.extend(extra)

        return opts


@dataclass(frozen=True, slots=True)
class MavenConfig:
    """Maven 配置."""

    path: str | None
    settings: str | None
    skip_tests: bool = True

    def resolve_mvn_bin(self) -> Path:
        """解析 mvn 可执行文件路径."""
        if self.path:
            p = Path(self.path)
            if p.is_file() and p.exists():
                return p

        import shutil

        mvn = shutil.which("mvn")
        if mvn:
            return Path(mvn)

        raise RuntimeError(
            "未找到 Maven 可执行文件。请配置 maven.path 或确保 mvn 在 PATH 中。"
        )

    def build_compile_args(self, module: str, goal: str = "compile") -> list[str]:
        """构建 Maven 编译参数.

        Args:
            module: 目标模块路径.
            goal: Maven 目标，默认 compile。clear 后重建用 package.
        """
        args = [goal, "-pl", module, "-am", "-T", "1C"]
        if self.skip_tests:
            args.append("-DskipTests")
        if self.settings:
            args.extend(["-s", self.settings])
        return args


@dataclass(frozen=True, slots=True)
class ProjectConfig:
    """项目全局配置."""

    name: str
    root: Path
    services: dict[str, ServiceConfig]
    java: JavaConfig
    jvm: JvmConfig
    maven: MavenConfig
    env_dir: Path | None = None

    @classmethod
    def from_yaml(cls, config_path: Path) -> Self:
        """从 YAML 文件加载配置."""
        import yaml

        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        project = data["project"]
        root = Path(project["root"]).expanduser().resolve()

        services = {}
        for name, svc in data.get("services", {}).items():
            services[name] = ServiceConfig(
                name=name,
                main_class=svc["main_class"],
                module=svc["module"],
                port=svc["port"],
                context_path=svc.get("context_path", ""),
            )

        java_data = data.get("java", {})
        java = JavaConfig(
            path=java_data.get("path"),
            version=java_data.get("version"),
        )

        jvm_data = data.get("jvm", {})
        jvm = JvmConfig(
            base_opts=jvm_data.get("base_opts", []),
            gc_opts=jvm_data.get("gc_opts", []),
            memory=jvm_data.get("memory", "-Xms2g -Xmx2g"),
            metaspace=jvm_data.get("metaspace"),
            heap_dump_on_oom=jvm_data.get("heap_dump_on_oom", True),
            debug_port=jvm_data.get("debug_port", 8000),
            jmx_port=jvm_data.get("jmx_port", 1099),
        )

        maven_data = data.get("maven", {})
        maven = MavenConfig(
            path=maven_data.get("path"),
            settings=maven_data.get("settings"),
            skip_tests=maven_data.get("skip_tests", True),
        )

        env_dir = data.get("env_dir")

        return cls(
            name=project["name"],
            root=root,
            services=services,
            java=java,
            jvm=jvm,
            maven=maven,
            env_dir=Path(env_dir).expanduser().resolve() if env_dir else None,
        )

    def scan_envs(self) -> dict[str, Path]:
        """扫描环境配置文件，返回 env_name → filepath 映射.

        支持 bootstrap-{env}.env、{prefix}-{env}.env、{env}.env 等命名格式.
        剥离第一个 '-' 之前的前缀作为环境名: bootstrap-sit5 → sit5, isp-sit5 → sit5.
        """
        env_dir = self.env_dir or self.root / "env"
        if not env_dir.exists():
            return {}

        result: dict[str, Path] = {}
        for f in sorted(env_dir.glob("*.env")):
            if f.name == ".env":
                continue
            stem = f.stem
            env_name = stem.split("-", 1)[1] if "-" in stem else stem
            result[env_name] = f
        return result

    def get_service(self, name: str) -> ServiceConfig:
        """获取指定服务配置."""
        if name not in self.services:
            available = ", ".join(sorted(self.services))
            raise ValueError(f"未知服务: '{name}'。可用服务: {available}")
        return self.services[name]
