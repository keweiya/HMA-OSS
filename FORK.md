# 本分支（fork）说明

本仓库是 [frknkrc44/HMA-OSS](https://github.com/frknkrc44/HMA-OSS) 的第三方构建分支。
上游代码保持原样不动，本分支只做三件事：

1. **定期同步上游代码** —— 每天把上游 `master` 拉到本仓库，并把下方「fork 层」这一个提交 rebase 到最新的上游提交之上。
2. **自动跟随上游发版** —— 定时检测上游是否发布了新的 release（`oss-N`），一旦发现就立刻用该 release 对应的上游提交重新构建、并以同样的 `oss-N` 发一个本仓库的 release。
3. **替换发行身份** —— 重新构建出来的应用包名、Magisk 模块 ID、模块脚本名、系统服务状态目录，以及 App/模块的更新地址，全部指向本分支自己的配置。

上游代码、版权、翻译与贡献者归属全部保留（AGPL-3.0）。本分支的全部改动都可以在下面这几个文件里看完整。

---

## 一、fork 层目录

| 路径 | 作用 |
|---|---|
| `fork/fork.env` | **唯一的身份配置文件**：包名、应用名、Magisk 模块 ID、作者、状态目录前缀、上游仓库等 |
| `scripts/fork_identity.py` | 把「干净的上游工作区」改写成 `fork.env` 描述的身份（apply / verify） |
| `scripts/fork_sync.sh` | 同步上游：`git rebase upstream/master` + 冲突策略 + 推送 |
| `scripts/fork_verify_artifacts.sh` | 构建产物验收：校验 APK 的 applicationId / versionName，扫描 dex 与模块 zip 里的上游特征串 |
| `scripts/fork_gen_keystore.sh` | 生成本分支的签名密钥库，并打印需要写入的 GitHub secrets |
| `.github/workflows/fork-sync.yml` | **同步流水线**（Actions 里显示为「同步上游代码」）：每天定时把 fork 层 rebase 到上游 master，只同步代码，不构建、不发版 |
| `.github/workflows/fork-release.yml` | **发版流水线**（Actions 里显示为「检测上游新版本并发布」）：每天定时检测上游是否出了新版本，是则构建并发版，否则几秒内空跑结束 |
| `fork/release-notes-zh.md` | release 正文的中文模板，占位符由发版流水线渲染 |
| `fork/upstream-notes-zh/<tag>.md` | 上游更新说明的**人工校对中文翻译**（按标签命名，存在时优先使用） |
| `scripts/translate_notes.py` | 没有人工翻译时，用免密钥的机器翻译把上游英文说明转成中文 |
| `README.md` / `README_upstream.md` | 本分支的中文说明（默认展示）/ 上游原版英文说明存档 |
| `FORK.md` | 本文档 |

上游自带的 `.github/workflows/`（`main.yml` / `pull_request.yml` / `issue.yml` / `crowdin.yml`）在本分支已被删除：它们会借用上游的 secrets 和发行标签，在本仓库里跑起来只会报错或污染 releases。`fork_sync.sh` 每次同步后都会重新检查一遍，防止上游新增的 workflow 混进来。

## 二、身份配置（`fork/fork.env`）

```properties
APP_ID=io.moonlit.quarry          # applicationId / namespace
LEGACY_NS=io.moonlit.quarry.legacy # 历史 icu.nullptr.hidemyapplist 源码的新命名空间
PROJECT_NAME=HMA-OSS              # 产物文件名前缀 / Gradle rootProject.name
APP_NAME=Quarry                   # 桌面图标名称
MODULE_ID=quarry                  # 模块 ID -> /data/adb/modules/quarry
MODULE_NAME=HMA-OSS Zygisk        # 模块显示名：与上游保持一致，看起来就是原版模块
MODULE_AUTHOR=keweiya
MODULE_DESC=A Zygisk backend for HMA-OSS   # 与上游保持一致
STATE_PREFIX=quarry_state         # /data/misc/quarry_state_*/status.json
```

同时还会被自动改掉的标识：

| 上游 | 本分支 |
|---|---|
| `HMAService` / `IHMAService`(AIDL) / `HMAServiceDataHolder` | `BridgeService` / `IBridgeService` / `BridgeServiceDataHolder` |
| `MyApp.hmaApp` | `MyApp.managerApp` |
| 日志 tag、导出的日志/配置文件名 | 与上游保持一致（项目同名，无需改名） |
| 界面文案里的 `Zygisk` / `LSPosed` / `HMA/HMAL` / `隐藏应用列表` | `Quarry` / `Xposed` / `Quarry` /（删除） |

改完这里，只需要重新跑一次流水线（或本地构建），**不需要动上游任何一行代码**。校验项：

* `APP_ID`、`LEGACY_NS` 必须是合法 Java 包名，且 `LEGACY_NS` 是 `APP_ID` 的子包；
* 任何一项都不能包含上游特征串（`frknkrc44` / `hma` / `hidemyapplist`），否则直接报错退出。

`fork_identity.py apply` 会做替换 + 目录搬迁 + 事后校验；`verify` 会扫描整个构建输入范围，只要还有一个 `org.frknkrc44.hma_oss`、`icu.nullptr.hidemyapplist`、`hma_oss_zygisk`、`hide_my_applist`、`furkank.net` 或 `api.github.com/repos/frknkrc44` 就会失败。

> 唯一刻意保留的上游字符串是 `AboutFragment.kt` 等文件里的作者署名与版权注释——这是 AGPL-3.0 的署名要求，`verify` 会把它作为提示打印出来，不影响构建。

## 三、自动化流程

### 同步 `fork-sync.yml`

每天 `04:17 UTC`（北京时间 12:17）定时运行，也可手动触发：

1. `git fetch upstream master`；
2. `scripts/fork_sync.sh`：把 fork 层提交 rebase 到 `upstream/master`，冲突按白名单自动裁决（上游 workflow 一律删除；`README.md`/`FORK.md`/`scripts/`/`fork/` 一律以本分支为准；其它文件冲突则中止并报错），然后 `git push --force-with-lease`。

它不参与构建和发版，任何时刻都可以单独跑。

### 发版 `fork-release.yml`

每天 `06:43 UTC`（北京时间 14:43）定时运行，也可手动触发。两个 job：

**job `check`**

1. `gh api repos/frknkrc44/HMA-OSS/releases/latest` 取上游最新 release 标签（手动触发时可用 `release_tag` 指定）；
2. 本仓库若已有同名 release → `new_release=false`，整个流水线到此结束（只跑几秒，不发版）；上游发了新版（本仓库还没有同名 release）→ `new_release=true`。

**job `release`（仅当 `new_release=true`）**

发行版标题固定为 `oss-N（跟随上游发行版重新构建）`，正文由 `fork/release-notes-zh.md` 渲染，**全中文**：安装步骤、更新方式、发行身份表，以及「上游更新说明」的中文译文。正文同样会出现在 App 的更新弹窗里。

上游更新说明的中文按三级回退生成：

1. `fork/upstream-notes-zh/<tag>.md` 存在 → 直接用人工校对翻译（当前 `oss-173` 就是这个情况）；
2. 否则调用 `scripts/translate_notes.py`（免密钥：Google 翻译端点优先，MyMemory 兜底；`Co-authored-by:` 会整理成一行「共同作者」）→ 标注「机器翻译，未人工校对」；
3. 机器翻译不可用 → 保留英文原文并标注。

三种情况都会把英文原文折叠在末尾供对照。上游发了新版之后，如果想让人工翻译覆盖机器翻译，把译文放到 `fork/upstream-notes-zh/<tag>.md` 再手动跑一次发版流水线（勾选 `force`）即可刷新发行说明。

构建与发布步骤：

1. 取上游该标签对应的 commit SHA，`git checkout --detach` 到那个提交（**构建的永远是上游发版时的原始代码**，不是同步中途的半成品）；
2. 从本仓库 `master` 取回 fork 层文件（`scripts/`、`fork/`、`FORK.md`、`.github/workflows/`）；
3. `git update-ref refs/remotes/origin/master <上游 release 的 SHA>` —— 这一步是版本号对齐的关键：上游用 `git rev-list refs/remotes/origin/master --count - 432` 得出 `oss-N`，把该 ref 钉在上游发版提交上，本仓库构建出来的 `versionName` 才会和上游标签**完全一致**（App 内的更新弹窗就是拿 `tag_name` 和 `versionName` 比的，不一致会每次启动都弹更新提示）；
4. 写入签名密钥与 `local.properties`（`officialBuild=true`）；
5. `python3 scripts/fork_identity.py apply --check-anchors`；
6. `./gradlew prebuild && ./gradlew :app:assemble && ./gradlew :zygote:assemble`；
7. 验收：断言 APK 的 `applicationId == APP_ID`、`versionName == oss-N`，并确认 dex / 模块 zip 里不含上游特征串与框架特征串；
8. 生成模块更新描述文件 `update.json`（`version` / `versionCode` / `zipUrl` / `changelog`）；
9. `gh release create oss-N`，附件为：release 模块 zip、debug 模块 zip、`translators.json`、`update.json`。


手动触发：Actions → **Fork sync** → Run workflow 立即同步；Actions → **Fork release** → Run workflow 立即检查上游新版，可选参数 `release_tag`（指定要跟随的上游标签）与 `force`（勾选后即使本仓库已经镜像过该标签也重新构建、覆盖发布资产）。

两条流水线相互独立：发版流水线自己拉取上游发行版对应的提交，所以即使当天同步还没跑、或同步因为上游冲突失败，发版仍然能正常进行。

关于标签：fork 创建时 GitHub 会把上游的标签一起复制过来，所以本仓库里的 `oss-173` 等标签指向的就是**上游发版时的提交**，本仓库的 release 只是挂在同名标签上。这样 `git checkout oss-173` 得到的是原汁原味的上游代码，构建产物则由该提交 + `fork/fork.env` 唯一决定（可复现）。

### 为什么包名必须是固定值

Android 只允许 `applicationId` 相同、且签名相同的 APK 互相覆盖安装；模块侧又是把管理器的包名（`BuildConfig.APP_PACKAGE_NAME`）编译进代码里、再用「签名校验 + `content://<包名>.ServiceProvider`」跟 App 握手的。所以：

* **包名随机化会直接导致无法覆盖升级**——每次安装都会变成一个新应用，旧版永远升级不上；
* 同时模块会找不到 App（它按编译进去的包名去找，随机包名对不上）；
* 版本号也必须单调递增才能升级，本仓库的 `versionCode` 取自上游提交数，天然递增。

本仓库的做法是：**包名固定为一个与上游毫不相干的常量**（`io.moonlit.quarry`），配合固定的签名密钥库。要更隐蔽只能从别的地方入手（启动器图标/别名、字符串与类名混淆等），而不是包名随机。

### 更新地址

| 位置 | 上游 | 本分支 |
|---|---|---|
| App 内检查更新 `AppConstants.UPDATE_CHECK_URL` | `api.github.com/repos/frknkrc44/HMA-OSS/releases/latest` | `api.github.com/repos/keweiya/HMA-OSS/releases/latest` |
| 模块 `updateJson`（`zygote/build.gradle.kts`） | `https://furkank.net/hma_oss_update_checker.json` | `https://github.com/keweiya/HMA-OSS/releases/latest/download/update.json` |
| App「关于」页 GitHub 链接、帮助链接、翻译链接 | `github.com/frknkrc44/HMA-OSS...` | `github.com/keweiya/HMA-OSS`（帮助链接指向仓库里的 `FORK.md`） |
| 构建期翻译头像抓取（`app/build.gradle.kts`） | 上游 release 资产 | 保留（用户不可见，且必须在首次发版前就可访问） |

`update.json` 作为每个 release 的附件存在，所以 `releases/latest/download/update.json` 这个固定地址永远指向最新版，Magisk 侧不需要改配置。

## 四、首次配置（一次性）

```bash
# 1. 生成签名密钥并打印 secrets
scripts/fork_gen_keystore.sh

# 2. 写入仓库 secrets（四个）
gh secret set FORK_KEYSTORE_B64      --repo <owner>/<repo> --body "$(base64 -w0 fork-keys/fork-release.jks)"
gh secret set FORK_KEYSTORE_PASSWORD --repo <owner>/<repo> --body "<password>"
gh secret set FORK_KEY_ALIAS         --repo <owner>/<repo> --body "fork-release"
gh secret set FORK_KEY_PASSWORD      --repo <owner>/<repo> --body "<password>"

# 3. 跑一次流水线
gh workflow run fork.yml --repo <owner>/<repo>
```

密钥库必须长期保存：换了签名，已安装的旧版本就无法再被覆盖安装。

## 五、本地构建

```bash
cp fork/fork.env /tmp/fork.env          # 备份
git update-ref refs/remotes/origin/master <上游 oss-N 的 SHA>   # 版本号对齐（可选）
python3 scripts/fork_identity.py apply --check-anchors

cat >> local.properties <<'EOF'
officialBuild=true
fileDir=/abs/path/key.jks
storePassword=...
keyAlias=...
keyPassword=...
EOF

./gradlew prebuild && ./gradlew :app:assemble && ./gradlew :zygote:assemble

scripts/fork_verify_artifacts.sh --apk app/build/outputs/apk/release/*.apk --module zygote/build/outputs/magisk/release/*.zip
```

`fork_identity.py apply` 会就地改写工作区，撤销方式：

```bash
git checkout -- . && git clean -fd
```

## 六、反检测处理与残留说明

目标：产物里不留任何能把本分支识别为**上游那套代码**的特征串（上游包名/命名空间、作者、旧模块 id、其它同类 App 的包名等）。项目名本身与上游同名（`HMA-OSS`），因此「HMA-OSS」字样属于本分支自己的品牌，允许出现，但只在下面说明的范围内。处理分三类：

1. **替换**：包名、命名空间、类名（`HMAService` 等）、日志 tag、导出的文件名、模块 ID / 名称 / 描述 / 脚本名、`/data/adb/modules/<id>`、`/data/misc/<prefix>_*`、各种 URL、界面文案里的 `HMA-OSS`/`Zygisk`/`LSPosed`/`隐藏应用列表`。
2. **隐藏**：必须保持原值的字符串（其它 App 的包名，如原版 HMA `com.tsng.hidemyapplist`、Magisk 管理器的 `libmagisk.so`/`.magisk`、检测器 `wu.Zygisk.Detector`、`org.lsposed`）改成 base64 + 运行期 `unhide()` 解码（见 `RootAppsPreset.kt` / `Utils.kt` / `DetectorAppsPreset.kt`），运行时行为完全不变，但产物里不再有明文。
3. **保留**：加载器框架强制要求的拼写，改了模块就无法工作：

**关于「HMA-OSS」这个字样**：本分支的项目名与上游同名，所以产物里出现的 `HMA-OSS` 全部属于本分支自己的身份——仓库 URL（更新检查地址、关于页、帮助链接）与产品字符串（日志 tag、导出的 `HMA-OSS_logs_*.log` / `HMA-OSS_config_*.json` 文件名、界面文案）。验收脚本在计分前会先把「本仓库 slug」（`keweiya/HMA-OSS`）掩码掉，因此它不会与"上游特征串"混为一谈；真正被禁止的仍是上游代码身份：`frknkrc44`、`org.frknkrc44.hma_oss`、`icu.nullptr.hidemyapplist`、`hide_my_applist`、原版作者名、`hua/hmal`、`furkank.net`、`hma_`/`hmaApp`/`hmaoss`、以及被改名的 `HMAService`/`IHMAService`。

| 残留 | 位置 | 为什么不能改 |
|---|---|---|
| `zygisk/<abi>.so` | 模块 zip | Magisk / Zygisk 实现只扫描模块目录下的 `zygisk/` 子目录，这是装载契约 |
| `$ZYGISK_ENABLED` / `$ZYGISK_NAME` / `bin/zygiskd*` | `22-check-framework.sh` | 安装期由框架注入的环境变量与守护进程名 |
| `magisk --sqlite ... 'zygisk'` | `22-check-framework.sh` | Magisk 自身的设置键与命令 |
| `com.v7878.zygisk.*` | `ZygoteEntry.java` 的 import | 第三方加载器库的 API |
| `zygisk { }` 块 | `zygote/build.gradle.kts` | Gradle 插件 DSL，不进入产物 |

结论（可用 `scripts/fork_verify_artifacts.sh` 复现）：**管理器 APK 里上述特征串为 0**；模块 zip 里只剩上表这几项框架契约，且以 `info` 形式逐条打印出来。此外 `Xposed`（用户列表里用于识别 Xposed 模块，你未要求清除）与贡献者姓名字符串（`translators.json`）保持在明文。

另外两点权衡，改的是默认行为，需要时可以还原：

* **关于页署名**：为满足「不留原版特征串」，关于页里的上游作者名 / 原版仓库链接被替换为中性文案（`Upstream` / `Original project (AGPL-3.0)` + 本仓库链接）。**LICENSE.md、CREDITS.md、README、本文件仍完整保留上游署名与许可**，AGPL-3.0 的源码分发与署名要求由仓库侧承担。
* **`sick_mode_notice`**：这条提示原文把另外两个 App 的名字混在一起，无法用词级替换，改为单一英文文案（其余 25 个语种对该条不再覆盖）。

## 七、许可

上游项目以 **AGPL-3.0** 授权（见 `LICENSE.md`）。本分支是对上游的修改版本，因此：

* 保留上游全部版权声明、作者署名（`CREDITS.md`、关于页）与许可证；
* 本分支的修改内容（即上面「fork 层目录」里的全部文件）以同样的 AGPL-3.0 提供，源码就公开发布在本仓库里；
* 发行包与上游包名不同，二者可以共存；请勿把本分支的构建当作官方版本反馈给上游。
