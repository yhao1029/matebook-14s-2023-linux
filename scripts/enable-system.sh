#!/usr/bin/env bash
set -euo pipefail
umask 077
state=/var/lib/matebook-biometrics-guide
[[ $EUID == 0 && -f "$state/managed" ]] || exit 1
[[ $1 != root ]]
methods=${2:?authentication methods required}
[[ $methods == face || $methods == fingerprint || $methods == face,fingerprint ]] || exit 1
reenable=false
if [[ -e "$state/enabled" ]]; then
    reenable=true
    for service in sudo gdm-fingerprint; do
        cmp -s "/etc/pam.d/$service" "$state/$service.applied" || { echo '已有 PAM 后续改动，停止自动接管。'; exit 1; }
    done
fi
# Check the PAM shape before making any changes.
if ! $reenable; then
    grep -Eq '^auth[[:space:]]+required[[:space:]]+pam_fprintd.so([[:space:]]|$)' /etc/pam.d/gdm-fingerprint
fi
grep -Eq '^@include[[:space:]]+common-auth$' /etc/pam.d/sudo
if grep -Eq 'auth.*(pam_fprintd|libbiopass_pam)' /etc/pam.d/common-auth; then
    echo 'common-auth 已有生物识别配置，请先处理重复认证。' >&2
    exit 1
fi
scratch=$(mktemp -d /run/matebook-guide.XXXXXXXX)
trap 'rm -rf -- "$scratch"' EXIT
for service in sudo gdm-fingerprint; do
    if ! $reenable; then cp -p "/etc/pam.d/$service" "$state/$service.original"; fi
done
sed 's/^\(auth[[:space:]]\+required[[:space:]]\+\)pam_fprintd\.so.*$/\1libbiopass_pam.so/' \
    "$state/gdm-fingerprint.original" > "$state/gdm-fingerprint.applied"
sed '/^@include[[:space:]]\+common-auth$/i auth sufficient libbiopass_pam.so' \
    "$state/sudo.original" > "$state/sudo.applied"
# The dedicated probe never affects login or sudo.
test ! -e /etc/pam.d/matebook-guide-probe
trap 'rm -f /etc/pam.d/matebook-guide-probe; rm -rf -- "$scratch"' EXIT
printf 'auth sufficient libbiopass_pam.so\nauth required pam_unix.so\n' > /etc/pam.d/matebook-guide-probe
tests=()
[[ $methods != *face* ]] || tests+=('不碰指纹，只看镜头')
[[ $methods != *fingerprint* ]] || tests+=('遮住镜头并放上已登记指纹')
tests+=('遮住镜头且不碰指纹，等密码提示后输入密码')
for method in "${tests[@]}"; do
    read -r -p "独立认证测试，请$method，准备好按回车。"
    pamtester -I "tty=$(tty)" matebook-guide-probe "$1" authenticate
done
read -r -p '以上是否确实分别使用所选方式及原密码通过？输入 yes: ' answer
[[ ${answer,,} == yes ]]
systemd-run --unit=matebook-guide-rollback --on-active=10m /bin/bash "$state/restore.sh" pam
for service in sudo gdm-fingerprint; do
    install -m 644 "$state/$service.applied" "$scratch/$service"
    # Install into the destination directory before the atomic rename.
    install -m 644 "$scratch/$service" "/etc/pam.d/.matebook-$service"
    mv -f "/etc/pam.d/.matebook-$service" "/etc/pam.d/$service"
done
touch "$state/enabled"
