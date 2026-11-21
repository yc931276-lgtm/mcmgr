# 打包说明

两种发行包：Debian/Ubuntu 的 `.deb`（在 Linux 上构建）和现代 Windows 的
`mcmgr.exe`（在 Windows 上构建，PyInstaller 不能交叉编译）。两者都由项目根目录
统一驱动，产物在 `dist/`。

## Debian / Ubuntu：`.deb`

```bash
./packaging/deb/build-deb.sh              # -> dist/mcmgr_<版本>_all.deb
OUT=/tmp/deb ./packaging/deb/build-deb.sh # 自定义输出目录
SKIP_STAMP=1 ./packaging/deb/build-deb.sh # 沿用已有构建戳（不建议）
```

构建不要求 root；`dpkg-deb --root-owner-group` 负责把属主固定为 root:root。
脚本会先运行 `tools/stamp_build.py`，所以 `mcmgr env` 里的 `built` 就是这次打包时间。

安装与卸载：

```bash
sudo apt install ./dist/mcmgr_0.4.1_all.deb   # 自动装 python3 依赖
mcmgr --version
sudo apt remove mcmgr                          # 保留 ~/.mcmgr 数据
```

包内布局：

| 路径 | 内容 |
| --- | --- |
| `/usr/bin/mcmgr` | 启动器（`python3 -B -c`，显式把 `/usr/lib/mcmgr` 放到 `sys.path` 最前，避免当前目录的同名包遮蔽） |
| `/usr/lib/mcmgr/mcmgr/` | Python 源码包（含 `_build.json` 构建戳） |
| `/usr/share/doc/mcmgr/` | README、`copyright`、`changelog.Debian.gz` |

依赖：`python3 (>= 3.10)`；`Recommends: default-jre-headless | default-jre`（只影响
启动游戏，安装文件不需要 Java）。启动器带 `-B`，不会在 `/usr/lib` 下写
`__pycache__`，卸载后无残留。`Architecture: all`（纯 Python），可按需用
`ARCH=amd64` 之类的值覆盖文件名和控制字段。

测试过：`dpkg -i` 安装 → `mcmgr --version` / `mcmgr env` / `mcmgr info` →
`dpkg -r` 卸载，无残留；从包含另一个 `mcmgr/` 源码目录的 cwd 运行也只会加载
`/usr/lib/mcmgr` 的版本。

## Windows：`mcmgr.exe`

在 Windows 10/11 上（需要 python.org 的 Python 3.10+，不能用 Microsoft Store 的
应用别名）：

```powershell
powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1
```

脚本会：

1. 运行 `tools/stamp_build.py` 写入真实构建时间；
2. 运行 `packaging\windows\make_version_info.py` 生成 exe 的版本资源；
3. 创建 `.venv-win` 并安装 `pyinstaller`；
4. 用 `packaging\windows\mcmgr.spec` 打包成单文件 `dist\mcmgr.exe`；
5. 打印大小、SHA-256，并跑一次 `mcmgr.exe --version` 冒烟测试。

产物是**单文件控制台程序**，自带 Python 运行时，目标机不需要安装 Python；仍然需要
Java 来实际启动游戏（`mcmgr` 会自动查找已有 Java）。首次运行会解压到
`%TEMP%`，属正常现象；exe 未签名，SmartScreen 可能提示"未知发布者"，选择
"更多信息 → 仍要运行"即可。

`mcmgr.exe env` 的 `build` 行会显示 `frozen executable (PyInstaller)`，`source`
指向 exe 自身，`built` 来自打包时写入的 `_build.json`。

### 没有 Windows 机器？

推 tag 或手动触发 `.github/workflows/build-packages.yml`，GitHub Actions 会在
`windows-latest` 上构建 exe、在 `ubuntu-latest` 上构建 deb，并从 workflow 的
Artifacts 下载 `mcmgr-deb` / `mcmgr-windows`。

### 关于 Wine

仓库里还有一个尽力而为的脚本 `packaging/windows/build-under-wine.sh`（本机开发
用），在 Linux + Wine 下安装 Windows Python 3.12 并调用同一个 spec。Wine 环境
差异较大，只作为没有 Windows 时的备用手段；正式发布建议用 Windows 或 CI。

## 版本与构建时间

两个包都从 `mcmgr/__init__.py` 读取版本，从 `mcmgr/_build.json` 读取构建时间；
发版前改版本号后重新运行打包脚本即可，无需手工维护第二处。
