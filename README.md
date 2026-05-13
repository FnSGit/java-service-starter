# Java Service Starter

通用 Java Maven 多模块微服务项目一键编译启动器。

## 功能特性

- **一键编译启动** — 智能检测代码变更，只编译有修改的模块
- **多环境支持** — 通过 env 文件管理 sit/uat/prod 等环境配置
- **YAML 驱动** — 项目配置集中管理，团队可共享
- **智能编译检测** — 两层机制：持久化状态 + 文件系统时间戳回退
- **JVM 参数管理** — 内存、GC、调试、JMX 等参数统一配置
- **环境变量分离** — spring.* 等 JVM 参数与进程环境变量自动分类

## 安装

```bash
uv tool install git+ssh://git@github.com/FnSGit/java-service-starter.git
```

## 快速开始

```bash
# 1. 在 Maven 项目根目录初始化配置
cd /path/to/your-java-project
jss init .

# 2. 查看扫描到的服务
jss services

# 3. 查看可用环境
jss envs

# 4. 一键编译启动
jss start <service-name> sit5 -b
```

## 命令列表

| 命令 | 用途 |
|------|------|
| `jss init [目录]` | 初始化项目配置 |
| `jss services [服务名]` | 查看服务列表和运行状态 |
| `jss envs` | 查看可用环境配置 |
| `jss start <服务> <环境> -b` | 一键编译启动 |
| `jss restart <服务> [环境]` | 快速重启 |
| `jss stop <服务>` | 停止服务 |
| `jss history` | 查看编译/启动历史 |

## 配置文件

配置文件位于 `.java-service-starter/config.yaml`，由 `jss init` 自动生成并带注释说明。

### 环境配置文件

放在项目 `env/` 目录下，支持多种命名格式：

| 文件名 | 环境名 |
|--------|--------|
| `bootstrap-sit5.env` | sit5 |
| `isp-sit5.env` | sit5 |
| `dev.env` | dev |

文件内容按 key 前缀自动分类：
- `spring.*`、`server.*`、`logging.*`、`epm.*` 等 → 转为 `-D` JVM 参数
- 其他 key → 作为进程环境变量

## 开发

```bash
# 克隆项目
git clone git@github.com:FnSGit/java-service-starter.git
cd java-service-starter

# 安装开发依赖
uv sync

# 运行测试
uv run pytest
```

## License

MIT
