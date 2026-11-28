# v0.2.0 · 干净 Zorin 系统实测版

机主在同一台 HUAWEI MateBook 14s 2023 的另一套干净 Zorin OS 中实际安装测试，确认本轮修订完全可用。原有 Windows Hello 配对保留，不执行传感器重新配对。

- 完整补齐构建依赖，修正 gudev 漏装及 doctest/CMake 预检误报。
- 授权后只读尝试获取本机 Windows 通讯密钥：兼容 WINDOWS/Windows 等路径大小写、推荐分区选择、隔离只读视图；失败说明原因并提供 Windows 本地导出指引。也支持手动导入本设备有效的 32 字节二进制密钥。
- 指纹录入进度、独立验证、多手指管理及人脸/指纹验证测试。
- 人脸录入上方为前置彩色预览，下方为实际红外人脸裁剪；候选冻结后可确认、重拍或取消。
- 支持仅人脸、仅指纹或两者并行；补录另一种后可重新启用，密码回退保留。
- 所有确认提示使用小写 yes，兼容大写输入。

## 下载与运行

下载附件 matebook-biometrics-v0.2.0.tar.gz 和 SHA256SUMS，放在同一目录。执行 `sha256sum -c SHA256SUMS` 校验，然后解压完整压缩包。在解压目录以普通桌面用户执行：

```bash
bash scripts/matebook-biometrics.sh
```

首次安装选择 a 或按 1 → 2 → 3 → 5 分步执行；已有安装不要重复安装后端，管理数据选 3，更新启用选 5。需要管理员操作时由 sudo 提示认证。

适用 Ubuntu 24.04 系 amd64、GNOME/GDM、GXFP5130。Secure Boot 的模块签名未自动处理。Windows 缓存可读/可解密不是所有环境都保证成立；BitLocker 或不兼容保护可能仍需本人导出密钥。未宣称其他发行版、冷启动/休眠恢复、照片/视频防伪或卸载全过程已实测。样本及密钥只保存在本机，不包含在发行包中。

完整步骤：https://github.com/yhao1029/matebook-14s-2023-linux-biometric/blob/main/docs/setup.md
