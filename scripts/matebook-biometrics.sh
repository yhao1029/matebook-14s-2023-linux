#!/usr/bin/env bash
# MateBook 14s 2023, Ubuntu noble amd64. Run as the desktop user.
set -euo pipefail
umask 077
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
here=$PWD
cache="${XDG_CACHE_HOME:-$HOME/.cache}/matebook-biometrics"
state=/var/lib/matebook-biometrics-guide
driver_version=0.1.0-guide
backend=/opt/matebook-biometrics-guide
dropin=/etc/systemd/system/fprintd.service.d/71-matebook-guide.conf
autoload=/etc/modules-load.d/71-matebook-guide.conf
src=/usr/src/gxfp-$driver_version
user=$(id -un)
[[ $EUID != 0 ]] || { echo '请以桌面用户运行，脚本会按需调用 sudo。'; exit 1; }

die() { printf '%s\n' "$*" >&2; exit 1; }
confirm() { local answer; read -r -p "$1 [输入 YES 确认] " answer; [[ $answer == YES ]]; }
packages=(git curl ca-certificates build-essential cmake pkg-config meson ninja-build dkms mokutil
  libglib2.0-dev libgusb-dev libopencv-dev doctest-dev libpixman-1-dev python3-gi fprintd v4l-utils pamtester zenity)
check() {
    . /etc/os-release
    [[ ${UBUNTU_CODENAME:-${VERSION_CODENAME:-}} == noble && $(dpkg --print-architecture) == amd64 ]] ||
        die '安装部分适用于 Ubuntu 24.04 系 amd64。'
    [[ -d /sys/bus/acpi/devices/GXFP5130:00 && -r /etc/pam.d/gdm-fingerprint ]] ||
        die '需要 GXFP5130 ACPI 设备与 GDM。'
}
fetch() {
    local url=$1 path=$2 digest=$3
    if ! printf '%s  %s\n' "$digest" "$path" | sha256sum -c --status; then
        curl --fail --location --retry 2 -o "$path.part" "$url"
        printf '%s  %s\n' "$digest" "$path.part" | sha256sum -c -
        mv -- "$path.part" "$path"
    fi
}
prepare() {
    check
    confirm '安装构建依赖并下载公开源代码？' || return 1
    mkdir -p -- "$cache"
    if [[ ! -e /lib/modules/$(uname -r)/build/Makefile ]]; then
        packages+=("linux-headers-$(uname -r)")
    fi
    sudo apt-get update
    sudo apt-get install --no-remove "${packages[@]}"
    fetch https://github.com/Mbed-TLS/mbedtls/releases/download/mbedtls-3.6.5/mbedtls-3.6.5.tar.bz2         "$cache/mbedtls.tar.bz2" 4a11f1777bb95bf4ad96721cac945a26e04bf19f57d905f241fe77ebeddf46d8
    fetch https://github.com/phucvinh57/biopass/releases/download/1.6.0/biopass_1.6.0_amd64.deb         "$cache/biopass.deb" 3830203cae937d7554d8ddccf5a47a728a9f0d5a45e57616d7cf13b70f35f0b9
    local commit=5e8c91c6b63da472dad946fbfdad2f43bca21eb4
    if [[ ! -d "$cache/gxfp/.git" ]]; then
        git clone https://github.com/Metrohan/gxfp5130-linux.git "$cache/gxfp"
    fi
    git -C "$cache/gxfp" checkout --detach "$commit"
    git -C "$cache/gxfp" diff --quiet || die '源码目录已有本地改动。'
}
restore() {
    sudo test -f "$state/managed" || die '未找到此脚本的安装记录。'
    sudo /bin/bash "$state/restore.sh"
}
install_stack() {
    check
    local secure key work
    if [[ -d /sys/firmware/efi ]]; then
        secure=$(LC_ALL=C mokutil --sb-state) || die '无法确认 Secure Boot 状态。'
        [[ $secure == *'SecureBoot disabled'* ]] || die '本脚本要求 Secure Boot 已关闭。签名和 MOK 需另行配置。'
    fi
    [[ -f "$cache/mbedtls.tar.bz2" && -f "$cache/biopass.deb" && -d "$cache/gxfp/.git" ]] ||
        die '请先运行 prepare。'
    [[ $(git -C "$cache/gxfp" rev-parse HEAD) == 5e8c91c6b63da472dad946fbfdad2f43bca21eb4 ]] || die '驱动源码版本不匹配。'
    printf '%s  %s\n' 3830203cae937d7554d8ddccf5a47a728a9f0d5a45e57616d7cf13b70f35f0b9 "$cache/biopass.deb" | sha256sum -c -
    printf '%s  %s\n' 4a11f1777bb95bf4ad96721cac945a26e04bf19f57d905f241fe77ebeddf46d8 "$cache/mbedtls.tar.bz2" | sha256sum -c -
    read -r -p '输入本人设备已有的 32 字节配对文件路径（只输入路径）: ' key
    [[ -f "$key" && $(stat -Lc %s -- "$key") == 32 ]] || die '需要 32 字节二进制文件。'
    confirm '安装 DKMS、私有 libfprint 和 Biopass？' || return 1
    local target
    for target in "$state" "$backend" "$dropin" "$autoload" "$src" /var/lib/fprint/gxfp; do
        sudo test ! -e "$target" || die "已有 $target，请先检查现有安装。"
    done
    [[ ! -d /sys/module/gxfp && -z $(dkms status -m gxfp) ]] || die '已有 GXFP 驱动。'
    if dpkg-query -W -f='${db:Status-Status}' biopass 2>/dev/null | grep -qx installed; then
        die '已有 Biopass。可直接用 manage 管理现有录入。'
    fi
    work=$(mktemp -d "$cache/build.XXXXXXXX")
    tar -xf "$cache/mbedtls.tar.bz2" -C "$work"
    git -C "$cache/gxfp" archive HEAD kernel libfprint | tar -x -C "$work"
    sed -i '1i#include <set>' "$work/libfprint/libfprint/sigfm/sigfm.cpp"
    sed -i 's|#include <opencv2/opencv.hpp>|#include <opencv2/core.hpp>\n#include <opencv2/imgproc.hpp>\n#include <opencv2/features2d.hpp>\n#include <opencv2/imgcodecs.hpp>|' "$work/libfprint/libfprint/sigfm/sigfm.cpp" "$work/libfprint/libfprint/sigfm/tests.cpp"
    cmake -S "$work/mbedtls-3.6.5" -B "$work/tls-build" -G Ninja \
        -DCMAKE_INSTALL_PREFIX="$work/tls" -DCMAKE_POSITION_INDEPENDENT_CODE=ON \
        -DUSE_SHARED_MBEDTLS_LIBRARY=OFF -DENABLE_TESTING=OFF -DENABLE_PROGRAMS=OFF
    cmake --build "$work/tls-build" -j 4
    cmake --install "$work/tls-build"
    PKG_CONFIG_PATH="$work/tls/lib/pkgconfig" meson setup "$work/fprint-build" "$work/libfprint" \
        -Ddrivers=gxfp -Ddoc=false -Dintrospection=false -Dgtk-examples=false \
        -Dudev_rules=disabled -Dudev_hwdb=disabled
    meson compile -C "$work/fprint-build" -j 4
    local library
    library=$(find "$work/fprint-build/libfprint" -maxdepth 1 -type f -name 'libfprint-2.so.2.*' -print -quit)
    [[ -n "$library" ]] || die '找不到编译后的 libfprint。'
    if ldd "$library" | grep -q 'not found'; then die '私有库存在缺失依赖。'; fi
    sudo install -d -m 700 "$state"
    sudo install -m 700 "$here/restore-system.sh" "$state/restore.sh"
    sudo touch "$state/managed"
    trap 'echo "安装中断，正在恢复已写入的本项目配置。"; restore' ERR
    sudo cp -a /etc/pam.d "$state/before-install-pam"
    sudo apt-get install --no-remove --no-upgrade "$cache/biopass.deb"
    sudo diff -qr /etc/pam.d "$state/before-install-pam"
    sed -i "s/^PACKAGE_VERSION=.*/PACKAGE_VERSION=\"$driver_version\"/" "$work/kernel/dkms.conf"
    sudo install -d "$src" "$backend/lib" "$(dirname -- "$dropin")"
    sudo cp -a --no-preserve=ownership "$work/kernel/." "$src/"
    sudo install -m 644 "$library" "$backend/lib/libfprint-2.so.2"
    sudo dkms install -m gxfp -v "$driver_version" -k "$(uname -r)"
    sudo install -d -m 700 /var/lib/fprint/gxfp
    sudo install -m 600 /dev/stdin /var/lib/fprint/gxfp/psk_raw32.bin < "$key"
    printf 'gxfp\n' | sudo tee "$autoload" >/dev/null
    printf '[Service]\nUMask=0077\nEnvironment=LD_LIBRARY_PATH=%s/lib\nEnvironment=FP_GXFP_PSK=/var/lib/fprint/gxfp/psk_raw32.bin\nDeviceAllow=/dev/gxfp rw\n' "$backend" |
        sudo tee "$dropin" >/dev/null
    sudo modprobe gxfp
    sudo systemctl daemon-reload
    sudo systemctl restart fprintd
    fprintd-list "$user" || [[ -c /dev/gxfp ]]
    trap - ERR
    echo '后端已安装。请先录入、验证，再运行 enable。'
}
manage() { /usr/bin/python3 "$here/manage.py" "$@"; }
enable() {
    check
    sudo test -f "$state/managed" || die '此脚本只接管自己安装的系统。'
    /usr/bin/python3 "$here/manage.py" ready
    fprintd-list "$user" | grep -q 'finger' || die '请先录入指纹。'
    sudo test ! -e "$state/enabled" || die '已启用。'
    confirm '修改 sudo 与 GDM 的 PAM 配置并启动 10 分钟恢复计时器？' || return 1
    sudo /bin/bash "$here/enable-system.sh" "$user"
    echo '请在新终端分别用人脸、指纹和密码执行 sudo -k /usr/bin/true，并测试三种锁屏解锁。'
    if confirm '全部测试通过并保留设置？'; then
        sudo systemctl stop matebook-guide-rollback.timer
    else
        sudo /bin/bash "$state/restore.sh" pam
    fi
}
case "${1:-menu}" in
    prepare) prepare ;;
    install) install_stack ;;
    manage) shift; manage "$@" ;;
    enable) enable ;;
    uninstall) confirm '撤销本项目的系统安装？个人生物样本可在管理菜单按项删除。' && restore ;;
    all) prepare; install_stack; manage default; enable ;;
    menu)
        echo 'a 从头安装（默认录一个人脸样本和右手食指）'
        echo '1 准备  2 安装后端  3 管理录入  4 卸载  5 启用认证'
        read -r -p '选择: ' choice
        case "$choice" in
            a) exec bash "$here/matebook-biometrics.sh" all ;; 1) exec bash "$here/matebook-biometrics.sh" prepare ;; 2) exec bash "$here/matebook-biometrics.sh" install ;;
            3) exec bash "$here/matebook-biometrics.sh" manage ;; 4) exec bash "$here/matebook-biometrics.sh" uninstall ;; 5) exec bash "$here/matebook-biometrics.sh" enable ;;
            *) die '无效选项。' ;;
        esac ;;
    -h|--help) echo 'bash matebook-biometrics.sh [all|prepare|install|manage|enable|uninstall]' ;;
    *) die '未知命令，请用 --help。' ;;
esac
