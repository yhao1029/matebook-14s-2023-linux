"""Metadata-only Windows volume selection and case-insensitive path resolution."""
import argparse
import json
from pathlib import Path
import subprocess
import sys


def resolve_path(root, relative):
    root = Path(root).resolve(strict=True)
    current = root
    for name in Path(relative).parts:
        if name in ('..', '/'):
            raise ValueError('不接受越界路径')
        matches = [p for p in current.iterdir() if p.name.casefold() == name.casefold()]
        if not matches:
            raise FileNotFoundError(f'缺少路径组件：{name}')
        if len(matches) != 1:
            raise ValueError(f'存在大小写冲突：{name}，请人工核对')
        current = matches[0].resolve(strict=True)
        if not current.is_relative_to(root):
            raise ValueError('路径通过链接指向所选目录以外，停止读取')
    return current


REQUIRED = ('Windows/System32/config/SYSTEM', 'Windows/System32/config/SECURITY',
            'ProgramData/Goodix/Goodix_Cache.bin')


def required_files(root):
    files = [resolve_path(root, relative) for relative in REQUIRED]
    if not all(path.is_file() for path in files):
        raise ValueError('Windows 注册表或 Goodix 缓存不是普通文件')
    return files


def mounted_volumes():
    data = json.loads(subprocess.check_output(
        ['findmnt', '--json', '-o', 'SOURCE,TARGET,FSTYPE,OPTIONS'], text=True))
    volumes = []
    seen = set()
    def walk(rows):
        for row in rows:
            if row.get('fstype') in ('ntfs', 'ntfs3', 'fuseblk', 'fuse.ntfs-3g'):
                root = Path(row['target'])
                identity = str(root.resolve())
                if identity not in seen:
                    seen.add(identity)
                    score = 0
                    for relative in REQUIRED:
                        try:
                            score += int(resolve_path(root, relative).is_file())
                        except (OSError, ValueError):
                            pass
                    volumes.append(dict(row, score=score))
            walk(row.get('children', []))
    walk(data.get('filesystems', []))
    return sorted(volumes, key=lambda row: -row['score'])


def choose_volume():
    print('已挂载的 NTFS 分区（只查看目录，不自动挂载或解锁）：', file=sys.stderr)
    volumes = mounted_volumes()
    for number, row in enumerate(volumes, 1):
        status = '只读挂载' if 'ro' in row.get('options', '').split(',') else '可写挂载，将通过隔离只读视图读取'
        print(f"{number}. {row.get('source', '?')} → {row['target']} | 文件特征 {row['score']}/3 | {status}", file=sys.stderr)
    recommended = bool(volumes and volumes[0]['score'] == 3)
    if recommended:
        print('推荐 1：已找到 SYSTEM、SECURITY 和 Goodix 缓存；这只是候选识别，不证明密钥有效。', file=sys.stderr)
    print('未挂载分区可在系统“磁盘”工具查看；本脚本不会自动挂载。', file=sys.stderr)
    # Metadata only; never unlock or mount a block device.
    result = subprocess.run(['lsblk', '-p', '-o', 'NAME,FSTYPE,SIZE,LABEL,MOUNTPOINTS'],
                            text=True, capture_output=True)
    if result.returncode == 0:
        print(result.stdout, file=sys.stderr)
    print('输入分区编号，m 手动输入挂载根目录，q 取消' +
          ('；回车选择推荐项 1：' if recommended else '（没有默认项）：'), file=sys.stderr)
    choice = input().strip()
    if not choice and recommended:
        choice = '1'
    if choice == 'm':
        print('输入挂载根目录，例如 /media/用户名/Windows；不要填 WINDOWS 目录或 SYSTEM 文件：', file=sys.stderr)
        root = Path(input().strip())
    elif choice.isdigit() and 1 <= int(choice) <= len(volumes):
        root = Path(volumes[int(choice) - 1]['target'])
    else:
        raise ValueError('未选择分区，已取消')
    if not root.is_dir():
        raise ValueError('所选位置不是已挂载的分区目录')
    required_files(root)
    print(f'确认来源为本机 Windows 分区 {root}？输入 yes：', file=sys.stderr)
    if input().strip().lower() != 'yes':
        raise ValueError('未确认来源，已取消')
    return root.resolve()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--choose', action='store_true')
    group.add_argument('--files', type=Path)
    args = parser.parse_args()
    if args.choose:
        print(choose_volume())
    else:
        for path in required_files(args.files):
            if '\n' in str(path):
                raise ValueError('不支持包含换行符的路径')
            print(path)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, EOFError, subprocess.SubprocessError) as error:
        print(f'分区检查停止：{error}', file=sys.stderr)
        sys.exit(1)
