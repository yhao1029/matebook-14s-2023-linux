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


def initialize_face():
    for path in (CONFIG, DATA, FACES, DATA / "models"):
        private_dir(path)
    config_path = CONFIG / "config.yaml"
    if config_path.exists():
        return read_camera()
    print("请用 v4l2-ctl --list-devices 及 --list-formats-ext 确认原生 GREY 红外节点。")
    camera = input("输入 /dev/v4l/by-path/ 下的红外摄像头路径: ").strip()
    if not camera.startswith("/dev/v4l/by-path/") or not Path(camera).resolve().is_char_device():
        raise RuntimeError("无效的摄像头路径")
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
    config_path.write_text(json.dumps(config, indent=2))
    return camera


def read_camera():
    # JSON is valid YAML. For an existing GUI-written YAML file ask for the node
    # rather than editing unrelated settings.
    try:
        return json.loads((CONFIG / "config.yaml").read_text())["methods"]["face"]["camera"]
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
    input("正对镜头约 40–60 厘米，准备好后按回车。")
    with subprocess.Popen(
        ["/usr/bin/biopass-helper", "preview-session", "--camera", camera, "--model", row[0]],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0,
    ) as proc:
        def reply():
            end = time.monotonic() + 20
            result = bytearray()
            while time.monotonic() < end and len(result) < 4096:
                if select.select([proc.stdout], [], [], 0.2)[0]:
                    char = proc.stdout.read(1)
                    if char == b"\n":
                        return result.decode()
                    if not char:
                        break
                    result.extend(char)
            raise RuntimeError("摄像头连接超时")
        try:
            if reply() != "READY":
                raise RuntimeError("无法打开摄像头")
            for _ in range(12):
                proc.stdin.write(f"CAPTURE {destination}\n".encode())
                result = reply()
                if result == "OK":
                    destination.chmod(0o600)
                    return
                if result != "NO_FACE":
                    break
            raise RuntimeError("未采集到清晰人脸，请调整姿态与光线")
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(3)
                except subprocess.TimeoutExpired:
                    proc.kill()


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


def enroll_finger(finger):
    subprocess.run(["sudo", "fprintd-enroll", "-f", finger, USER], check=True)
    subprocess.run(["fprintd-verify", "-f", finger, USER], check=True)


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


def main():
    if os.geteuid() == 0:
        raise RuntimeError("请以当前桌面用户运行")
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "ready":
        if not registered_faces():
            raise RuntimeError("请先录入人脸")
        return
    if command == "default":
        enroll_finger("right-index-finger")
        capture_face(FACES / "本人-正脸.jpg")
        return
    while True:
        choice = input("1 管理人脸，2 管理指纹，回车退出: ").strip()
        try:
            if choice == "1":
                face_menu()
            elif choice == "2":
                finger_menu()
            else:
                return
        except (ValueError, RuntimeError, OSError, subprocess.CalledProcessError) as error:
            print(error, file=sys.stderr)


if __name__ == "__main__":
    main()
