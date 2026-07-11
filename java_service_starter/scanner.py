"""Maven 项目自动扫描模块.

自动扫描项目结构，识别服务模块、主类、端口等配置。
"""

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from rich.console import Console

console = Console()

# Maven POM 命名空间
POM_NS = {"m": "http://maven.apache.org/POM/4.0.0"}


class ScannedService:
    """扫描到的服务信息."""

    def __init__(
        self,
        name: str,
        module_path: str,
        main_class: str | None = None,
        port: int | None = None,
        context_path: str | None = None,
    ) -> None:
        self.name = name
        self.module_path = module_path
        self.main_class = main_class
        self.port = port
        self.context_path = context_path

    def is_complete(self) -> bool:
        """检查是否信息完整."""
        return all([
            self.main_class,
            self.port,
            self.context_path,
        ])

    def __repr__(self) -> str:
        return f"ScannedService({self.name}, port={self.port}, main={self.main_class})"


class ProjectScanner:
    """Maven 项目扫描器."""

    def __init__(self, project_root: Path) -> None:
        self.root = project_root.resolve()
        self.services: list[ScannedService] = []

    def scan(self) -> list[ScannedService]:
        """扫描项目，识别所有潜在的服务模块."""
        console.print(f"[dim]扫描项目: {self.root}[/dim]")

        # 查找所有 pom.xml（排除 target 目录）
        pom_files = [
            p for p in self.root.rglob("pom.xml")
            if "target" not in str(p)
        ]

        for pom_path in sorted(pom_files):
            self._analyze_module(pom_path)

        # 排序：信息完整的放前面
        self.services.sort(key=lambda s: (not s.is_complete(), s.name))
        return self.services

    def _analyze_module(self, pom_path: Path) -> None:
        """分析单个模块."""
        module_dir = pom_path.parent
        rel_path = module_dir.relative_to(self.root).as_posix()

        # 检查是否有 src/main/java（Java 模块的特征）
        # 注意：根目录本身可能就是单独立项目，不再跳过 rel_path == "."
        src_java = module_dir / "src" / "main" / "java"
        if not src_java.exists():
            return

        # 根目录作为服务时，使用项目目录名作为推断基准
        infer_name = self.root.name if rel_path == "." else module_dir.name

        service = ScannedService(
            name=self._infer_service_name(infer_name),
            module_path=rel_path,
        )

        # 解析 pom.xml 提取信息
        self._parse_pom(pom_path, service)

        # 扫描源码寻找主类
        if not service.main_class:
            service.main_class = self._find_main_class(src_java)

        # 无主类的模块是依赖库，不是可启动服务，跳过
        if not service.main_class:
            return

        # 扫描配置文件寻找端口
        if not service.port:
            service.port = self._find_port(module_dir)

        # 推断 context-path
        if not service.context_path:
            service.context_path = self._infer_context_path(service.name)

        self.services.append(service)

    def _parse_pom(self, pom_path: Path, service: ScannedService) -> None:
        """解析 pom.xml 提取构建信息."""
        try:
            tree = ET.parse(pom_path)
            root = tree.getroot()

            # 查找 packaging 类型
            packaging = root.find("m:packaging", POM_NS)
            if packaging is not None and packaging.text == "pom":
                # 聚合模块，不是可运行模块
                # 但如果有 src/main/java，可能是聚合模块包含代码
                pass

            # 查找 properties 中的 server.port
            props = root.find("m:properties", POM_NS)
            if props is not None:
                port_prop = props.find("m:server.port", POM_NS)
                if port_prop is not None and port_prop.text is not None:
                    try:
                        service.port = int(port_prop.text)
                    except ValueError:
                        pass

        except ET.ParseError:
            pass

    def _find_main_class(self, src_java: Path) -> str | None:
        """在源码中查找 Spring Boot 主类.

        优先级：
        1. 同时包含 @SpringBootApplication 和 SpringApplication.run 的类
        2. 包含 SpringApplication.run 的类
        3. 包含 main 方法且类名含 Application 的类
        """
        spring_boot_pattern = re.compile(r"@SpringBootApplication")
        spring_run_pattern = re.compile(r"SpringApplication\.run\s*\(")
        main_pattern = re.compile(r"public\s+static\s+void\s+main\s*\(")
        package_pattern = re.compile(r"^package\s+([\w.]+);")

        candidates: list[tuple[int, str]] = []  # (priority, full_class_name)

        for java_file in sorted(src_java.rglob("*.java")):
            content = java_file.read_text(encoding="utf-8", errors="ignore")
            has_spring_boot = spring_boot_pattern.search(content) is not None
            has_spring_run = spring_run_pattern.search(content) is not None
            has_main = main_pattern.search(content) is not None

            if has_spring_boot and has_spring_run:
                priority = 0  # 最高优先级
            elif has_spring_run:
                priority = 1
            elif has_main and "Application" in java_file.stem:
                priority = 2
            else:
                continue

            package_match = package_pattern.search(content)
            package = package_match.group(1) if package_match else ""
            class_name = java_file.stem
            full_name = f"{package}.{class_name}" if package else class_name

            candidates.append((priority, full_name))

        if not candidates:
            return None

        candidates.sort(key=lambda x: x[0])
        return candidates[0][1]

    def _find_port(self, module_dir: Path) -> int | None:
        """从配置文件查找服务端口.

        搜索范围：
        1. src/main/resources/ 下所有 application*.properties
        2. src/main/resources/ 下所有 application*.yml / yaml（含子目录如 config/）
        3. pom.xml 中的 server.port property

        YAML 匹配策略：找到 server: 块后，在同级缩进范围内查找 port: 数字
        """
        resources = module_dir / "src" / "main" / "resources"
        if not resources.exists():
            return None

        port = None

        # 检查 properties 文件（仅 application.properties，不含环境后缀）
        for prop_file in resources.rglob("application.properties"):
            content = prop_file.read_text(encoding="utf-8", errors="ignore")
            match = re.search(r"server\.port\s*=\s*(\d+)", content)
            if match:
                port = int(match.group(1))
                break

        # 检查 yaml 文件（仅 application.yml/yaml，不含环境后缀）
        if port is None:
            for ext in ("yml", "yaml"):
                for yaml_file in resources.rglob(f"application.{ext}"):
                    port = self._parse_yaml_port(yaml_file)
                    if port:
                        break
                if port:
                    break

        return port

    def _parse_yaml_port(self, yaml_file: Path) -> int | None:
        """从 YAML 文件解析 server.port.

        采用逐行解析，正确处理缩进层级：
        1. 找到 ^server: 行，记录其缩进
        2. 在 server 块内（缩进更深），找到 port: 数字 的行
        3. 超出 server 块缩进则停止
        """
        content = yaml_file.read_text(encoding="utf-8", errors="ignore")
        lines = content.splitlines()

        in_server = False
        server_indent = 0

        for line in lines:
            stripped = line.lstrip()
            if not stripped or stripped.startswith("#"):
                continue

            current_indent = len(line) - len(stripped)

            # 找到 server: 块开始
            if stripped.startswith("server:") and not in_server:
                in_server = True
                server_indent = current_indent
                continue

            if in_server:
                # 缩进回退到 server 级别或更浅，说明 server 块结束
                if current_indent <= server_indent:
                    in_server = False
                    continue

                # 在 server 块内找 port: 数字
                port_match = re.match(r"[ \t]*port:\s*(\d+)\s*$", line)
                if port_match:
                    return int(port_match.group(1))

        return None

    def _infer_service_name(self, module_name: str) -> str:
        """从模块名推断简短服务名.

        策略：先剥离后缀，再按需剥离前缀，避免名称冲突。
        例如:
          uccb-epm-ps-service → ps（剥后缀 -service → uccb-epm-ps，剥前缀 uccb-epm- → ps）
          core-banking-service → core-banking（剥后缀 -service → core-banking，仅2段不剥前缀）
          notification-service → notification（剥后缀 -service → notification，仅1段不剥前缀）
          uccb-epm-application-batch → batch
          user-service → user
        """
        name = module_name

        # 第一步：剥离常见后缀
        suffixes = [
            r"-service$",
            r"-application$",
            r"-app$",
            r"-web$",
            r"-api$",
            r"-ui$",
            r"-worker$",
            r"-job$",
        ]
        for pat in suffixes:
            new_name = re.sub(pat, "", name)
            if new_name != name:
                name = new_name
                break

        # 第二步：仅当剥离后段数仍≥3时（暗示存在企业前缀），剥离前缀
        # 这避免了 "core-banking" 被错误剥离为 "banking"
        if name.count("-") >= 2:
            prefixes = [
                r"^[a-z]+-[a-z]+-application-",  # uccb-epm-application-
                r"^[a-z]+-[a-z]+-",              # uccb-epm-
                r"^[a-z]+-application-",          # myapp-application-
            ]
            for pat in prefixes:
                new_name = re.sub(pat, "", name)
                if new_name != name:
                    name = new_name
                    break

        # 如果简化后为空或太短，回退到原模块名
        if len(name) < 2:
            return module_name

        return name

    def _infer_context_path(self, module_name: str) -> str:
        """根据模块名推断 context-path."""
        # 常见缩写映射
        name_upper = module_name.upper()
        # 提取短名称（去掉前缀）
        for prefix in ["UCCB-EPM-", "EPM-", "SERVICE-"]:
            if name_upper.startswith(prefix):
                name_upper = name_upper[len(prefix):]
                break

        # 去掉 -SERVICE 后缀
        if name_upper.endswith("-SERVICE"):
            name_upper = name_upper[:-8]

        # 去掉 -APPLICATION 后缀
        if name_upper.endswith("-APPLICATION"):
            name_upper = name_upper[:-12]

        return f"/{name_upper}"


def scan_project(project_root: Path) -> list[ScannedService]:
    """便捷函数：扫描项目并返回服务列表."""
    scanner = ProjectScanner(project_root)
    return scanner.scan()
