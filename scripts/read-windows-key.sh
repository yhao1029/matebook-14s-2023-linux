#!/usr/bin/env bash
# Must run in a NEW private mount namespace; only the temporary bind is remounted.
set -euo pipefail
umask 077
original_ns=${1:?parent namespace required}
source_root=${2:?Windows root required}
python=${3:?Python required}
reader=${4:?reader required}
format_helper=${5:?format helper required}
output=${6:?output required}
[[ $(id -u) == 0 ]] || { echo '只读视图需要管理员权限。' >&2; exit 1; }
[[ $(readlink /proc/self/ns/mnt) != "$original_ns" ]] || {
    echo '未进入独立挂载空间，拒绝创建视图。' >&2; exit 1;
}
view=$(mktemp -d /run/matebook-windows-ro.XXXXXXXX)
mounted=false
cleanup() {
    if $mounted; then umount -- "$view" || true; fi
    rmdir -- "$view" || true
}
trap cleanup EXIT
mount --bind -- "$source_root" "$view" || {
    echo '无法创建 Windows 临时视图；未改原分区。' >&2; exit 1;
}
mounted=true
mount -o remount,bind,ro,nosuid,nodev,noexec -- "$view" || {
    echo '无法将临时视图设为只读；停止读取。' >&2; exit 1;
}
options=$(findmnt -n -o VFS-OPTIONS --mountpoint "$view")
[[ ,$options, == *,ro,* ]] || { echo '临时视图只读校验失败。' >&2; exit 1; }
echo '已建立隔离的只读视图；原 Windows 挂载状态不变。'
"$python" "$reader" --recover-existing-communication-key --windows-root "$view" \
    --format-helper "$format_helper" --output "$output"
