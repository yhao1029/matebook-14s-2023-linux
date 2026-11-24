#!/usr/bin/env bash
set -euo pipefail
state=/var/lib/matebook-biometrics-guide
[[ $EUID == 0 && -f "$state/managed" ]] || exit 1
for service in sudo gdm-fingerprint; do
    if [[ -f "$state/$service.original" ]]; then
        if [[ -f "$state/$service.applied" ]] && ! cmp -s "/etc/pam.d/$service" "$state/$service.applied" &&
            ! cmp -s "/etc/pam.d/$service" "$state/$service.original"; then
            echo "PAM 文件后来改过，请手动合并 $state/$service.original" >&2
            exit 1
        fi
        install -m 644 "$state/$service.original" "/etc/pam.d/$service"
    fi
done
systemctl stop matebook-guide-rollback.timer 2>/dev/null || true
rm -f "$state/enabled"
[[ ${1:-} != pam ]] || exit 0
systemctl stop fprintd
rm -f /etc/modules-load.d/71-matebook-guide.conf /etc/systemd/system/fprintd.service.d/71-matebook-guide.conf
if [[ -d /sys/module/gxfp ]]; then modprobe -r gxfp; fi
if [[ -n $(dkms status -m gxfp -v 0.1.0-guide) ]]; then
    dkms remove -m gxfp -v 0.1.0-guide --all
fi
rm -rf /usr/src/gxfp-0.1.0-guide /opt/matebook-biometrics-guide
rm -f /var/lib/fprint/gxfp/psk_raw32.bin
rmdir /var/lib/fprint/gxfp 2>/dev/null || true
if dpkg-query -W -f='${db:Status-Status}' biopass 2>/dev/null | grep -qx installed; then
    apt-get remove biopass
fi
systemctl daemon-reload
systemctl start fprintd
rm -f "$state/managed"
echo "系统后端已撤销。原 PAM 备份仍在 $state；构建依赖和个人录入保留。"
