# 伪装标识（Branding）

本 fork 发布出去的 APK / 模块不使用上游身份（`org.frknkrc44.hma_oss`、`hma_oss_zygisk`），
而是使用一套随机化过的身份，构建前由脚本自动改写源码树。

当前身份与 [`oss-173`](https://github.com/keweiya/HMA-OSS/releases/tag/oss-173) 出厂值一致：

| 项目 | 值 |
| --- | --- |
| 应用包名（applicationId） | `io.moonlit.quarry` |
| 桌面名称 | `Quarry` |
| 桌面图标 | `app/src/main/res/mipmap-*/brand_icon_foreground.png`（脚本按种子生成） |
| Magisk/KSU 模块 id | `quarry`（`/data/adb/modules/quarry`） |
| 运行状态目录 | `/data/misc/quarry_state_*` |
| 模块启动脚本 | `/data/adb/.../quarry.sh` |

因此**从 oss-173 升上来的机器可以直接覆盖安装**（前提：`versionCode` 递增 + 用同一把签名密钥签名）。

## 文件

| 文件 | 作用 |
| --- | --- |
| `branding.properties` | 唯一的身份配置源 |
| `scripts/apply_branding.py` | 按配置改写整棵源码树并生成图标（幂等，`--check` 只校验） |
| `scripts/roll_branding.py` | 重新随机一套身份 / 只换图标 |

## 构建流程

`.github/workflows/main.yml` 在 `./gradlew` 之前执行：

```bash
python3 scripts/apply_branding.py         # 改包名 / 标签 / 模块 id / 状态目录 / 图标
python3 scripts/apply_branding.py --check # 有残留就 fail
```

改写内容（与 oss-173 产物对齐）：

```
org.frknkrc44.hma_oss          -> <appId>
icu.nullptr.hidemyapplist      -> <appId>.legacy
/data/misc/hide_my_applist_    -> /data/misc/<codename>_state_
hmaoss.sh                      -> <codename>.sh
hma_oss_zygisk                 -> <codename>
app_name "HMA-OSS"             -> <appLabel>
```

同时会搬动 `java/`、`aidl/` 下的包目录，改写 `proguard` 规则、`AndroidManifest.xml`、
`zygote/build.gradle.kts` 里的模块信息，以及应用内检查更新用的仓库地址。

本地想复现同样的产物：

```bash
python3 scripts/apply_branding.py && ./gradlew :app:assemble :zygote:assemble
```

（本地构建完记得 `git checkout -- .`，脚本是直接改工作区的。）

## 覆盖更新的三条硬性条件

1. **包名 / codename 不变**：`appId`、`codename` 一旦改动，新包会以另一个应用身份安装，不会覆盖旧包。
   真要换身份请用 `python3 scripts/roll_branding.py`，并接受"变成新应用"的后果。
2. **versionCode 递增**：`versionCode = git commit 数 + 0x6F7373`，跟着上游提交走，正常情况下自动递增。
   当前 master 计数比 oss-173 大，所以能升级。
3. **同一签名密钥**：CI 用 `KEY_STORE / KEY_STORE_PASSWORD / ALIAS / ALIAS_KEY_PASSWORD` 四个 secret 签名。
   缺任何一个，`main.yml` 会在构建开始前直接报错退出，而不是产出一个装不上去的包。

## CI 自检

`main.yml` 的 "Verify branded APK" 步骤会用 `aapt2 dump badging` 断言：

- `package: name='<appId>'`
- `application-label:'<appLabel>'`
- `zygote/build.gradle.kts` 里 `id = "<codename>"`

任何一条不满足（比如上游合并把改名冲掉了）都会让流水线立刻失败，而不是默默发出一个上游身份的包。
