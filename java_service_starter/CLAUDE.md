[根目录](../CLAUDE.md) > **java_service_starter**

# java_service_starter

Java Service Starter 核心包，实现 Java Maven 项目的扫描、编译、启动、停止等全部业务逻辑。

## 模块职责

作为单模块 Python 包，包含 CLI 入口和所有业务模块，提供 `jss` / `java-start` 命令行工具。

## 入口与启动

- **CLI 入口**：`cli.py:main()` -- 由 `pyproject.toml` 的 `[project.scripts]` 注册为 `jss` 和 `java-start`
- 命令分发：`main()` 通过 argparse 解析子命令，路由到 `cmd_*` 函数

## 对外接口

### CLI 命令（用户直接调用）

| 命令 | 对应函数 | 核心逻辑 |
|------|----------|----------|
| `jss init` | `cmd_init()` | 调用 `ProjectScanner.scan()` 扫描项目，生成 `config.yaml` |
| `jss status` | `cmd_status()` | 调用 `get_service_status()` 查询端口/进程状态 |
| `jss envs` | `cmd_envs()` | 调用 `ProjectConfig.scan_envs()` 扫描环境文件 |
| `jss start` | `cmd_start()` | 调用 `start_service()` 编译+启动 |
| `jss restart` | `cmd_restart()` | 停止后重新启动，复用 `state.get_last_start_args()` |
| `jss stop` | `cmd_stop()` | 调用 `stop_service()` 发送 SIGTERM |
| `jss clear` | `cmd_clear()` | 调用 `clear_service()` 删除 target 目录 |
| `jss history` | `cmd_history()` | 从 `StateManager` 读取历史记录 |

### Python API（可被其他模块导入）

- `start_service(project, service, env, ...)` -- 完整的编译+启动流程
- `stop_service(port)` -- 停止指定端口的服务
- `is_running(port)` -- 检查端口是否在监听
- `find_pid(port)` -- 查找占用端口的进程 PID
- `get_service_status(port)` -- 返回 (status, pid, elapsed)
- `load_env(project, env)` -- 加载环境配置，返回 (jvm_opts, sys_envs)
- `build_classpath_dev(...)` -- 构建开发模式 classpath
- `compile_module(...)` -- 执行 Maven 编译
- `needs_compile(project, module, state)` -- 检测是否需要编译

## 关键依赖与配置

### 运行时依赖

- `pyyaml>=6.0` -- YAML 配置文件解析
- `rich>=13.0` -- 终端富文本输出（表格、进度条、实时日志）

### 构建工具

- `hatchling` -- 构建后端
- `uv` -- 包管理与虚拟环境

### 配置文件格式

配置文件位于 `.java-service-starter/config.yaml`，顶层结构：

```yaml
project:   # 项目名称和根路径
java:      # Java 路径和版本
maven:     # Maven 路径、settings、是否跳过测试
jvm:       # JVM 参数（base_opts, gc_opts, memory, metaspace, debug/jmx 端口）
env_dir:   # 环境配置文件目录
services:  # 服务模块列表（main_class, module, port, context_path）
```

## 数据模型

| 类 | 文件 | 说明 |
|----|------|------|
| `ServiceConfig` | `models.py` | 单个服务配置（不可变 dataclass） |
| `JavaConfig` | `models.py` | Java 路径/版本，含 `resolve_java_bin()` / `resolve_java_home()` |
| `JvmConfig` | `models.py` | JVM 参数，含 `build_opts()` 构建完整参数列表 |
| `MavenConfig` | `models.py` | Maven 路径/配置，含 `build_compile_args()` |
| `ProjectConfig` | `models.py` | 项目全局配置，含 `from_yaml()` 反序列化和 `scan_envs()` |
| `ScannedService` | `scanner.py` | 扫描到的服务信息（可变） |
| `CompileRecord` | `state.py` | 编译记录数据类 |
| `StartRecord` | `state.py` | 启动记录数据类 |
| `ProjectState` | `state.py` | 项目状态聚合类 |
| `StateManager` | `state.py` | 状态管理器，JSON 持久化到 `.java-service-starter/state.json` |

## 测试与质量

当前**无测试目录和测试用例**。参见根 CLAUDE.md 的测试策略章节获取建议优先级。

## 常见问题 (FAQ)

**Q: 环境变量如何分类为 JVM 参数和系统环境变量？**
A: 在 `java_runner.py` 的 `_parse_env_file()` 中，以 `spring.`/`server.`/`logging.`/`galaxy.`/`epm.`/`platform.`/`flowable.`/`sequences.` 开头的 key 转为 `-D` JVM 参数，其余作为进程环境变量。

**Q: 编译检测的两层策略是什么？**
A: 优先使用 `StateManager.is_compile_fresh()`（比较持久化的编译时间戳与源码 mtime），若状态不存在则回退到文件系统时间戳比较（比较 `target/classes` 与 `src/main` 的 mtime）。

**Q: classpath 构建为什么优先使用 Maven 解析？**
A: `target/lib` 目录下 jar 按字母排序可能导致类冲突（同名类在不同 jar 中），Maven `dependency:build-classpath` 能给出正确的加载顺序。

**Q: 如何添加新的环境变量前缀到 JVM 参数分类？**
A: 修改 `java_runner.py` 中 `_parse_env_file()` 函数的 `jvm_prefixes` 元组。

## 相关文件清单

```
java_service_starter/
  __init__.py       # 版本号: __version__ = "2.0.0"
  cli.py            # CLI 入口，8 个子命令
  models.py         # 5 个数据模型类
  scanner.py        # ProjectScanner, ScannedService
  maven.py          # compile_module(), auto_compile()
  watcher.py        # needs_compile()
  java_runner.py    # 核心运行时：进程管理、环境加载、classpath 构建
  state.py          # StateManager, ProjectState, CompileRecord, StartRecord
```

## 变更记录 (Changelog)

| 时间 | 操作 | 说明 |
|------|------|------|
| 2026-05-14 21:45 | 初始创建 | 首次生成模块 AI 上下文文档 |
