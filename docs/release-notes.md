## v0.1.1-preview

- 指纹录入会读取设备报告的采集次数并显示进度，提示最后一次采集与录入完成后的独立验证。
- 区分取消、超时和 libfprint 温度估算保护。保护仍由 libfprint 执行。
- 管理菜单新增「3 验证测试」。人脸显示匹配的本地样本标签。指纹显示命中的手指及已有备注。当前 Ubuntu 24.04 自带的 fprintd 需要逐项比对，测试时可能需要轻触同一根手指多次。
- 本机已实测录入右手拇指，验证新指纹，并用新菜单识别人脸样本和右手食指。干净系统的完整安装仍待验证。

## 用法

下载并解压整个压缩包，用普通桌面用户运行 `bash scripts/matebook-biometrics.sh`。已经完成部署的用户可直接运行新包里的 `bash scripts/03-manage.sh`。人脸验证测试需要 `bubblewrap` 和 `python3-yaml`。

自动安装适用 Ubuntu 24.04 系 amd64、GNOME/GDM 和 Goodix GXFP5130。安装指纹驱动需要本人设备已有的配对文件。手动配置、限制及恢复见 [配置与验证](https://github.com/yhao1029/matebook-14s-2023-linux/blob/main/docs/setup.md)。
