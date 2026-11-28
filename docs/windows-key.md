# 保留 Windows Hello 的配对密钥获取流程

通讯密钥不是指纹模板。此方案不重新配对、不上传 provisioning blob、不删除 Windows Hello 数据，不调用 Windows 指纹重置或重新录入功能。Linux 人脸和指纹仍需单独录入。

## Linux 安装菜单

运行 `bash scripts/matebook-biometrics.sh`，选择准备、安装后端。后端安装前会询问是否有 Windows、Windows 指纹是否已配置，再选择“授权只读尝试”或“手动导入”。拒绝授权就终止，不会改用重配对。

离线读取明确涉及 Windows 的 SYSTEM/SECURITY 注册表中的 DPAPI_SYSTEM、系统主密钥和 Goodix 缓存；这些属于敏感数据，仅在本机内存解析，不打印或上传。安装依赖需要联网，但不会传送上述文件。

脚本按编号列出已挂载 NTFS 卷，检查 SYSTEM、SECURITY 和 Goodix 缓存的文件特征，把完整候选排在前面并设为回车默认项；最终仍要求输入 YES 确认来源。也提供 m 手填挂载根目录、q 取消。没有完整候选就不设默认项。磁盘列表同时显示未挂载分区，未挂载/加密分区不能直接选来读取。

路径每一级都兼容大小写，包括 Windows/WINDOWS、System32/SYSTEM32、ProgramData、缓存文件与主密钥文件名；发现大小写冲突或链接越界时停止。应选择分区根目录，不是 WINDOWS 文件夹，也不是 SYSTEM 文件本身。

只接受已有的只读挂载；不会自动解锁 BitLocker、挂载、修复 NTFS、删除休眠文件或关闭 Windows 安全功能。可写挂载会明确停止，推荐采用下面的 Windows 导出方法，不要随便强制挂载。

## Windows 本地导出（离线读取失败时）

1. 正常重启进入这台电脑的 Windows。不要重置 PIN、删除指纹或重新配置 Hello；保留当前状态。
2. 从本项目整套下载文件中取出 `scripts/export-windows-key.py`，放在本人可控的本地目录。脚本来自上游固定版本的缓存解密工具，使用 Windows 自带 CryptUnprotectData，不调用指纹设备。
3. 若没有 Python 3，安装 python.org 的 Windows Python。打开 PowerShell，运行 `py -3 --version` 确认；若没有 py 启动器则使用 `python`。
4. 切换到脚本目录，例如 `cd "$env:USERPROFILE\Downloads\matebook-biometrics\scripts"`，把目录替换为实际解压目录。
5. 执行 `py -3 .\export-windows-key.py --out-psk .\psk_raw32.bin`。默认读取 `%ProgramData%\Goodix\Goodix_Cache.bin`。如权限不足，才用“以管理员身份运行”的 PowerShell，在同一目录重试同一命令；不运行 SYSTEM 服务或计划任务。
6. 成功会提示已写入 32 字节文件。可用 `(Get-Item .\psk_raw32.bin).Length` 检查长度，不要用十六进制查看器输出内容。
7. 通过本人控制的移动存储带到 Linux。安装菜单选“手动导入”，填 Linux 上的完整路径。它只是本地文件导入，不上传。
8. 成功安装并确认有效后，自行妥善保管或删除移动存储和 Windows 导出副本。不要放入聊天、公开仓库、网盘共享或截图。

找不到缓存：可能未使用本款 Goodix 驱动、缓存路径不同，或没有既有配对。可以使用 `--cache "实际的 Goodix_Cache.bin 路径"` 指定本人已确认的文件，不要猜测或提交整个 Windows 目录。

DPAPI 失败：当前 Windows 上下文、系统保护或缓存格式可能不兼容。脚本会停止；管理员身份也不保证成功。不要关闭安全软件、重置 Hello、接管密钥目录权限或使用网上的通用密钥。此时没有承诺可完成安装，需进一步研究。

成功导出和长度正确也不能证明缓存与传感器当前配对一致。若 Linux 握手失败，应停止并保留原 Windows 状态；不能通过自动重新配对来掩盖失败。

这条新安装流程尚未完成干净系统端到端验收，当前只提供源码测试，不恢复旧版发行包。
