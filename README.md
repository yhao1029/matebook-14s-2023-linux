# HUAWEI MateBook 14s 2023 的 Linux 生物识别配置

> **2026-11-28：撤回 v0.1.0/v0.1.1 预览发行包。** 用户在全新系统实测发现安装依赖已有配对文件，未达到从零安装目标。当前 main 修订包含尚未完成干净系统端到端验证的新配对路径，请勿视为已验证的一键安装版。[问题与新流程](docs/clean-install-status.md)。

记录在 MateBook 14s 2023（13 代 Intel Core i9、HKFG-XX 系列）上使用 Linux 指纹和红外人脸的经验。Zorin OS 18.1、GNOME/GDM、amd64、内核 7.0.0-43-generic 的原部署已实测锁屏与 sudo。两种识别并行，任一成功即可通过，原密码仍可使用。

| 部件 | 本次实测 |
| --- | --- |
| 指纹 | Goodix GXFP5130，ACPI/eSPI，社区 gxfp 内核驱动 + libfprint + fprintd |
| 人脸 | 原生 GREY 640×360 红外摄像头，Biopass 1.6.0 |
| 认证 | sudo、GNOME 锁屏分别测试了只用人脸、右手食指和密码 |
| 首版脚本适用范围 | Ubuntu 24.04 系 amd64 + systemd + GNOME/GDM。具体机型、内核头文件、Secure Boot 和摄像头仍需检查 |

**这里的 Windows Hello 指 Windows 里同类的使用体验。** Linux 需要重新录入自己的样本。红外人脸存在检查不能证明活体识别能力，样本为本机裁剪照片。本次没有验证照片或视频防伪、冷启动及休眠恢复。

- [手动配置、测试和恢复](docs/setup.md)
- [发行状态（等待干净系统实测）](https://github.com/yhao1029/matebook-14s-2023-linux-biometric/releases)
- [总菜单](scripts/matebook-biometrics.sh)
- [准备](scripts/01-prepare.sh) · [安装后端](scripts/02-install.sh) · [管理数据](scripts/03-manage.sh) · [卸载](scripts/04-uninstall.sh)

下载整套文件后，在 `scripts/` 目录用普通桌面用户运行 `bash matebook-biometrics.sh`。全流程默认录一个人脸样本和右手食指。单项入口依赖同目录的辅助脚本，请一起下载。修订版提供导入本设备有效密钥与生成新配对两条路径；后者写入共享传感器，会影响 Windows/其他 Linux 的旧配对，必须单独确认。没有可公开的通用密钥模板。不要在已有正常配对的设备上仅为测试而重新配对。

脚本处于预览阶段，原部署的实机结果与本仓库脚本的验证范围分开记录。请先阅读手动流程。Arch、Fedora、Debian 原版、KDE、Xfce 的软件包、权限和登录管理器有差异，当前只提供参考思路。
