> **本仓库是 [frknkrc44/HMA-OSS](https://github.com/frknkrc44/HMA-OSS) 的第三方构建分支。**
>
> 上游代码保持原样，本分支通过自动化流水线定期同步上游代码，并在上游发布新版本时用同样的版本号重新构建、发布本仓库的 release。
> 重新构建的产物使用独立的发行身份（应用包名/模块 ID/更新地址均与上游不同，两个版本可以共存），全部改动集中在 `fork/fork.env` 与 `scripts/`。
> 完整说明见 [FORK.md](FORK.md)。
>
> This is a third-party build branch of upstream. CI keeps it in sync with upstream and mirrors every upstream release with a distinct package identity. See [FORK.md](FORK.md).

---

<div align="center">
  <h2>HMA-OSS</h2>

  <img src="HideMyAss-OSS.svg" alt="HMA-OSS Logo" style="max-width:360px;width:60%;height:auto;">

  <p>
    <a href="https://github.com/frknkrc44/HMA-OSS" style="text-decoration:none">
      <img src="https://img.shields.io/github/stars/frknkrc44/HMA-OSS?label=Stars&logo=github">
    </a>
    <a href="https://github.com/frknkrc44/HMA-OSS/actions" style="text-decoration:none">
      <img src="https://img.shields.io/github/actions/workflow/status/frknkrc44/HMA-OSS/main.yml?branch=master&logo=github">
    </a>
    <a href="https://github.com/frknkrc44/HMA-OSS/releases/latest" style="text-decoration:none">
      <img src="https://img.shields.io/github/v/release/frknkrc44/HMA-OSS?label=Release">
    </a>
    <a href="https://github.com/frknkrc44/HMA-OSS/releases/latest" style="text-decoration:none">
      <img src="https://img.shields.io/github/downloads/frknkrc44/HMA-OSS/total">
    </a>
    <a href="https://t.me/aerathfuns" style="text-decoration:none">
      <img src="https://img.shields.io/badge/Telegram-Channel-blue.svg?logo=telegram">
    </a>
    <a href="https://choosealicense.com/licenses/gpl-3.0/" style="text-decoration:none">
      <img src="https://img.shields.io/github/license/frknkrc44/HMA-OSS?label=License">
    </a>
  </p>
</div>

---

- **English**
- [中文（简体）](README_zh_CN.md)
- [Türkçe](README_tr.md)
- [日本語](README_ja.md)
- [Indonesia](README_id.md)
- [Português](README_pt.md)
- [Français](README_fr.md)

## About this module

Although it's bad practice to detect the installation of specific apps, not every app using root provides random package name support. In this case, if apps related to root (such as Fake Location and Storage Isolation) are detected, it is tantamount to detecting that the device is rooted.

Additionally, some apps use various loopholes to acquire your app list, in order to use it as fingerprinting data or for other nefarious purposes.

This module can work as an Zygisk module to hide apps or reject app list requests.

## About HMA-OSS

https://github.com/frknkrc44/HMA-OSS/wiki

## I want to contribute translation
You can contribute translation [here](https://crowdin.com/project/frknkrc44-hma-oss).

## Update log
[Reference to the commits page](https://github.com/frknkrc44/HMA-OSS/commits)
