#!/usr/bin/env bash
# Writes only a Linux-side key; reads Windows through a private read-only bind.
set -euo pipefail
umask 077
here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source_tree=${1:?source tree required}
output=${2:?output required}
fail() { echo "$*" >&2; echo '下一步：阅读 docs/windows-key.md，在 Windows 本地导出后回 Linux 手动导入。' >&2; exit 1; }
read -r -p '本机是否保留 Windows 双系统？[y/N] ' windows
case "$windows" in
 y|Y)
    read -r -p 'Windows 指纹目前是否已经配置并能正常使用？[y/N] ' configured
    [[ $configured == y || $configured == Y ]] || echo 'Windows 未配置过时可能没有 Goodix 缓存；不会要求重新录入或重置 Windows Hello。'
    read -r -p '1 授权只读尝试本机 Windows；2 手动导入本机密钥；回车取消: ' mode
    case "$mode" in
      1)
        echo '会读取 Goodix_Cache.bin、SYSTEM/SECURITY 中 DPAPI_SYSTEM 和对应系统主密钥，仅解密通讯密钥；不读取 SAM、指纹/人脸模板，不上传。'
        read -r -p '是否允许以上本机读取？输入 yes: ' consent
        [[ ${consent,,} == yes ]] || fail '未获授权，停止指纹安装。'
        echo '只选择已经挂载的卷；将在独立挂载空间建立临时只读视图，不改变原挂载，不解锁或修复 Windows。'
        root=$(python3 "$here/windows_volume.py" --choose) || fail '未选定可用 Windows 分区。'
        python3 "$here/windows_volume.py" --files "$root" >/dev/null || fail 'Windows 文件检查失败。'
        for command in unshare mount umount findmnt readlink; do
            command -v "$command" >/dev/null || fail "缺少隔离视图工具：$command（由 util-linux/coreutils 提供）。"
        done
        envdir="${XDG_CACHE_HOME:-$HOME/.cache}/matebook-biometrics/key-reader-venv"
        if [[ ! -x "$envdir/bin/python" ]]; then
            read -r -p '需要 Linux 本地 DPAPI 解析依赖。允许建立隔离环境并安装 impacket==0.13.0？输入 yes: ' consent
            [[ ${consent,,} == yes ]] || fail '未安装解析依赖。'
            python3 -m venv "$envdir" || fail '缺少 python3-venv，请先安装该软件包。'
            "$envdir/bin/python" -m pip install 'impacket==0.13.0' || fail '解析依赖下载或安装失败。'
        fi
        "$envdir/bin/python" -c 'import importlib.metadata; assert importlib.metadata.version("impacket") == "0.13.0"' || fail '解析依赖版本不匹配。'
        private=$(sudo mktemp -d /run/matebook-key.XXXXXXXX)
        trap 'sudo rm -f -- "$private/psk.bin"; sudo rmdir -- "$private"' EXIT
        original_ns=$(readlink /proc/self/ns/mnt)
        if ! sudo unshare --mount --propagation private /bin/bash "$here/read-windows-key.sh" \
            "$original_ns" "$root" "$envdir/bin/python" "$here/recover-windows-key.py" \
            "$source_tree/userspace/tools/unseal_bb010002.py" "$private/psk.bin"; then
            fail '只读视图或离线解密未完成：请看上方具体错误。可能是系统禁用挂载命名空间、权限不足，或 DPAPI/缓存格式不受支持；不会改用可写读取或重新配对。'
        fi
        sudo cat "$private/psk.bin" > "$output"
        ;;
      2) mode=manual ;;
      *) fail '已取消。' ;;
    esac
    ;;
 *) mode=manual ;;
esac
if [[ ${mode:-} == manual ]]; then
    read -r -p '输入本设备当前有效的 32 字节二进制密钥文件路径（回车取消）: ' key
    [[ -f "$key" && $(stat -Lc %s -- "$key") == 32 ]] || fail '没有有效的 32 字节文件；不会创建或上传新配对。'
    cat -- "$key" > "$output"
fi
[[ $(stat -Lc %s -- "$output") == 32 ]] || fail '输出长度检查失败。'
chmod 600 "$output"
echo '本机密钥已导入 Linux 私有文件，未显示内容。'
