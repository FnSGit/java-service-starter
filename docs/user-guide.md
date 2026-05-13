# Java Service Starter 使用教程

通用 Java Maven 多模块微服务项目一键编译启动器。

---

## 目录

1. [安装](#1-安装)
2. [快速开始](#2-快速开始)
3. [配置详解](#3-配置详解)
4. [命令详解](#4-命令详解)
5. [项目初始化](#5-项目初始化)
6. [编译检测机制](#6-编译检测机制)
7. [环境配置文件](#7-环境配置文件)
8. [常见问题](#8-常见问题)

---

## 1. 安装

### 前置条件

- Python 3.14+
- uv 包管理器
- Java 8+（需已安装）
- Maven（需已安装）

### 安装方式

```bash
# 全局安装（推荐）
uv tool install git+ssh://git@github.com/FnSGit/java-service-starter.git

# 安装后可用两个命令
jss --help
java-start --help
```

---

## 2. 快速开始

```bash
# 1. 初始化项目配置（自动扫描 Maven 模块）
jss init /path/to/your-java-project

# 2. 查看服务列表
jss services

# 3. 查看可用环境
jss envs

# 4. 一键编译启动
jss start <service-name> sit5 -b

# 5. 快速重启（复用上次参数）
jss restart <service-name>

# 6. 停止服务
jss stop <service-name>
```

---

## 3. 配置详解

配置文件为 YAML 格式，位于 `.java-service-starter/config.yaml`，由 `jss init` 自动生成。

### 查找顺序

1. `-c` 参数指定的路径
2. 当前目录 `.java-service-starter/config.yaml`
3. 当前目录 `java-service-starter.yaml`

### 配置结构

```yaml
# 项目基本信息
project:
  name: my-project           # 项目名
  root: /path/to/project     # 项目根目录

# Java 运行环境配置
# path: java 可执行文件路径（如 /usr/bin/java8），为空则自动检测 JAVA_HOME
# version: Java 大版本号，用于选择正确的 JDK
java:
  path: ""
  version: 8

# Maven 构建配置
# path: mvn 可执行文件路径，为空则从 PATH 查找
# settings: Maven settings.xml 路径，为空则用默认
# skip_tests: 编译时是否跳过测试
maven:
  path: ""
  settings: ""
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

# 环境配置文件目录，存放 bootstrap-{env}.env 或 {prefix}-{env}.env 文件
env_dir: /path/to/project/env

# 服务模块配置
# 每个服务包含:
#   main_class: Spring Boot 启动类全限定名
#   module: Maven 模块路径（相对于项目根目录）
#   port: 服务端口号
#   context_path: 上下文路径
services:
  ps:
    main_class: com.example.PsApplication
    module: my-project-application-online/my-project-ps-service
    port: 10023
    context_path: /PS
```

---

## 4. 命令详解

### 全局参数

```
-c, --config CONFIG   指定配置文件路径
```

### start — 启动服务

```bash
jss start <服务名> [环境] [选项]
```

| 参数 | 说明 |
|------|------|
| `服务名` | 配置文件中定义的服务名 |
| `环境` | 环境名（默认 `dev`） |
| `-b, --build` | 一键编译启动：先检测源码变更，按需编译，再启动 |
| `-d, --debug` | 启用远程调试（默认端口 8000） |
| `-j, --jmx` | 启用 JMX 监控（默认端口 1099） |
| `-f, --force` | 服务已运行时强制重启 |

```bash
# 直接启动
jss start ps sit5

# 一键编译启动（推荐）
jss start ps sit5 -b

# 编译启动 + 远程调试
jss start ps sit5 -b -d
```

### restart — 快速重启

```bash
jss restart <服务名> [环境] [选项]
```

自动使用上次启动时的参数（环境、debug、jmx），无需重复输入。

```bash
# 快速重启
jss restart ps

# 重启前编译
jss restart ps -b
```

### stop — 停止服务

```bash
jss stop <服务名>
```

先发送 SIGTERM，等待 30 秒；若未退出则 SIGKILL 强制终止。

### services — 查看服务列表

```bash
# 查看所有服务及运行状态
jss services

# 查看指定服务
jss services ps
```

输出 Rich 表格，包含服务名、端口、主类、模块路径、运行状态(PID)。

### envs — 查看可用环境

```bash
jss envs
```

列出 `env/` 目录下所有环境配置文件及其对应的环境名。

### history — 查看历史

```bash
jss history
```

显示最近的编译记录和启动记录。

---

## 5. 项目初始化

```bash
jss init /path/to/java-project [选项]
```

| 选项 | 说明 |
|------|------|
| `--java-path` | Java 可执行文件路径 |
| `--maven-settings` | Maven settings.xml 路径 |

### 扫描逻辑

1. **模块发现**：扫描项目下所有 `pom.xml`（排除 `target`），筛选含 `src/main/java` 的模块
2. **主类识别**（优先级从高到低）：
   - 同时含 `@SpringBootApplication` 和 `SpringApplication.run`
   - 含 `SpringApplication.run`
   - 含 `main` 方法且类名含 `Application`
3. **端口检测**：从 `application.properties` / `application.yml` 读取 `server.port`
4. **Context-Path 推断**：从模块名推导

### 扫描后需手动补充

端口可能配置在外部配置中心（如 Nacos），扫描器无法自动检测。需编辑配置补充端口号。

---

## 6. 编译检测机制

`-b` 启动时智能检测是否需要编译，两层机制：

### 第一层：持久化状态

比较 `state.json` 中上次编译时间戳 vs 源码文件最新修改时间。源码比编译时间新 → 需要编译。

### 第二层：文件系统回退

比较 `target/classes` 下最新文件 mtime vs `src/main/java` 和 `src/main/resources` 最新文件 mtime。源码比 class 文件新 → 需要编译。

> 注意：使用 `target/classes` 下**文件的最新 mtime**，而非目录 mtime。因为修改已有 class 文件内容不会更新目录条目的 mtime。

---

## 7. 环境配置文件

放在项目 `env/` 目录下，命名格式灵活：

| 文件名 | 环境名 | 解析规则 |
|--------|--------|----------|
| `bootstrap-sit5.env` | sit5 | 剥离第一个 `-` 之前的前缀 |
| `isp-sit5.env` | sit5 | 同上 |
| `dev.env` | dev | 无前缀，直接取 stem |

### 加载顺序（后者覆盖前者）

1. 项目根目录 `.env`
2. `env_dir/.env`
3. 环境专属文件（如 `env_dir/isp-sit5.env`）

### 参数分类规则

- `spring.*`、`server.*`、`logging.*`、`galaxy.*`、`epm.*`、`platform.*` 等 → 自动转为 `-D` JVM 参数
- 其他 key → 作为进程环境变量传递

---

## 8. 常见问题

### Q: 编译检测不准确？

A: 可能原因：
1. IDE 自动编译修改了 `target/classes` 的时间戳 → 下次检测会重新对比
2. `state.json` 被删除 → 重新编译一次后自动恢复

### Q: 启动超时但服务实际在运行？

A: 默认等待 120 秒。超时不影响服务运行，检查日志确认即可。

### Q: 如何修改 JVM 内存参数？

A: 编辑配置文件中的 `jvm.memory` 字段：

```yaml
jvm:
  memory: "-Xms4g -Xmx4g -Xmn1g"
```

### Q: 如何为不同环境使用不同 JVM 参数？

A: 通过 `env/` 目录下的 `.env` 文件注入 `-D` 参数实现环境差异。