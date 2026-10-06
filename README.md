# HMA-OSS 第三方构建分支

本仓库是 [frknkrc44/HMA-OSS](https://github.com/frknkrc44/HMA-OSS) 的 **第三方构建分支（fork）**：上游代码原样保留，本仓库只负责

1. **每天自动同步上游代码**（把本分支的改动层变基到上游 `master`）；
2. **跟随上游发版**：上游发布新版本时，用同一次提交、同样的版本号自动重新构建并发布本仓库的 release；
3. **更换发行身份**：重新构建的产物使用独立的包名 / 模块 ID / 更新地址，与上游版本互不冲突，可以共存。

上游的版权、许可、翻译与贡献者署名全部保留。所有改动集中在 `fork/fork.env` 与 `scripts/`，完整说明见 [FORK.md](FORK.md)（上游原版 README 见 [README_upstream.md](README_upstream.md)）。

---

## 下载与安装

到 [Releases](https://github.com/keweiya/HMA-OSS/releases/latest) 下载最新版的 `*-release.zip`（Zygisk 模块包）：

1. 在 Magisk / KernelSU 管理器里「从本地安装」该 zip；
2. 安装脚本会自动装好配套的管理器 App（已有旧版会直接覆盖升级）；
3. 重启手机，打开管理器 App，确认状态为「系统服务已加载」。

模块内部同时提供 `-debug.zip`，仅用于排查问题。

## 更新

- App 内「检查更新」与 Magisk / KernelSU 里的模块更新，都指向**本仓库的 Releases**，不会再去上游拿包。
- 版本号与上游保持一致（例如上游 `oss-173`，本仓库也是 `oss-173`），方便对照上游更新内容。
- 每个 release 的说明都是中文的：上游更新内容会翻译成中文（能人工校对就人工校对，否则机器翻译），英文原文折叠在末尾供对照。
- 模块内固定地址：`https://github.com/keweiya/HMA-OSS/releases/latest/download/update.json`

## 本分支的发行身份

| 项目 | 值 | 说明 |
|---|---|---|
| 应用包名 applicationId | `io.moonlit.quarry` | 与上游 `org.frknkrc44.hma_oss` 完全不同，两个版本可共存；**必须是固定值**，随机包名会导致无法覆盖升级，模块与 App 也会失联 |
| 项目名 / 产物名前缀 | `HMA-OSS` | 仓库名与 Gradle 项目名；产物例如 `HMA-OSS-oss-173-release.zip` |
| 模块显示名 / 描述 | `HMA-OSS Zygisk` / `A Zygisk backend for HMA-OSS` | 与上游一致，在 Magisk / KernelSU 里看起来就是原版模块 |
| Magisk 模块 ID | `quarry` | 安装目录 `/data/adb/modules/quarry`；与上游模块不冲突，可共存 |
| 桌面图标名 | `Quarry` | 只影响手机上显示的应用名，想一起改成 `HMA-OSS` 就改 `APP_NAME` |

想改的话只改 [`fork/fork.env`](fork/fork.env) 一处，流水线会按新身份重新生成全部产物。

## 自动化

| 流水线 | 文件 | 定时 | 作用 |
|---|---|---|---|
| 同步上游代码 | [`.github/workflows/fork-sync.yml`](.github/workflows/fork-sync.yml) | 每天 12:17（北京时间） | 只同步代码，不构建、不发版 |
| 检测上游新版本并发布 | [`.github/workflows/fork-release.yml`](.github/workflows/fork-release.yml) | 每天 14:43（北京时间） | 检测到上游**发布了新版本**才构建发版；上游没发新版就空跑结束 |

两条流水线都可以在 Actions 页面手动触发；发版流水线支持指定上游标签（`release_tag`）和强制重建（`force`）。

## 与上游的差异

功能与上游完全一致，只改发行身份相关的部分：包名与命名空间、内部类名、模块 ID / 名称 / 描述 / 脚本名、日志 tag、导出的日志与配置文件名、状态目录、更新地址，以及产物里的上游特征串（部分必须保值的字符串改为运行期解码）。加载器框架强制要求的部分（`zygisk/<abi>.so`、`$ZYGISK_*` 等）保持原样，逐条列在 [FORK.md](FORK.md) 的「反检测处理与残留说明」。

每个 release 的产物在发布前都会自动校验：`applicationId`、`versionName`、以及 dex / 模块 zip 里的特征串，校验不通过不会发布。

## 自行构建

```bash
cp fork/fork.env /tmp/fork.env               # 备份
python3 scripts/fork_identity.py apply --check-anchors   # 把身份应用到当前工作区
./gradlew prebuild && ./gradlew :app:assemble && ./gradlew :zygote:assemble
scripts/fork_verify_artifacts.sh --apk app/build/outputs/apk/release/*.apk \
  --module zygote/build/outputs/magisk/release/*.zip
git checkout -- . && git clean -fd           # 还原工作区
```

签名、密钥配置、目录结构与失败排查见 [FORK.md](FORK.md)。

## 许可与声明

- 上游项目以 **AGPL-3.0** 授权，见 [LICENSE.md](LICENSE.md)；本分支是对上游的修改版本，同样以 AGPL-3.0 提供，源码即本仓库。
- 上游作者与贡献者署名保留在 [CREDITS.md](CREDITS.md)、[README_upstream.md](README_upstream.md) 及各源文件的版权声明中。
- 本仓库是**非官方构建**，请勿把本构建的问题反馈给上游；问题请提到本仓库的 Issues。
