"""Local enrollment manager. Camera samples and labels stay on this computer."""
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import select
import sqlite3
import subprocess
import sys
import time
from urllib.request import urlopen

os.umask(0o077)
CONFIG = Path.home() / ".config/com.ticklab.biopass"
DATA = Path.home() / ".local/share/com.ticklab.biopass"
FACES = DATA / "faces"
USER = getpass.getuser()
RELEASE = "https://github.com/phucvinh57/biopass/releases/download/1.6.0/"
MODELS = (
    ("yolov8n-face", "yolov8n-face.onnx", "detection", None,
     "3e81709ceaae911db2dd23bed39aa1fc980b6320e8a8bbf8b587b2a8feaa5a5a"),
    ("edgeface-s-gamma-05", "edgeface_s_gamma_05.onnx", "recognition", None,
     "cdc2ced431b4bf071c92f2fe8bb6ed4b5017be4175b4375eaa6e14b255f831ce"),
)
FINGERS = [(side + "-" + finger, label + name)
           for side, label in (("right", "右手"), ("left", "左手"))
           for finger, name in (("thumb", "拇指"), ("index-finger", "食指"),
                                ("middle-finger", "中指"), ("ring-finger", "无名指"),
                                ("little-finger", "小指"))]


def private_dir(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink() or path.stat().st_uid != os.getuid():
        raise RuntimeError("应用目录须由当前用户所有且不能是符号链接")
    path.chmod(0o700)


def registered_faces():
    return sorted(p for p in FACES.glob("*")
                  if p.is_file() and not p.is_symlink()
                  and p.suffix.lower() in (".jpg", ".jpeg", ".png"))


def discover_ir_camera():
    from shutil import which
    if not which('v4l2-ctl'):
        raise RuntimeError('缺少 v4l2-ctl。请先完成准备步骤安装 v4l-utils，然后重试。')
    candidates = {}
    paths = sorted(Path('/dev/v4l/by-path').glob('*')) + sorted(Path('/dev').glob('video*'))
    for path in paths:
        if not path.resolve().is_char_device():
            continue
        try:
            result = subprocess.run(['v4l2-ctl', '-d', str(path), '--list-formats-ext'],
                                    text=True, capture_output=True, timeout=8)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0 and "'GREY'" in result.stdout:
            candidates.setdefault(str(path.resolve()), str(path))
    choices = list(candidates.values())
    if len(choices) == 1:
        print('自动识别原生 GREY 红外摄像头：' + choices[0])
        return choices[0]
    if choices:
        for index, path in enumerate(choices, 1):
            print(f'{index}. {path}')
        choice = input('发现多个红外节点，输入编号（回车取消）: ').strip()
        if choice.isdigit() and 1 <= int(choice) <= len(choices):
            return choices[int(choice) - 1]
    raise RuntimeError('未选定可读取的原生 GREY 红外节点。请检查摄像头隐私开关、权限及 v4l2-ctl --list-devices；不要填写猜测路径。')


def initialize_face():
    if not Path('/usr/bin/biopass-helper').exists():
        raise RuntimeError('尚未安装 Biopass 后端，请先完成菜单 2；摄像头硬件存在不代表软件已安装。')
    for path in (CONFIG, DATA, FACES, DATA / "models"):
        private_dir(path)
    config_path = CONFIG / "config.yaml"
    previous = None
    if config_path.exists():
        import yaml
        previous = yaml.safe_load(config_path.read_text())
        if previous.get('methods', {}).get('face', {}).get('camera'):
            return read_camera()
    camera = discover_ir_camera()
    formats = subprocess.check_output(["v4l2-ctl", "-d", camera, "--list-formats-ext"], text=True)
    if "'GREY'" not in formats:
        raise RuntimeError("该节点没有原生 GREY 格式")
    with sqlite3.connect(CONFIG / "biopass.db") as db:
        db.execute("""CREATE TABLE IF NOT EXISTS models (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, task TEXT NOT NULL,
            architecture TEXT, path TEXT NOT NULL, version TEXT, checksum TEXT,
            source TEXT NOT NULL, installed_at INTEGER NOT NULL)""")
        for slug, filename, task, arch, checksum in MODELS:
            p = DATA / "models" / filename
            if not p.exists():
                with urlopen(RELEASE + filename, timeout=30) as response:
                    payload = response.read(32 * 1024 * 1024)
                if hashlib.sha256(payload).hexdigest() != checksum:
                    raise RuntimeError(f"校验失败: {filename}")
                p.write_bytes(payload)
            if hashlib.sha256(p.read_bytes()).hexdigest() != checksum:
                raise RuntimeError(f"校验失败: {filename}")
            db.execute("INSERT OR IGNORE INTO models VALUES (?,?,?,?,?,?,?,?,?)",
                       (slug, slug, task, arch, str(p), "1.6.0", checksum, "builtin", int(time.time())))
        db.execute("PRAGMA user_version=2")
    config = {
        "schema_version": 2,
        "strategy": {"debug": False, "execution_mode": "parallel",
                     "order": ["face", "fingerprint"],
                     "ignore_services": ["gdm-password", "sshd", "pkexec", "polkit-1"]},
        "methods": {
            "face": {"enable": True, "retries": 3, "retry_delay": 200, "camera": camera,
                     "detection": {"model_id": MODELS[0][0], "threshold": 0.5},
                     "recognition": {"model_id": MODELS[1][0], "threshold": 0.5},
                     "anti_spoofing": {"enable": False, "ir_camera": camera}},
            "fingerprint": {"enable": True, "retries": 3, "timeout": 5000},
        },
    }
    if previous:
        face_defaults = config['methods']['face']
        face_defaults.update(previous.get('methods', {}).get('face', {}))
        config.update(previous)
        config.setdefault('methods', {})['face'] = face_defaults
    config_path.write_text(json.dumps(config, indent=2))
    return camera


def read_camera():
    # JSON is valid YAML. For an existing GUI-written YAML file ask for the node
    # rather than editing unrelated settings.
    try:
        import yaml
        return yaml.safe_load((CONFIG / "config.yaml").read_text())["methods"]["face"]["camera"]
    except (ValueError, KeyError):
        return input("输入 Biopass 当前配置的红外摄像头路径: ").strip()


def label(prompt):
    if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        from shutil import which
        if which("zenity"):
            result = subprocess.run(["zenity", "--entry", "--title=本地样本标签",
                                     "--text=" + prompt], text=True, capture_output=True)
            return result.stdout.strip() if result.returncode == 0 else ""
    return input(prompt + "：").strip()


def capture_face(destination):
    if destination.exists() or destination.is_symlink():
        raise RuntimeError("此名称已存在")
    camera = initialize_face()
    with sqlite3.connect(f"file:{CONFIG / 'biopass.db'}?mode=ro", uri=True) as db:
        row = db.execute("SELECT path FROM models WHERE id=?", (MODELS[0][0],)).fetchone()
    if not row:
        raise RuntimeError("Biopass 中还没有安装 YOLOv8n 人脸检测模型")
    from face_preview import capture_with_preview
    capture_with_preview(camera, row[0], destination)


def face_name():
    name = label("输入样本标签，例如 本人-正脸")
    if not name or len(name) > 80 or name.startswith(".") or any(c in name for c in "/\\\r\n\0"):
        raise RuntimeError("标签为空或包含无效字符")
    return FACES / (name + ".jpg")


def face_menu():
    private_dir(FACES)
    faces = registered_faces()
    for index, face in enumerate(faces, 1):
        print(f"{index}. {face.stem}")
    action = input("a 新增，r 改名，d 删除，回车返回: ").strip()
    if action == "a":
        capture_face(face_name())
    elif action in ("r", "d"):
        choice = int(input("样本编号: "))
        if not 1 <= choice <= len(faces):
            raise RuntimeError("无效编号")
        face = faces[choice - 1]
        if action == "r":
            target = face_name().with_suffix(face.suffix)
            if target.exists() or target.is_symlink():
                raise RuntimeError("标签已存在")
            face.rename(target)
        elif input(f"删除 {face.stem}？输入 YES: ") == "YES":
            face.unlink()


def enrollment_stage_count(device_path):
    if not re.fullmatch(r"/net/reactivated/Fprint/Device/[0-9]+", device_path):
        return None
    try:
        result = subprocess.run(
            ["gdbus", "call", "--system", "--dest", "net.reactivated.Fprint",
             "--object-path", device_path, "--method", "org.freedesktop.DBus.Properties.Get",
             "net.reactivated.Fprint.Device", "num-enroll-stages"],
            capture_output=True, text=True, check=True, timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.fullmatch(r"\(<(?:int32 )?([1-9][0-9]*)>,\)\s*", result.stdout)
    return int(match[1]) if match else None


def enroll_finger(finger):
    print("请先完成管理员认证。出现录入提示后，轻放要录入的手指。", flush=True)
    subprocess.run(["sudo", "-v"], check=True)
    started = int(time.time())
    command = ["/usr/bin/timeout", "--foreground", "--signal=INT", "--kill-after=5s",
               "300", "sudo", "-n", "/usr/bin/env", "LC_ALL=C", "/usr/bin/stdbuf", "-oL", "-eL",
               "/usr/bin/fprintd-enroll", "-f", finger, USER]
    stages = 0
    total_stages = None
    try:
        with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, errors="replace") as proc:
            for line in proc.stdout:
                print(line, end="", flush=True)
                if line.startswith("Using device "):
                    total_stages = enrollment_stage_count(line.removeprefix("Using device ").strip())
                elif line.startswith("Enrolling "):
                    if total_stages:
                        print(f"本次预计需要 {total_stages} 次有效采集，完成后另做一次验证。",
                              flush=True)
                    else:
                        print("本次需要多次有效采集，完成后另做一次验证。", flush=True)
                    print("现在轻放指腹，保持到采集提示出现。", flush=True)
                elif "enroll-stage-passed" in line:
                    stages += 1
                    progress = f"{stages}/{total_stages}" if total_stages and stages < total_stages else str(stages)
                    next_step = ("下一次是最后一轮采集。"
                                 if total_stages and stages + 1 == total_stages else "")
                    print(f"已完成 {progress} 次采集。{next_step}请完全抬起，再轻放。",
                          flush=True)
                elif any(status in line for status in (
                        "enroll-retry-scan", "enroll-swipe-too-short",
                        "enroll-finger-not-centered", "enroll-remove-and-retry")):
                    print("请移开手指，再用指腹中央轻放。", flush=True)
            status = proc.wait()
    except KeyboardInterrupt:
        raise RuntimeError("已取消指纹录入。") from None
    if status in (-2, 130):
        raise RuntimeError("已取消指纹录入。")
    if status in (124, 137):
        raise RuntimeError("录入超时。请完全抬起手指，再试一次。")
    if status:
        try:
            logs = subprocess.run(
                ["journalctl", "-u", "fprintd", "--since", f"@{started}",
                 "--no-pager", "-o", "cat", "-n", "40"],
                text=True, capture_output=True, timeout=3,
            )
        except (OSError, subprocess.TimeoutExpired):
            logs = None
        if logs is not None and re.search(
            r"error during (?:identify for enroll|enroll): Device disabled to prevent overheating",
            logs.stdout, re.IGNORECASE,
        ):
            raise RuntimeError(
                "libfprint 的温度估算保护暂时拒绝录入。此状态按读取器使用时长估算，没有实际温度读数。请让读取器完全空闲约 7 分钟后再试一次。若仍立即失败，请检查 fprintd 与驱动的会话状态。"
            )
        raise RuntimeError("指纹录入失败。详细原因请查看 journalctl -u fprintd -n 30。")
    print("录入完成，指纹已保存。接下来单独验证，请抬起后再轻放一次同一根手指。", flush=True)
    try:
        verified = subprocess.run(
            ["/usr/bin/timeout", "--foreground", "--signal=INT", "--kill-after=5s",
             "45", "fprintd-verify", "-f", finger, USER],
        )
    except KeyboardInterrupt:
        print("已取消验证，录入仍已保存。")
        return
    if verified.returncode:
        print("录入已保存，本次验证未通过或已取消。可稍后重新验证。")
    else:
        print("验证通过，新指纹可以使用。")


def delete_finger(finger):
    subprocess.run(["sudo", "/usr/bin/python3", str(Path(__file__).with_name("delete-finger.py")),
                    USER, finger], check=True)


def finger_menu():
    result = subprocess.run(["fprintd-list", USER], text=True, capture_output=True)
    listed = set(re.findall(r"^\s*- #\d+: ([\w-]+)", result.stdout, re.M))
    if "Using device" not in result.stdout:
        raise RuntimeError("fprintd 未发现设备")
    label_path = DATA / "finger-labels.json"
    labels = json.loads(label_path.read_text()) if label_path.exists() else {}
    keys = dict(zip("1234567890", FINGERS))
    for key, (finger, name) in keys.items():
        print(f"{key}. {name}  {'已录入' if finger in listed else '未录入'}  {labels.get(finger, '')}")
    choice = input("输入 1–9 或 0，c 自定义备注并选择手指，回车返回: ").strip()
    note = ""
    if choice == "c":
        note = label("输入该手指的本地备注")
        choice = input("选择该备注对应的标准手指编号: ").strip()
    if choice not in keys:
        return
    finger, name = keys[choice]
    if finger in listed:
        action = input("r 删除旧记录并重新录入，d 删除，l 修改备注，回车返回: ").strip()
        if action == "l":
            note = label("输入新的本地备注")
        elif action in ("r", "d") and input(f"确认移除旧{ name }？输入 YES: ") == "YES":
            delete_finger(finger)
            labels.pop(finger, None)
            if action == "r":
                enroll_finger(finger)
            elif action == "d":
                note = ""
        else:
            return
    else:
        enroll_finger(finger)
    if note:
        labels[finger] = note
    private_dir(DATA)
    label_path.write_text(json.dumps(labels, ensure_ascii=False, indent=2))


def verify_fingerprint_samples():
    listing = subprocess.run(["fprintd-list", USER], env=dict(os.environ, LC_ALL="C"),
                             capture_output=True, text=True)
    enrolled = set(re.findall(r"^\s*- #\d+: ([\w-]+)", listing.stdout, re.M))
    fingers = [(key, name) for key, name in FINGERS if key in enrolled]
    if not fingers:
        raise RuntimeError("没有可验证的已录入指纹，请先检查读取器和登记列表。")
    note_path = DATA / "finger-labels.json"
    notes = json.loads(note_path.read_text()) if note_path.is_file() else {}
    print(f"共有 {len(fingers)} 个指纹记录。每次请使用同一根待测手指。")
    for index, (key, name) in enumerate(fingers, 1):
        print(f"正在比对 {index}/{len(fingers)}（{name}）。请先抬起，再轻放待测手指。",
              flush=True)
        result = subprocess.run(
            ["timeout", "--foreground", "--signal=INT", "--kill-after=5s", "15",
             "stdbuf", "-oL", "-eL", "fprintd-verify", "-f", key, USER],
            env=dict(os.environ, LC_ALL="C"), stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True,
        )
        if "verify-match (done)" in result.stdout and result.returncode == 0:
            suffix = f"（{notes[key]}）" if notes.get(key) else ""
            print(f"匹配到了：{name}{suffix}")
            return
        if "verify-no-match (done)" not in result.stdout:
            if result.returncode == 124:
                raise RuntimeError("等待指纹超时，测试未完成。")
            if result.returncode in (-2, 130):
                print("已取消指纹测试。")
                return
            print(result.stdout.strip())
            raise RuntimeError("读取器没有返回有效的比对结果，请查看 fprintd 日志。")
        if index < len(fingers):
            input("这一项未匹配。请先完全抬起，按回车进入下一项，再轻放同一根手指。")
    print("没有匹配到任何已录入的指纹。")


def verify_face_samples():
    import shutil
    import tempfile

    try:
        import yaml
    except ImportError as error:
        raise RuntimeError("人脸测试需要 python3-yaml。") from error
    if not shutil.which("bwrap"):
        raise RuntimeError("人脸测试需要 bubblewrap 来隔离临时诊断文件。")
    samples = {str(path): path.stem for path in registered_faces()}
    if not samples:
        raise RuntimeError("请先录入人脸。")
    if not (CONFIG / "biopass.db").is_file():
        raise RuntimeError("找不到 Biopass 模型数据库。")
    config = yaml.safe_load((CONFIG / "config.yaml").read_text())
    config["strategy"].update(debug=True, execution_mode="sequential", order=["face"],
                              ignore_services=[])
    config["methods"]["fingerprint"]["enable"] = False
    if not config["methods"]["face"]["enable"]:
        raise RuntimeError("Biopass 当前关闭了人脸验证。")
    # Biopass reads settings by passwd home and uses absolute paths in the DB.
    # Override only its view of these two directories for this process.
    fs_type = subprocess.check_output(
        ["stat", "-f", "-c", "%T", "/dev/shm"], text=True
    ).strip()
    if fs_type != "tmpfs":
        raise RuntimeError("人脸诊断需要 /dev/shm 为临时内存文件系统。")
    with tempfile.TemporaryDirectory(prefix="matebook-face-test-", dir="/dev/shm") as tmp:
        root = Path(tmp)
        conf = root / "config"
        data = root / "data"
        conf.mkdir()
        data.mkdir()
        (conf / "config.yaml").write_text(json.dumps(config))
        shutil.copyfile(CONFIG / "biopass.db", conf / "biopass.db")
        binds = []
        for name in ("faces", "models"):
            source = DATA / name
            if source.is_dir():
                (data / name).mkdir()
                binds += ["--ro-bind", str(source), str(source)]
        print("请正对摄像头。开始独立人脸验证，结束后会显示匹配的样本标签。", flush=True)
        result = subprocess.run(
            ["timeout", "--foreground", "--signal=INT", "--kill-after=5s", "45",
             "bwrap", "--unshare-net", "--ro-bind", "/", "/", "--dev-bind", "/dev", "/dev",
             "--proc", "/proc", "--die-with-parent",
             "--ro-bind", str(conf), str(CONFIG), "--bind", str(data), str(DATA),
             *binds, "/usr/bin/biopass-helper", "auth", "--username", USER,
             "--service", "matebook-face-diagnostic"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            for log in sorted((data / "logs").glob("*.log")):
                for line in log.read_text(errors="replace").splitlines():
                    match = re.search(r"Recognition PASSED \| matched face='(.*)' score=", line)
                    if match and match[1] in samples:
                        print(f"匹配到了人脸样本：{samples[match[1]]}")
                        return
            print("人脸验证通过，但当前 Biopass 版本未提供可识别的样本标签。")
        elif result.returncode == 124:
            raise RuntimeError("人脸测试超时。")
        elif result.returncode == 2:
            raise RuntimeError("人脸验证未启动，请检查摄像头、录入和模型。")
        elif result.stderr.startswith("bwrap:"):
            raise RuntimeError("无法建立隔离的人脸测试环境：" + result.stderr.strip())
        else:
            print("未匹配到人脸样本，或摄像头暂时不可用。")


def verification_menu():
    choice = input("验证测试：1 人脸，2 指纹，回车返回: ").strip()
    try:
        if choice == "1":
            verify_face_samples()
        elif choice == "2":
            verify_fingerprint_samples()
    except KeyboardInterrupt:
        print("\n已取消验证测试。")


def configure_available_methods():
    import yaml
    face = bool(registered_faces())
    result = subprocess.run(['fprintd-list', USER], text=True, capture_output=True)
    finger = bool(re.search(r'^\s*- #\d+: [\w-]+', result.stdout, re.M))
    if not face and not finger:
        raise RuntimeError('请至少录入一种：人脸或指纹。')
    private_dir(CONFIG)
    path = CONFIG / 'config.yaml'
    config = yaml.safe_load(path.read_text()) if path.exists() else {
        'schema_version': 2,
        'strategy': {'execution_mode': 'parallel', 'order': ['face', 'fingerprint'],
                     'ignore_services': ['gdm-password', 'sshd', 'pkexec', 'polkit-1']},
        'methods': {'face': {'enable': False},
                    'fingerprint': {'enable': True, 'retries': 3, 'timeout': 5000}}}
    config['methods'].setdefault('face', {})['enable'] = face
    config['methods'].setdefault('fingerprint', {})['enable'] = finger
    temporary = CONFIG / '.config-enable.tmp'
    with temporary.open('w') as output:
        json.dump(config, output, indent=2)
    temporary.chmod(0o600)
    temporary.replace(path)
    return ','.join(name for name, active in (('face', face), ('fingerprint', finger)) if active)


def main():
    if os.geteuid() == 0:
        raise RuntimeError("请以当前桌面用户运行")
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "ready":
        print(configure_available_methods())
        return
    if command == "default":
        enroll_finger("right-index-finger")
        try:
            capture_face(FACES / "本人-正脸.jpg")
        except RuntimeError as error:
            print(error)
            if input('暂时仅使用已录入指纹，继续启用？输入 YES: ') != 'YES':
                raise
        return
    while True:
        choice = input("1 管理人脸，2 管理指纹，3 验证测试，回车退出: ").strip()
        try:
            if choice == "1":
                face_menu()
            elif choice == "2":
                finger_menu()
            elif choice == "3":
                verification_menu()
            else:
                return
        except (ValueError, RuntimeError, OSError, subprocess.CalledProcessError) as error:
            print(error, file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except (EOFError, KeyboardInterrupt):
        print("\n已退出。")
