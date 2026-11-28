#!/usr/bin/env bash
# Writes only a Linux-side imported key; never mounts or writes Windows/sensor.
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
        read -r -p '是否允许以上本机读取？输入 YES: ' consent
        [[ $consent == YES ]] || fail '未获授权，停止指纹安装。'
        echo '只检查已经挂载的卷，不自动挂载、解锁、修复或更改 Windows 分区。'
        findmnt -rn -o TARGET,FSTYPE,OPTIONS | grep -E 'ntfs|fuseblk|bitlocker' || true
        mapfile -t roots < <(python3 -c '
import json, pathlib, subprocess
data=json.loads(subprocess.check_output(["findmnt", "--json", "-o", "TARGET,FSTYPE"]))
def walk(rows):
    for row in rows:
        p=pathlib.Path(row["target"])
        if row.get("fstype") in ("ntfs", "ntfs3", "fuseblk") and (p/"Windows").is_dir() and (p/"ProgramData").is_dir():
            print(p)
        walk(row.get("children", []))
walk(data.get("filesystems", []))')
        if [[ ${#roots[@]} == 1 ]]; then
            root=${roots[0]}
            echo "识别到 Windows 卷：$root"
            read -r -p '确认读取这个本机 Windows 卷？输入 YES: ' consent
            [[ $consent == YES ]] || fail '未确认 Windows 来源，已停止。'
        else
            read -r -p '输入 Windows 分区的挂载根目录（含 Windows 和 ProgramData 的目录）: ' root
        fi
        [[ -d "$root" ]] || fail '未找到挂载目录：可能尚未挂载或 BitLocker 尚未由本人解锁。'
        for path in Windows/System32/config/SYSTEM Windows/System32/config/SECURITY ProgramData/Goodix/Goodix_Cache.bin; do
            sudo test -f "$root/$path" || fail "缺少 $path：可能选错卷、没有 Goodix 缓存，或驱动采用不同缓存格式。"
            options=$(findmnt -n -o OPTIONS --target "$root/$path")
            [[ ,$options, == *,ro,* ]] || fail 'Windows 卷不是只读挂载；停止，不自动重新挂载。'
        done
        envdir="${XDG_CACHE_HOME:-$HOME/.cache}/matebook-biometrics/key-reader-venv"
        if [[ ! -x "$envdir/bin/python" ]]; then
            read -r -p '需要 Linux 本地 DPAPI 解析依赖。允许建立隔离环境并安装 impacket==0.13.0？输入 YES: ' consent
            [[ $consent == YES ]] || fail '未安装解析依赖。'
            python3 -m venv "$envdir" || fail '缺少 python3-venv，请先安装该软件包。'
            "$envdir/bin/python" -m pip install 'impacket==0.13.0' || fail '解析依赖下载或安装失败。'
        fi
        "$envdir/bin/python" -c 'import importlib.metadata; assert importlib.metadata.version("impacket") == "0.13.0"' || fail '解析依赖版本不匹配。'
        private=$(sudo mktemp -d /run/matebook-key.XXXXXXXX)
        trap 'sudo rm -f -- "$private/psk.bin"; sudo rmdir -- "$private"' EXIT
        if ! sudo "$envdir/bin/python" "$here/recover-windows-key.py" \
            --recover-existing-communication-key --windows-root "$root" \
            --format-helper "$source_tree/userspace/tools/unseal_bb010002.py" --output "$private/psk.bin"; then
            fail '离线 DPAPI 解密失败：当前支持的机器范围保护/主密钥/缓存完整性校验未通过；不会修改 Windows 以尝试修复。'
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
