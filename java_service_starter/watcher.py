"""源码变更检测模块."""

from pathlib import Path

from .models import ProjectConfig
from .state import StateManager


def _get_newest_mtime(directory: Path) -> float:
    """获取目录下所有文件中最新的修改时间戳."""
    newest = 0.0
    if not directory.exists():
        return newest
    for f in directory.rglob("*"):
        if f.is_file():
            mtime = f.stat().st_mtime
            if mtime > newest:
                newest = mtime
    return newest


def needs_compile(project: ProjectConfig, service_module: str, state: StateManager) -> list[str]:
    """检测需要编译的模块列表.

    优先使用持久化状态判断编译 freshness，
    若状态不存在则回退到文件系统时间戳比较。

    Returns:
        需要编译的模块路径列表。空列表表示无需编译。
    """
    modules_to_compile: list[str] = []

    # 收集需要检查的所有模块（目标模块 + 所有含 src 的子模块）
    modules: list[str] = [service_module]

    # 扫描项目根目录下所有含 src/main/java 的子模块
    for pom in sorted(project.root.rglob("pom.xml")):
        if "target" in str(pom):
            continue
        mod_dir = pom.parent
        rel_mod = mod_dir.relative_to(project.root).as_posix()
        if rel_mod == "." or rel_mod == service_module or rel_mod in modules:
            continue
        if (mod_dir / "src" / "main" / "java").exists():
            modules.append(rel_mod)

    for mod in modules:
        # 优先使用持久化状态判断
        if state.is_compile_fresh(mod, project.root):
            continue

        # 回退到文件系统时间戳比较
        mod_path = project.root / mod
        target_classes = mod_path / "target" / "classes"

        # 没有编译输出，必然需要编译
        if not target_classes.exists():
            modules_to_compile.append(mod)
            continue

        # 用 target/classes 下最新文件 mtime 代替目录 mtime
        # （目录 mtime 只在增删文件时更新，修改已有 class 文件不会更新目录 mtime）
        target_mtime = _get_newest_mtime(target_classes)
        if target_mtime == 0.0:
            modules_to_compile.append(mod)
            continue

        # 检查 src/main/java 和 src/main/resources
        src_dirs = [
            mod_path / "src" / "main" / "java",
            mod_path / "src" / "main" / "resources",
        ]
        has_change = False
        for src_dir in src_dirs:
            newest_src = _get_newest_mtime(src_dir)
            if newest_src > target_mtime:
                has_change = True
                break

        if has_change:
            modules_to_compile.append(mod)

    return modules_to_compile
