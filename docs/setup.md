# 手动配置与验证

> 更新：脚本已增加经授权只读尝试 Windows 配对缓存与失败后的本地导出引导。详见 [Windows 密钥获取](windows-key.md)。下文手动流程中的“仅接收已有文件”指手动导入方式；安装脚本现已增加只读获取选项，不会重新配对传感器。

## 1. 确认硬件，准备依赖

在普通用户终端执行：

```bash
cat /etc/os-release
uname -r
cat /sys/class/dmi/id/product_name
ls /sys/bus/acpi/devices/GXFP5130:00
v4l2-ctl --list-devices
ls -l /dev/v4l/by-path/
```

用 `v4l2-ctl -d <摄像头节点> --list-formats-ext` 确认哪一个提供原生 `GREY`。记录稳定的 by-path 入口，机器之间端口号可能不同。指纹传感器通过 ACPI 枚举，`lsusb` 找不到并不能说明没有指纹硬件。

Ubuntu 24.04 系依赖：

```bash
sudo apt update
sudo apt install git curl ca-certificates build-essential cmake pkg-config meson ninja-build \
    dkms mokutil libglib2.0-dev libgusb-dev libopencv-dev doctest-dev libpixman-1-dev \
    python3-gi python3-yaml bubblewrap fprintd v4l-utils pamtester zenity
sudo apt install "linux-headers-$(uname -r)"
```

从公开项目获取固定版本，先检查项目说明和脚本中的 SHA-256。也可用 [01-prepare.sh](../scripts/01-prepare.sh) 完成这步。指纹源码取 Metrohan 项目的提交 `5e8c91c6b63da472dad946fbfdad2f43bca21eb4`，另准备 Mbed TLS 3.6.5 和 Biopass 1.6.0 amd64 包。Secure Boot 开启的机器应另走模块签名与 MOK 管理。预览脚本会停止。

## 2. 准备本机配对文件并安装后端

Goodix 握手需要与传感器目前配对状态一致的 PSK。已有 Windows 配对的机器请先阅读上游关于保留原配对的说明，并在本人机器上准备该设备的合法 32 字节二进制配对文件。它是通讯密钥。指纹和人脸模板需要另录。请勿把此文件、Windows 凭据或模板放到仓库或日志中。本文流程仅接收已有配对文件，不执行 Windows 数据库读取或传感器重新配对。另见 [上游 PSK 说明](https://github.com/Metrohan/gxfp5130-linux/blob/5e8c91c6b63da472dad946fbfdad2f43bca21eb4/userspace/PSK.md)。

以下是实际安装顺序，自动化入口为 [02-install.sh](../scripts/02-install.sh)。

1. 用户目录中用 CMake 将 Mbed TLS 3.6.5 编译成带 PIC 的静态库并安装到私有构建目录。Ubuntu 24.04 的常规 2.x 开发包无法满足此源码使用的 3.x 接口。
2. 将该目录的 `lib/pkgconfig` 加入 `PKG_CONFIG_PATH`，用 Meson 构建社区 libfprint。关键参数见下面。Ubuntu OpenCV 4 的构建补充 `<set>` 并明确使用 core、imgproc、features2d、imgcodecs 头文件。脚本中有完整命令。
3. 用 `kernel/dkms.conf` 将源码放到对应的 `/usr/src/gxfp-<版本>`，运行 `sudo dkms install -m gxfp -v <版本> -k "$(uname -r)"`，再用 `sudo modprobe gxfp` 加载。预览脚本使用 `0.1.0-guide` 这个独立的 DKMS 版本。
4. 将编译好的库以 SONAME `libfprint-2.so.2` 放入私有目录。将本机配对文件安装到 `/var/lib/fprint/gxfp/psk_raw32.bin`（目录 0700，文件 0600，root 所有）。配置 fprintd 专用 systemd drop-in。照抄片段前请确认私有库确实在该路径。
5. 运行 `sudo systemctl daemon-reload`、`sudo systemctl restart fprintd` 和 `fprintd-list "$(id -un)"`。应见 Goodix GXFP5130 设备。将 `gxfp` 写入独立的 modules-load.d 文件可在启动时加载。
6. 备份 PAM 后用 apt 安装已校验的 Biopass deb。项目的包安装程序会刷新 PAM，安装后要比对原文件。先保持内置的 Biopass PAM profile 禁用。

```bash
meson setup build-gxfp libfprint -Ddrivers=gxfp -Ddoc=false \
    -Dintrospection=false -Dgtk-examples=false -Dudev_rules=disabled -Dudev_hwdb=disabled
meson compile -C build-gxfp
```

```ini
[Service]
UMask=0077
Environment=LD_LIBRARY_PATH=/opt/matebook-biometrics-guide/lib
Environment=FP_GXFP_PSK=/var/lib/fprint/gxfp/psk_raw32.bin
DeviceAllow=/dev/gxfp rw
```

## 3. 录入并验证

```bash
sudo fprintd-enroll -f right-index-finger "$(id -un)"
fprintd-verify -f right-index-finger "$(id -un)"
```

每次抬起后用指腹中间轻触，小幅平移或转动。再用未录入的手指验证，应拒绝。使用 [03-manage.sh](../scripts/03-manage.sh) 可按 1–9 和 0 选择十个手指，查看状态、逐项删除、重录或添加本地备注。fprintd 的指位是固定的，备注绑定标准手指。替换会先删除旧记录，录入失败时可用原密码重试。

在 Biopass GUI 或管理脚本中选择红外视频节点并添加本人样本。管理脚本默认下载项目的 YOLOv8n Face、EdgeFace S 通用模型，并校验发布包摘要。Biopass 把裁剪人脸保存在当前用户的私有目录，可以查看标签、改名、删除和新增姿态。同行发布时避免附上人脸照片或生物特征文件。不要把别人的样本录为自己的登录凭据。

管理脚本的「验证测试」可单独验证生物样本。人脸会显示 Biopass 匹配的样本标签。指纹会逐项检查已录入的手指，可能需要用同一根手指轻触多次。已有安装可直接运行新版管理脚本。人脸验证需要 `bubblewrap` 和 `python3-yaml`，测试不进入系统认证流程。

## 4. 并行认证与验证

将 Biopass 的策略设为 parallel，启用 face 和 fingerprint。GNOME 需要仅由 `gdm-fingerprint` 发起并行检测，`gdm-password` 提供独立的密码输入，避免两条会话抢传感器。忽略 `gdm-password`、`sshd`。本预览脚本还排除 Polkit；原机的全局 profile 试验与此处的限域安装不同。

先开一个保留的管理员终端并做好 PAM 备份。建立独立 PAM 测试服务，先测试只看镜头、遮镜头只碰指纹、两者缺席后输密码。确认三种方式真实通过再启用正式流程。预览脚本的 `enable` 做这一阶段，并安排十分钟自动撤销。正式配置将 `gdm-fingerprint` 中的 `auth required pam_fprintd.so` 换为 `auth required libbiopass_pam.so`，在 `sudo` 的 `@include common-auth` 前插入 `auth sufficient libbiopass_pam.so`，原密码规则由后续 common-auth 处理。勿同时打开全局指纹或 Biopass profile。

在新终端运行 `sudo -k /usr/bin/true`，分别验证人脸、遮住摄像头后的已录入指纹和密码。锁屏进入解锁界面重复三次。结果正常才确认取消自动恢复计时器。PAM 改动较容易影响登录，请从现有管理员终端恢复。Biopass 的终端回退会等生物检测结束，原版 helper 外层超时为 60 秒。

## 5. 故障和恢复

- 找不到传感器时先检查 ACPI、内核头文件、`dkms status`、`modinfo gxfp`、`journalctl -u fprintd`。更新内核后需要确认 DKMS 重建结果。
- 如果录入返回 `enroll-unknown-error`，查看 `journalctl -u fprintd -n 30`。若日志显示 `Device disabled to prevent overheating`，libfprint 的温度估算保护已触发。先停止指纹验证和录入，让读取器空闲几分钟再试。保护依据工作时间估算，单凭这条日志无法确认硬件的实际温度。
- TLS 校验失败优先确认本机配对是否匹配。双系统使用时避免重置传感器配对。
- 光线、盖板遮挡和设备占用会影响红外采集。早期 Howdy/dlib 实验中，暗帧过滤放宽后才稳定看到脸。Biopass 使用不同引擎，请独立测试。
- 只恢复认证可运行 `sudo /bin/bash /var/lib/matebook-biometrics-guide/restore.sh pam`。完整撤销本项目的后端用 [04-uninstall.sh](../scripts/04-uninstall.sh)。卸载前可按需用管理菜单逐个清除样本；卸载默认保留个人样本和通用依赖，避免删除其他软件使用的数据。手动安装的部分用各自备份撤销。
- 发布脚本新增 DKMS 构建、安装、PAM 试验和恢复路径。原部署已经用实际用户测试 sudo 和锁屏。本预览版本的检查见发行说明。

参考了 [Metrohan 的 GXFP5130 项目](https://github.com/Metrohan/gxfp5130-linux)、[其他 MateBook 实测讨论](https://github.com/Metrohan/gxfp5130-linux/issues/20)、[Biopass PAM 文档](https://github.com/phucvinh57/biopass/blob/1.6.0/docs/PAM.md)、[Biopass 红外相机指南](https://github.com/phucvinh57/biopass/blob/1.6.0/docs/IR%20camera.md) 和 [Howdy](https://github.com/boltgolt/howdy)。Fedora 和 Arch 可参考 GXFP5130 的上游发行版说明，KDE/Xfce 的登录和锁屏配置应分别按其显示管理器和锁屏程序验证。
