"""Local GTK preview using the same Biopass capture/detector as authentication."""
import os
from pathlib import Path
import select
import subprocess
import tempfile
import threading
import time


def discover_color_camera(ir_camera, paths=None, sysfs=Path('/sys/class/video4linux')):
    ir_node = Path(ir_camera).resolve().name
    ir_parent = (sysfs / ir_node / 'device').resolve().parent
    candidates = {}
    if paths is None:
        paths = sorted(Path('/dev/v4l/by-path').glob('*')) + sorted(Path('/dev').glob('video*'))
    for path in paths:
        node = path.resolve()
        if not node.is_char_device() or node.name == ir_node:
            continue
        result = subprocess.run(['v4l2-ctl', '-d', str(path), '--list-formats-ext'],
                                text=True, capture_output=True, timeout=8)
        if result.returncode or not any(fmt in result.stdout for fmt in ("'YUYV'", "'MJPG'", "'NV12'", "'RGB3'")):
            continue
        parent = (sysfs / node.name / 'device').resolve().parent
        candidates.setdefault(str(node), (parent == ir_parent, str(path)))
    choices = sorted(candidates.values(), key=lambda row: not row[0])
    preferred = [path for same, path in choices if same]
    if len(preferred) == 1:
        print('自动识别同一摄像头组件的前置彩色节点：' + preferred[0])
        return preferred[0]
    if len(choices) == 1:
        return choices[0][1]
    for number, (_, path) in enumerate(choices, 1):
        print(f'{number}. {path}')
    choice = input('请选择用于大画面预览的前置彩色摄像头编号，回车取消: ').strip()
    if choice.isdigit() and 1 <= int(choice) <= len(choices):
        return choices[int(choice)-1][1]
    raise RuntimeError('未选择彩色预览节点；不会改用红外画面冒充前置彩色预览')


def read_bytes(stream, count, timeout=10):
    end = time.monotonic() + timeout
    result = bytearray()
    while len(result) < count:
        remaining = end - time.monotonic()
        if remaining <= 0:
            raise RuntimeError('摄像头响应超时；检查是否被其他应用占用')
        if select.select([stream], [], [], min(remaining, .2))[0]:
            part = os.read(stream.fileno(), count - len(result))
            if not part:
                raise RuntimeError('摄像头助手已退出')
            result.extend(part)
    return bytes(result)


def read_line(stream):
    result = bytearray()
    deadline = time.monotonic() + 15
    while len(result) < 4096:
        byte = read_bytes(stream, 1, max(.01, deadline - time.monotonic()))
        if byte == b'\n':
            return result.decode(errors='replace')
        result.extend(byte)
    raise RuntimeError('摄像头协议异常')


def save_confirmed(destination, sample):
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(sample)
    except BaseException:
        Path(destination).unlink(missing_ok=True)
        raise


def capture_with_preview(camera, model, destination):
    color_camera = discover_color_camera(camera)
    try:
        import gi
        gi.require_version('Gtk', '3.0')
        from gi.repository import Gtk, GdkPixbuf, GLib
    except (ImportError, ValueError) as error:
        raise RuntimeError('预览需要 python3-gi 和 gir1.2-gtk-3.0，请先重新运行准备步骤') from error
    if not Gtk.init_check()[0]:
        raise RuntimeError('无法连接桌面；请在本人的图形桌面终端运行录入，不要 sudo 运行')
    window = Gtk.Window(title='本机红外人脸录入：确认后才保存')
    window.set_default_size(760, 560)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    box.set_border_width(12)
    window.add(box)
    live, detected = Gtk.Image(), Gtk.Image()
    box.pack_start(Gtk.Label(label='前置彩色摄像头预览（仅供调整位置，不保存彩色图像）'), False, False, 0)
    box.pack_start(live, True, True, 0)
    box.pack_start(Gtk.Label(label='实际检测到的人脸裁剪（不是身份匹配或活体检测）'), False, False, 0)
    box.pack_start(detected, False, False, 0)
    status = Gtk.Label(label='正在打开摄像头并预热，请正对镜头约 40–60 厘米…')
    status.set_line_wrap(True)
    box.pack_start(status, False, False, 0)
    confirm = Gtk.Button(label='确认录入')
    cancel = Gtk.Button(label='取消')
    retry = Gtk.Button(label='重新截取')
    retry.set_sensitive(False)
    confirm.set_sensitive(False)
    buttons = Gtk.Box(spacing=12)
    buttons.pack_start(confirm, True, True, 0)
    buttons.pack_start(retry, True, True, 0)
    buttons.pack_start(cancel, True, True, 0)
    box.pack_start(buttons, False, False, 0)
    stop = threading.Event()
    frozen = threading.Event()
    state = {'sample': None, 'time': 0, 'saved': False, 'error': None}

    def image(widget, payload, width, height):
        loader = GdkPixbuf.PixbufLoader.new_with_type('jpeg')
        loader.write(payload)
        loader.close()
        pixbuf = loader.get_pixbuf()
        scale = min(width / pixbuf.get_width(), height / pixbuf.get_height())
        widget.set_from_pixbuf(pixbuf.scale_simple(max(1, int(pixbuf.get_width()*scale)),
            max(1, int(pixbuf.get_height()*scale)), GdkPixbuf.InterpType.BILINEAR))

    def update(frame, sample, message):
        if stop.is_set():
            return False
        if frame:
            image(live, frame, 640, 300)
        state.update(sample=sample, time=time.monotonic())
        confirm.set_sensitive(sample is not None)
        retry.set_sensitive(sample is not None)
        if sample:
            image(detected, sample, 160, 120)
        else:
            detected.clear()
        status.set_text(message)
        return False

    def choose(_):
        if state['sample'] is None:
            return
        try:
            save_confirmed(destination, state['sample'])
            state['saved'] = True
            window.destroy()
        except OSError as error:
            state['error'] = str(error)
            window.destroy()

    def close(*_):
        stop.set()
        Gtk.main_quit()

    def retake(_):
        state['sample'] = None
        detected.clear()
        confirm.set_sensitive(False)
        retry.set_sensitive(False)
        status.set_text('已放弃上一张，正在重新截取…')
        frozen.clear()

    def worker():
        proc = None
        color = None
        try:
            # JPEG preview stays in memory; only detector crops temporarily enter tmpfs.
            with tempfile.TemporaryDirectory(prefix='matebook-face-', dir='/dev/shm') as tmp:
                crop = Path(tmp) / 'candidate.jpg'
                proc = subprocess.Popen(['/usr/bin/biopass-helper', 'preview-session',
                    '--camera', camera, '--model', model], stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
                ready = read_line(proc.stdout)
                if ready != 'READY':
                    raise RuntimeError('摄像头初始化失败：' + ready[:240])
                color = subprocess.Popen(['/usr/bin/biopass-helper', 'preview-session',
                    '--camera', color_camera], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, bufsize=0)
                color_ready = read_line(color.stdout)
                if color_ready != 'READY':
                    raise RuntimeError('前置彩色摄像头初始化失败：' + color_ready[:240])
                started = time.monotonic()
                while not stop.is_set():
                    if frozen.is_set():
                        stop.wait(.1)
                        continue
                    color.stdin.write(b'FRAME\n')
                    header = read_line(color.stdout)
                    if not header.startswith('OK '):
                        raise RuntimeError('预览采集失败：' + header[:240])
                    count = int(header[3:])
                    if not 0 < count <= 8 * 1024 * 1024:
                        raise RuntimeError('预览图像长度异常')
                    frame = read_bytes(color.stdout, count)
                    # Keep IR exposure/stream active while previewing in color.
                    proc.stdin.write(b'FRAME\n')
                    ir_header = read_line(proc.stdout)
                    if not ir_header.startswith('OK '):
                        raise RuntimeError('红外采集失败：' + ir_header[:240])
                    ir_count = int(ir_header[3:])
                    if not 0 < ir_count <= 8 * 1024 * 1024:
                        raise RuntimeError('红外图像长度异常')
                    read_bytes(proc.stdout, ir_count)
                    sample = None
                    message = '预热中，请保持完整正脸可见…'
                    if time.monotonic() - started >= 2:
                        proc.stdin.write(f'CAPTURE {crop}\n'.encode())
                        result = read_line(proc.stdout)
                        if result == 'OK':
                            sample = crop.read_bytes()
                            crop.unlink()
                            frozen.set()
                            message = '已截取有效人脸并冻结。确认录入吗？不满意可重新截取，或取消退出。'
                        elif result == 'NO_FACE':
                            message = '彩色预览仅供调整位置；红外尚未检测到有效人脸，请正对镜头并检查红外照明。'
                        else:
                            raise RuntimeError('人脸采集失败：' + result[:240])
                    GLib.idle_add(update, frame, sample, message)
                    stop.wait(.25)
        except Exception as error:
            GLib.idle_add(update, None, None, str(error))
        finally:
            for child in (proc, color):
                if child and child.poll() is None:
                    child.terminate()
                    try:
                        child.wait(3)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait()

    confirm.connect('clicked', choose)
    retry.connect('clicked', retake)
    cancel.connect('clicked', lambda _: window.destroy())
    window.connect('destroy', close)
    window.show_all()
    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    Gtk.main()
    thread.join(20)
    if state['error']:
        raise RuntimeError(state['error'])
    if not state['saved']:
        raise RuntimeError('已取消人脸录入，未保存样本')
