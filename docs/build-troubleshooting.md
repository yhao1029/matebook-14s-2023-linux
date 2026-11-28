# 构建阶段的 gudev 缺失

日志 `ERROR: Problem encountered: udev is required for SPI support`、`gudev-1.0 found: NO` 表示缺少 `libgudev-1.0-dev`，不是指纹器不支持。

固定版本上游 `libfprint/meson.build` 把 gxfp 映射为依赖 udev helper，helper 无条件检查 gudev。`-Dudev_rules=disabled` 只禁止安装规则，不会取消编译依赖。

新版已把该包加入准备清单，菜单 2 也会先检查依赖，经确认安装缺少的软件包，然后检查 pkg-config。失败会在获取密钥、编译及修改认证前停止。

更新整套 scripts 后可直接选择菜单 2；缺少包时输入 YES。也可手动 `sudo apt-get install --no-remove libgudev-1.0-dev` 后重试。不要继续选录入/启用：构建没有通过，后端还没有安装。

本配置关闭图形示例和 introspection，因此日志中的 cairo 和 gobject-introspection 缺失不是本次致命错误；不要为消除所有可选依赖提示随意更改构建选项。

进入 Meson 阶段说明安装程序走过了密钥获取步骤，但不能据此证明该密钥能与传感器握手，也不能证明整体安装成功。完整验收仍需后端安装、录入和认证实测。
