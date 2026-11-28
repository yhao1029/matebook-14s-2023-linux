#!/usr/bin/env bash
# Source this file; performs no action until ensure_build_dependencies is called.
ensure_build_dependencies() {
    local package status answer requirement
    local -a missing=()
    for package in "$@"; do
        status=$(dpkg-query -W -f='${db:Status-Status}' "$package" 2>/dev/null) || status=missing
        [[ $status == installed ]] || missing+=("$package")
    done
    if ((${#missing[@]})); then
        printf '构建/运行依赖缺失：%s\n' "${missing[*]}" >&2
        read -r -p '先安装这些 Linux 依赖，再继续后端安装？输入 yes: ' answer
        [[ ${answer,,} == yes ]] || { echo '依赖未齐，停止，尚未获取密钥或安装后端。' >&2; return 1; }
        sudo apt-get update || return 1
        sudo apt-get install --no-remove "${missing[@]}" || return 1
    fi
    for requirement in 'glib-2.0 >= 2.56' 'gio-unix-2.0 >= 2.56' 'gobject-2.0 >= 2.56' \
                       'gusb >= 0.2.0' 'gudev-1.0' 'opencv4 >= 4.5.0'; do
        if ! pkg-config --exists "$requirement"; then
            printf '依赖已检查，但 pkg-config 无法解析 %s；请检查软件包或 PKG_CONFIG_LIBDIR/PATH 设置。停止编译。\n' "$requirement" >&2
            return 1
        fi
    done
    # Noble doctest-dev ships doctestConfig.cmake, not doctest.pc.
    # Its package is checked above; Meson resolves its CMake version constraints.
    echo '构建依赖预检通过（含 GXFP 所需 gudev；doctest 交由 Meson/CMake 检测）。'
}
