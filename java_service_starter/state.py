"""状态持久化模块.

保存编译历史、启动记录等状态，避免重复操作，支持快速重启。
"""

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Self


@dataclass
class CompileRecord:
    """模块编译记录."""

    module: str
    timestamp: float
    success: bool
    duration: float = 0.0
    error: str | None = None


@dataclass
class StartRecord:
    """服务启动记录."""

    service: str
    env: str
    pid: int
    port: int
    timestamp: float
    debug: bool = False
    jmx: bool = False


@dataclass
class ProjectState:
    """项目状态数据."""

    project_name: str
    compile_history: dict[str, CompileRecord] = field(default_factory=dict)
    """模块路径 -> 最近编译记录."""
    start_history: list[StartRecord] = field(default_factory=list)
    """启动历史记录."""
    last_service_args: dict[str, dict] = field(default_factory=dict)
    """服务名 -> 上次启动参数."""

    def to_dict(self) -> dict:
        """序列化为字典."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Self:
        """从字典反序列化."""
        compile_history = {
            k: CompileRecord(**v)
            for k, v in data.get("compile_history", {}).items()
        }
        start_history = [
            StartRecord(**r) for r in data.get("start_history", [])
        ]
        return cls(
            project_name=data["project_name"],
            compile_history=compile_history,
            start_history=start_history,
            last_service_args=data.get("last_service_args", {}),
        )


class StateManager:
    """状态管理器."""

    STATE_FILE = ".java-service-starter/state.json"

    def __init__(self, project_root: Path, project_name: str) -> None:
        self.project_root = project_root
        self.state_file = project_root / self.STATE_FILE
        self.state = self._load(project_name)

    def _load(self, project_name: str) -> ProjectState:
        """加载状态."""
        if self.state_file.exists():
            try:
                with open(self.state_file, encoding="utf-8") as f:
                    data = json.load(f)
                return ProjectState.from_dict(data)
            except (json.JSONDecodeError, KeyError, TypeError):
                pass
        return ProjectState(project_name=project_name)

    def save(self) -> None:
        """保存状态到文件."""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(self.state.to_dict(), f, indent=2, ensure_ascii=False)

    def record_compile(self, module: str, success: bool, duration: float = 0.0, error: str | None = None) -> None:
        """记录编译结果."""
        self.state.compile_history[module] = CompileRecord(
            module=module,
            timestamp=time.time(),
            success=success,
            duration=duration,
            error=error,
        )
        self.save()

    def record_start(
        self,
        service: str,
        env: str,
        pid: int,
        port: int,
        *,
        debug: bool = False,
        jmx: bool = False,
    ) -> None:
        """记录启动结果."""
        record = StartRecord(
            service=service,
            env=env,
            pid=pid,
            port=port,
            timestamp=time.time(),
            debug=debug,
            jmx=jmx,
        )
        self.state.start_history.append(record)
        # 保留最近 50 条
        self.state.start_history = self.state.start_history[-50:]

        # 保存上次启动参数
        self.state.last_service_args[service] = {
            "env": env,
            "debug": debug,
            "jmx": jmx,
        }
        self.save()

    def get_last_compile_time(self, module: str) -> float:
        """获取模块上次成功编译时间."""
        record = self.state.compile_history.get(module)
        if record and record.success:
            return record.timestamp
        return 0.0

    def is_compile_fresh(self, module: str, project_root: Path) -> bool:
        """检查模块编译是否仍是最新的.

        比较上次成功编译时间与源码目录最新修改时间。
        如果源码有更新，则编译不 fresh。
        """
        last_compile = self.get_last_compile_time(module)
        if last_compile == 0:
            return False

        mod_path = project_root / module
        src_dirs = [
            mod_path / "src" / "main" / "java",
            mod_path / "src" / "main" / "resources",
        ]

        for src_dir in src_dirs:
            if not src_dir.exists():
                continue
            for f in src_dir.rglob("*"):
                if f.is_file() and f.stat().st_mtime > last_compile:
                    return False

        return True

    def get_last_start_args(self, service: str) -> dict | None:
        """获取服务上次启动参数."""
        return self.state.last_service_args.get(service)

    def get_last_pid(self, service: str, port: int) -> int | None:
        """获取服务最近一次启动的 PID."""
        for record in reversed(self.state.start_history):
            if record.service == service and record.port == port:
                return record.pid
        return None
