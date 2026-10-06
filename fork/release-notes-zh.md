# 发行说明模板（中文）
#
# 占位符由 .github/workflows/fork-release.yml 渲染：
#   {{TAG}} {{SHA}} {{APP_ID}} {{MODULE_ID}} {{MODULE_NAME}} {{PROJECT_NAME}}
#   {{UPSTREAM_SLUG}} {{REPO}} {{UPSTREAM_NOTES_ZH}} {{UPSTREAM_NOTES_SOURCE}}
#   {{UPSTREAM_NOTES}}   (英文原文，折叠在末尾供对照)
#
# 发布时作为 release 正文（中文说明），并同步展示在 App 的更新弹窗里。

> 本发行版是本仓库对上游 [{{UPSTREAM_SLUG}}](https://github.com/{{UPSTREAM_SLUG}}) 发行版 `{{TAG}}` 的重新构建，
> 代码取自上游该次发行时的提交 `{{SHA}}`，未做任何功能改动。

| 项目 | 值 |
|---|---|
| 版本号 | `{{TAG}}` |
| 对应的上游提交 | `{{SHA}}` |
| 应用包名（applicationId） | `{{APP_ID}}` |
| 模块 ID | `{{MODULE_ID}}`（{{MODULE_NAME}}） |
| 更新来源 | [本仓库最新版](https://github.com/{{REPO}}/releases/latest) |

## 安装方法

1. 下载下面的 **release 模块 zip**（`{{PROJECT_NAME}}-{{TAG}}-release.zip`）。
2. 在 Magisk / KernelSU 管理器里「从本地安装」该 zip；安装脚本会自动装好配套的管理器 App（若已有旧版会直接覆盖升级）。
3. 重启手机，打开管理器 App 确认状态为「系统服务已加载」。

如果你是第一次安装：本构建的包名与上游不同（`{{APP_ID}}`），可以和上游版本共存，但**不建议同时启用两个**同类模块，否则会互相干扰。

## 更新方式

- App 内「检查更新」和 Magisk 内的模块更新都指向本仓库，检测到新版会直接提示。
- 也可以直接在本仓库的 Releases 里下载最新 `zip` 覆盖安装。

## 关于本构建

- 与上游的差异仅限发行身份：应用包名、模块 ID、更新地址、以及产物里的上游特征串（详见仓库根目录的 `FORK.md`）。
- 本仓库每天自动同步上游代码，并在上游发布新版本时自动重新构建、发布同名版本。
- 反馈问题请提到本仓库；请勿把本构建的问题反馈给上游。

## 上游更新说明

{{UPSTREAM_NOTES_ZH}}

<sub>以上中文由本仓库处理（{{UPSTREAM_NOTES_SOURCE}}）；如与英文原文有出入，以英文原文为准。</sub>

<details>
<summary>英文原文对照</summary>

{{UPSTREAM_NOTES}}

</details>
