# 打包说明

两类发行包：

- Debian/Ubuntu 的 `.deb`，可构建 `all`（任意架构）、`arm64`、`armhf`、`amd64` 四种；
- 现代 Windows 的单文件 `mcmgr.exe`，支持 x64 与 ARM64（原生）。

两者都由项目根目录统一驱动，产物在 `dist/`。`.deb` 是纯 Python 包，**不需要为目标
架构编译**，在 x86_64 机器上也能构建 ARM 包；exe 由 PyInstaller 生成，不能交叉编译，
必须在目标架构的 Windows 上构建（本机或 CI）。

## Debian / Ubuntu：`.deb`

```bash
./packaging/deb/build-deb.sh                    # -> dist/mcmgr_<版本>_all.deb
ARCH=arm64 ./packaging/deb/build-deb.sh         # -> dist/mcmgr_<版本>_arm64.deb
ARCH=armhf ./packaging/deb/build-deb.sh         # -> dist/mcmgr_<版本>_armhf.deb
ARCH=amd64 ./packaging/deb/build-deb.sh         # -> dist/mcmgr_<版本>_amd64.deb
./packaging/deb/build-all.sh                    # 一次构建 all + arm64 + armhf
OUT=/tmp/deb ./packaging/deb/build-deb.sh       # 自定义输出目录
SKIP_STAMP=1 ./packaging/deb/build-deb.sh       # 沿用已有构建戳（build-all 内部使用）
```

`ARCH` 的取值：

| 值 | 可安装于 | 说明 |
| --- | --- | --- |
| `all`（默认） | 所有架构 | 纯 Python，推荐：一个包覆盖 x86_64 / ARM64 / ARMHF |
| `arm64` | 64 位 ARM（aarch64） | Debian/Ubuntu ARM64 服务器、树莓派 64 位系统等 |
| `armhf` | 32 位 ARM（硬浮点） | 树莓派 32 位系统等 |
| `amd64` | x86_64 | 只在 x86_64 上安装 |

构建不要求 root；`dpkg-deb --root-owner-group` 负责把属主固定为 root:root。脚本会先
运行 `tools/stamp_build.py`，所以 `mcmgr env` 里的 `built` 就是这次打包时间。
`build-all.sh` 只写一次构建戳，三个产物的时间一致。

安装与卸载：

```bash
sudo apt install ./dist/mcmgr_0.7.0_all.deb   # 自动装 python3 依赖
mcmgr --version
sudo apt remove mcmgr                         # 保留 ~/.mcmgr 数据
```

在 ARM64 上装 `_all.deb` 即可；想只允许 ARM64 安装时用 `_arm64.deb`。

包内布局：

| 路径 | 内容 |
| --- | --- |
| `/usr/bin/mcmgr` | 启动器（`python3 -B -c`，显式把 `/usr/lib/mcmgr` 放到 `sys.path` 最前，避免当前目录的同名包遮蔽） |
| `/usr/lib/mcmgr/mcmgr/` | Python 源码包（含 `_build.json` 构建戳） |
| `/usr/share/doc/mcmgr/` | README、`copyright`、`changelog.Debian.gz` |

依赖：`python3 (>= 3.10)`；`Recommends: default-jre-headless | default-jre`（只影响
启动游戏，安装文件不需要 Java）。启动器带 `-B`，不会在 `/usr/lib` 下写
`__pycache__`，卸载后无残留。

验证过：`dpkg -i` 安装 → `mcmgr --version` / `mcmgr env` / `mcmgr info` →
`dpkg -r` 卸载，无残留；从包含另一个 `mcmgr/` 源码目录的 cwd 运行也只会加载
`/usr/lib/mcmgr` 的版本。arm64 包在 CI 的 `ubuntu-24.04-arm` runner 上做同样的
安装/运行/卸载验证；armhf 只能在 ARM32 系统上安装，CI 仅构建并检查包元数据。

## Windows：`mcmgr.exe`（x64 / ARM64）

在 **对应架构** 的 Windows 10/11 上构建（需要 python.org 的 Python 3.10+，不能用
Microsoft Store 的应用别名）：

```powershell
powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1
```

- x64 Windows → `.venv-win` 里安装 `win_amd64` 版 PyInstaller → `dist\mcmgr.exe`（x64）。
- ARM64 Windows → 安装 ARM64 Python（python.org 的 Windows ARM64 安装包）→ pip 选到
  `win_arm64` 版 PyInstaller → `dist\mcmgr.exe`（原生 ARM64）。

脚本会：

1. 打印 Python 版本和 `platform.machine()`，便于确认架构；
2. 运行 `tools/stamp_build.py` 写入真实构建时间；
3. 运行 `packaging\windows\make_version_info.py` 生成 exe 的版本资源；
4. 创建 `.venv-win` 并安装 `pyinstaller`；
5. 用 `packaging\windows\mcmgr.spec` 打包成单文件 `dist\mcmgr.exe`；
6. 打印大小、SHA-256，并跑一次 `mcmgr.exe --version` 冒烟测试。

产物是**单文件控制台程序**，自带 Python 运行时，目标机不需要安装 Python；仍然需要
Java 来实际启动游戏（`mcmgr` 会自动查找已有 Java）。首次运行会解压到 `%TEMP%`，
属正常现象；exe 未签名，SmartScreen 可能提示"未知发布者"，选择"更多信息 → 仍要运行"。

`mcmgr.exe env` 的 `build` 行会显示 `frozen executable (PyInstaller)`，`source`
指向 exe 自身，`built` 来自打包时写入的 `_build.json`，`platform` 行会显示
`Windows ... ARM64` 或 `AMD64`。

x64 exe 在 Windows 11 ARM 上可以通过系统自带的 x64 模拟运行，但性能和启动稍差；
能拿到 ARM64 机器（或 CI）时优先用原生 ARM64 构建。

### 没有对应架构的 Windows 机器？

推 tag 或手动触发 `.github/workflows/build-packages.yml`，GitHub Actions 会按矩阵构建：

| Job | Runner | 产物 |
| --- | --- | --- |
| deb `all` | `ubuntu-latest` | `mcmgr-deb-all`（安装/卸载冒烟测试） |
| deb `arm64` | `ubuntu-24.04-arm` | `mcmgr-deb-arm64`（在真实 ARM64 上安装/运行/卸载） |
| deb `armhf` | `ubuntu-latest` | `mcmgr-deb-armhf`（只构建） |
| exe `x64` | `windows-latest` | `mcmgr-windows-x64` → `mcmgr-windows-x64.exe` |
| exe `arm64` | `windows-11-arm` | `mcmgr-windows-arm64` → `mcmgr-windows-arm64.exe` |

Artifacts 在对应 workflow run 页面下载。

### 关于 Wine

仓库里还有一个尽力而为的脚本 `packaging/windows/build-under-wine.sh`（本机开发用），
在 Linux + Wine 下安装 **x64** Windows Python 3.12 并调用同一个 spec。Wine 环境差异
较大，只作为没有 Windows 时的备用手段；它只能产出 x64 exe，**不能**构建原生 ARM64
exe。正式发布建议用 Windows 或 CI。

## 版本与构建时间

两个包都从 `mcmgr/__init__.py` 读取版本，从 `mcmgr/_build.json` 读取构建时间；
发版前改版本号后重新运行打包脚本即可，无需手工维护第二处。
