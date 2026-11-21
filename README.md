# mcmgr

一个用 Python 写的命令行工具，用来**下载、安装和管理 Java 版（原版）Minecraft**，并支持**离线启动**。

不依赖任何第三方库（纯标准库），Python ≥ 3.10。

## 安装

Debian/Ubuntu 可以直接装 `.deb`（见下方「打包与发行」），Windows 可以下载/构建单文件
`mcmgr.exe`。从源码运行时，任选其一（都不需要第三方依赖）：

```bash
cd mcmgr
./bin/mcmgr --help            # 直接运行源码树里的启动脚本（推荐）
python3 -m mcmgr --help       # 或者用 -m 模块方式
python3 -m pip install --user .   # 有 pip 的话可以装成命令（需要 setuptools）
```

## 打包与发行

```bash
./packaging/deb/build-deb.sh                  # -> dist/mcmgr_<版本>_all.deb
powershell -File packaging\windows\build.ps1 # Windows 上 -> dist\mcmgr.exe
```

- **Debian/Ubuntu**：`sudo apt install ./dist/mcmgr_0.5.0_all.deb`，安装后
  `/usr/bin/mcmgr` 即可用（源码在 `/usr/lib/mcmgr`，不写 `__pycache__`，卸载无残留）。
  依赖 `python3 (>= 3.10)`，Java 只是启动游戏时才需要。
- **Windows 10/11**：`build.ps1` 用 PyInstaller 打包成自带 Python 运行时的单文件
  `mcmgr.exe`（目标机无需装 Python）；PyInstaller 不能交叉编译，需要在 Windows 上
  构建，或推 tag 让 `.github/workflows/build-packages.yml` 在 CI 上生成。
- 细节（包布局、卸载、Wine 备用方案、CI 产物下载）见
  [`packaging/README.md`](packaging/README.md)。

## 快速开始

```bash
mcmgr versions                    # 列出可安装的正式版
mcmgr install 1.21.4              # 下载客户端、libraries、natives 和资源文件
mcmgr list                        # 查看已经装好的版本
mcmgr launch 1.21.4 -u Steve      # 离线启动（用户名自定义）
mcmgr config 1.21.4 -u Steve --uuid <uuid> --memory 4G   # 记住启动设置，以后直接 launch
```

> 首次 `install` 会下载资源文件（assets），体积较大（数百 MB），之后各版本共享。

## 命令一览

| 命令 | 说明 |
| --- | --- |
| `mcmgr versions` | 列出可安装版本（`--type release\|snapshot\|old\|all`，`--search 关键字`，`--limit N`，`--refresh` 强制刷新版本清单） |
| `mcmgr install <版本>` | 安装版本；`--no-assets` 跳过资源文件（体积小，但游戏内音效/语言等会缺失），`--jobs N` 同时下载的文件数，`--threads N` 单个大文件的分片连接数，`--force` 重新校验并补齐文件 |
| `mcmgr list` | 列出已安装版本及其占用、Java 要求、安装时间 |
| `mcmgr launch <版本>` | 启动游戏；`-u/--username`（`--name` 同义）、`--uuid`、`-m/--memory`、`--jvm-arg`、`--game-arg`、`--save`、`--dry-run`（见下文） |
| `mcmgr config <版本>` | 查看/修改该版本记住的启动设置（用户名、UUID、内存、Java、窗口、JVM/游戏参数），详见下文 |
| `mcmgr skin <版本>` | 给离线玩家换默认角色皮肤（资源包方式，不改 client jar）；`--file`、`--model`、`--show`、`--clear`（见下文） |
| `mcmgr lang <版本>` | 游戏语言：`--set system` 跟随系统，或 `--set zh_cn` 指定；`--show`、`--list`、`--clear`、`--json`（见下文） |
| `mcmgr verify <版本>` | 校验已安装文件（缺失/哈希不符） |
| `mcmgr remove <版本>` | 卸载版本；`--all-files` 连同实例存档目录一起删除 |
| `mcmgr javas` | 列出系统里检测到的 Java |
| `mcmgr info <版本>` | 显示版本详情、启动所需的 Java |
| `mcmgr env` | 查看版本、构建信息、安装路径、Python/系统、数据目录占用、镜像/代理、Java、已装版本；`--json` 输出机器可读格式 |
| `mcmgr --root DIR ...` | 使用自定义数据目录（默认 `~/.mcmgr`，也可用环境变量 `MCMGR_HOME`） |
| `mcmgr --mirror official\|bmclapi\|auto ...` | 下载源：官方 / BMCLAPI 镜像 / auto（默认读 `MCMGR_MIRROR`，见下文） |

`install` 支持版本别名：`latest`、`latest-release`、`latest-snapshot`。

### 查看版本与环境

纯 Python 项目没有编译产物，所以"构建时间"以源码构建戳（`mcmgr/_build.json`）为准：

```bash
./mcmgr --version      # 如 mcmgr 0.4.0
./mcmgr env            # 版本 + 构建来源 + 运行环境的总览
./mcmgr env --json     # 同样的内容，JSON 格式（便于脚本/反馈问题用）
```

`env` 会打印：

- **版本/构建**：程序版本、源码目录，以及 git 提交号（从 git 检出运行时显示 `git <sha>`，有未提交改动会标 `(modified)`；直接拷贝的目录显示 `source tree (no VCS metadata)`）；
- **构建时间**：`built 2026-11-21T19:12:00+08:00, 5m ago, commit abc1234`。时间来自 `mcmgr/_build.json`，由 `python3 tools/stamp_build.py` 在打包/拷贝前生成（同时记录版本、UTC 偏移、git 提交号）。没有构建戳时会退回"最新源码文件的修改时间"并标注 `no build stamp`；如果源码比构建戳更新，会显示 `[sources newer than stamp]`，提醒你重新生成；
- **运行环境**：Python 版本/实现/解释器路径、操作系统与架构；
- **数据目录**：`~/.mcmgr` 是否存在、是否可写、已占用空间与磁盘剩余；
- **下载设置**：当前镜像模式（`official`/`bmclapi`/`auto`）及其来源（默认值还是 `MCMGR_MIRROR`），以及探测到的 `http_proxy` 等代理变量；
- **Java**：`JAVA_HOME` 和所有检测到的运行时（版本号 + 路径）；
- **已安装版本**与已保存的启动配置版本列表。

发布或拷贝给别人之前跑一次：

```bash
python3 tools/stamp_build.py          # 写 mcmgr/_build.json（当前时间 + 版本 + git 提交）
python3 tools/stamp_build.py --print  # 只打印，不落盘
python3 tools/stamp_build.py --clean  # 删除构建戳
```

单看某个版本的信息用 `mcmgr info <版本>`，列已安装用 `mcmgr list`。

### 启动参数

```bash
mcmgr launch 1.21.4 -u Alex --memory 4G --java /usr/lib/jvm/java-21-openjdk-amd64/bin/java \
  --width 1280 --height 720 -- --fullscreen --server example.com
```

- `-u/--username`：离线用户名（默认 `Player`）
- `-m/--memory`：最大堆内存，支持 `2G` / `2048M` / `512`
- `--java`：指定 Java 可执行文件；不指定则按版本要求自动挑选（找不到会报错）
- `--width` / `--height`：窗口尺寸
- `--uuid`：自定义玩家 UUID（支持 8-4-4-4-12 或 32 位十六进制）；`--uuid offline` 表示仍按用户名推导
- `--jvm-arg ARG` / `--game-arg ARG`：附加 JVM 参数 / 游戏参数，可重复；以 `-` 开头的值请写成 `--jvm-arg=-Dfoo=bar`
- `-m/--memory`、`-u/--username` 等未指定时会用 `mcmgr config` 记住的值
- `--save`：把这次命令里的设置记住，下次 `launch` 不用重复
- `--` 之后的参数原样传给游戏
- `--dry-run`：只打印完整启动命令，便于排查

### 离线用户 UUID 与启动参数（config）

默认的离线 UUID 是 `UUID.nameUUIDFromBytes("OfflinePlayer:<用户名>")`（和原版服务端给离线玩家分配的 UUID 一致）。如果某个存档/服务器/模组需要固定的 UUID，可以改掉它：

```bash
# 直接给这次启动换 UUID（32 位或带横线都行）
mcmgr launch 1.21.4 -u Alex --uuid 0123456789abcdef0123456789abcdef

# 或者记住它：以后 launch 都用 Alex + 这个 UUID
mcmgr config 1.21.4 -u Alex --uuid 01234567-89ab-cdef-0123-456789abcdef

# 改回"按用户名推导"
mcmgr config 1.21.4 --uuid offline
```

`config` 能记住的东西：`username`、`uuid`、`memory`、`java`、`width`/`height`、额外 JVM 参数、额外游戏参数；`launch` 里再给的参数优先于记住的值（JVM/游戏参数是**追加**）。设置保存在 `<root>/launch/<版本>.json`，删掉版本文件也不会丢。

```bash
# 常用示例
mcmgr config 1.21.4 --memory 4G --width 1280 --height 720
mcmgr config 1.21.4 --jvm-arg=-XX:+UseG1GC --jvm-arg=-Dfile.encoding=UTF-8
mcmgr config 1.21.4 --game-arg=--fullscreen
mcmgr config 1.21.4 --show                 # 查看当前设置
mcmgr config 1.21.4 --unset uuid --clear-jvm-args   # 清掉单项 / 全部 JVM 参数
mcmgr config 1.21.4 --reset                # 全部清空
```

> 注意：UUID 只影响客户端传给游戏的 `--uuid`（离线模式下服务端仍按用户名分配），主要用于模组兼容、存档归属之类；同一套用户名+UUID 最好保持一致。

### 自定义默认角色（皮肤）

离线模式下没有皮肤服务器，游戏显示的是内置默认角色贴图（旧版 Steve/Alex，新版还有
Ari、Efe、Kai 等 9 个默认皮肤）。`mcmgr skin` 把你的 PNG 做成一个资源包放进实例目录，
并在 `options.txt` 的 `resourcePacks` 里启用，**不会修改 client jar**，所以 `verify`
仍然全绿，重装版本也不会丢。

```bash
mcmgr skin 1.19.2 --file my-skin.png            # 64x64，或旧版的 64x32
mcmgr skin 1.21.4 --file my-skin.png --model slim   # 只替换 slim 默认贴图
mcmgr skin 1.19.2 --show                        # 查看当前皮肤
mcmgr skin 1.19.2 --clear                       # 恢复默认角色
```

- 自动适配两种贴图布局：旧版（≤1.19.2）用 `textures/entity/steve.png`、`alex.png`；
  新版（1.19.4+）用 `textures/entity/player/wide|slim/*.png`。资源包格式号从 client jar
  里的 `version.json` 读取，1.7.10 这类没有 `version.json` 的老版本按发布日期推断。
- 默认 `--model both` 会同时替换 classic（steve/wide）和 slim（alex/slim）两套默认贴图，
  这样无论离线 UUID 被分到哪种模型都能看到自定义皮肤；如果皮肤本身是 slim 布局，
  用 `--model slim` 渲染更准确。
- 资源包保存在 `<root>/instances/<版本>/resourcepacks/mcmgr-default-skin.zip`。
- 玩家名用 `mcmgr config <版本> -u 名字`（或 `--name`）记住，`launch -u/--name` 可临时覆盖。

### 游戏语言（跟随系统）

`mcmgr launch` 第一次启动某个版本时，如果 `options.txt` 里还没有 `lang`，会按系统
locale 写入游戏语言（例如 `LANG=zh_CN.UTF-8` → `lang:zh_cn`），之后你在游戏里改过
语言就不会再被覆盖。

```bash
mcmgr lang 1.19.2 --show          # 当前语言、系统语言、可用语言数
mcmgr lang 1.19.2 --set system    # 跟随系统（也可写 auto/default）
mcmgr lang 1.19.2 --set zh_cn     # 指定语言（大小写都能识别）
mcmgr lang 1.19.2 --list          # 列出该版本可用的全部语言代码
mcmgr lang 1.19.2 --clear         # 删除 lang，退回游戏默认 en_us
```

- 语言代码风格随版本变化：1.12.2 及更早是 `zh_CN`、`en_US` 这种带大写的 `.lang`；
  1.13+ 是 `zh_cn`、`en_us` 的小写 `.json`。`--set` 会自动纠正大小写。
- 可用语言从资产索引（asset index）读取，不在 client jar 里；还没下载资源时
  `--list` 会先下载索引，所以需要正常安装过 assets（`--no-assets` 的版本会缺语言文件）。
- 系统 locale 依次读 `LC_ALL`、`LC_MESSAGES`、`LANGUAGE`、`LANG`；Windows 用系统
  UI 语言。只有语言、没有地区时（如 `LANG=zh`）会补成该语言的默认地区（`zh_cn`）。
- 语言只是 `options.txt` 里的一行，也可以手动改；`launch --dry-run` 不会写文件，
  只打印将要使用的语言。

## 多线程下载

下载是**两层并发**，可以分开调：

```bash
mcmgr install 1.21.4 --jobs 8 --threads 4
```

- `--jobs N`（默认 8）：**同时下载的文件数**。资源库有几千个小文件，这一层提速最明显。
- `--threads N`（默认 4）：**单个大文件用几条连接**。对客户端 jar 这类 ≥2 MiB 的文件，用 HTTP `Range` 请求切成 N 段并行拉取，最后按顺序拼回原文件。

行为说明：

- 服务器不支持 `Range`（或返回整文件）时自动退回单连接，结果不受影响；分片失败也会退回单连接重试。
- 每段写独立的 `.part.seg*` 临时文件，全部完成并校验 SHA-1 后才原子替换成正式文件；中断不会留下坏文件，残留碎片会被清理。
- 小文件不值得切分（阈值 2 MiB），仍然一次请求搞定。
- 想完全关掉多线程：`--jobs 1 --threads 1`。
- 实测：本机从 Mojang CDN 拉 28 MB 客户端 jar，4 连接约 1.5–1.9 s，单连接约 1.7 s（本地带宽不是瓶颈时提升有限，弱网/高延迟环境收益更大）。

## 中国大陆镜像（BMCLAPI）

在中国大陆从 Mojang 官方源下载可能很慢，可以用 [BMCLAPI](https://bmclapi2.bangbang93.com) 镜像：

```bash
mcmgr install 1.21.4 --mirror bmclapi     # 只对这次命令生效
export MCMGR_MIRROR=bmclapi               # 或在 shell 里设环境变量，之后都走镜像
mcmgr install 1.7.10
```

- 三种模式：`official`（只用官方，默认）、`bmclapi`（镜像优先，失败自动回落官方）、`auto`。
  不指定时用 `MCMGR_MIRROR`，再没有就按 `official` 走。全局参数：`mcmgr --mirror bmclapi install 1.21.4`。
- 镜像是**按文件逐个重写**的：版本清单、版本 JSON、客户端 jar、libraries（`/maven/`）、资源对象（`/assets/`）、资产索引（`/v1/packages/`）、log4j 配置都改走镜像；镜像返回 404 的文件（例如个别 log4j 配置）自动回落官方地址。
- 镜像站会先返回 302 跳转到合作节点，个别节点偶尔抖动，靠内置重试即可。

### 代理

如果 shell 里设了 `http_proxy`/`https_proxy` 但代理没开（Clash 没启动之类），下载会先失败一次，然后**自动绕过代理直连**，并在终端提示：

```text
note: proxy connection refused (HTTPS_PROXY=http://127.0.0.1:7890, ...); retrying without a proxy
```

不需要手动 `unset`。之后整个进程都直连，不会每个文件都卡一次。

## 目录结构

```text
~/.mcmgr/                     # 可用 MCMGR_HOME 或 --root 覆盖
├── meta/                     # 版本清单缓存
├── versions/<id>/            # 版本 JSON、客户端 jar、install.json 安装记录
├── libraries/                # 依赖库（Maven 布局）
├── assets/
│   ├── indexes/              # 资源索引
│   ├── objects/<ab>/<hash>   # 资源对象（按哈希去重）
│   └── log_configs/          # log4j 配置
├── natives/<id>/             # 解压后的本地库
├── instances/<id>/           # 每个版本独立的游戏目录（存档、设置都在这里）
└── launch/<id>.json          # mcmgr config 记住的启动设置
```

## 说明与限制

- 仅支持**原版**；不包含 Fabric/Quilt/Forge 等模组加载器。
- 仅支持**离线模式**启动（`--accessToken 0`、`userType legacy`），不能登录微软账号进正版服务器。
- 资源文件按 SHA-1 去重与校验，下载先写 `.part` 再原子替换，支持文件级并发、大文件分片多连接与失败重试。
- 会自动检测系统 Java（`JAVA_HOME`、`/usr/lib/jvm/*`、`which java` 等）；要求版本不满足时会给出提示。
- 网络错误会自动重试（4 次，指数退避 + 抖动），失败时给出可读提示（并列出当前 `http_proxy`/`https_proxy`，便于排查代理）；代理连不上时会自动绕过硬直连。
- 支持中国大陆 BMCLAPI 镜像加速（见上文），镜像文件缺失时自动回落官方。
- 在受限沙箱中使用时，把 `MCMGR_HOME` 指到可写目录（例如 `export MCMGR_HOME=$PWD/.mcmgr`）。

## 测试

```bash
python3 -m unittest discover -s tests -v
```

单测完全离线（不联网），覆盖规则解析、依赖筛选、启动参数拼装、离线 UUID（与 Java 实现一致）、CLI 解析等。

## License

MIT
