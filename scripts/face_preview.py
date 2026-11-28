"""Local GTK preview using the same Biopass capture/detector as authentication."""
import os
from pathlib import Path
import select
import subprocess
import tempfile
import threading
import time


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
    box.pack_start(Gtk.Label(label='实时摄像头画面（红外图像可能为灰度）'), False, False, 0)
    box.pack_start(live, True, True, 0)
    box.pack_start(Gtk.Label(label='实际检测到的人脸裁剪（不是身份匹配或活体检测）'), False, False, 0)
    box.pack_start(detected, False, False, 0)
    status = Gtk.Label(label='正在打开摄像头并预热，请正对镜头约 40–60 厘米…')
    status.set_line_wrap(True)
    box.pack_start(status, False, False, 0)
    confirm = Gtk.Button(label='确认录入')
    cancel = Gtk.Button(label='取消')
    confirm.set_sensitive(False)
    buttons = Gtk.Box(spacing=12)
    buttons.pack_start(confirm, True, True, 0)
    buttons.pack_start(cancel, True, True, 0)
    box.pack_start(buttons, False, False, 0)
    stop = threading.Event()
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
        if sample:
            image(detected, sample, 160, 120)
        else:
            detected.clear()
        status.set_text(message)
        return False

    def choose(_):
        if state['sample'] is None or time.monotonic() - state['time'] > 2:
            status.set_text('当前有效人脸已过期，请保持正对镜头等待重新检测。')
            confirm.set_sensitive(False)
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

    def worker():
        proc = None
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
                started = time.monotonic()
                while not stop.is_set():
                    proc.stdin.write(b'FRAME\n')
                    header = read_line(proc.stdout)
                    if not header.startswith('OK '):
                        raise RuntimeError('预览采集失败：' + header[:240])
                    count = int(header[3:])
                    if not 0 < count <= 8 * 1024 * 1024:
                        raise RuntimeError('预览图像长度异常')
                    frame = read_bytes(proc.stdout, count)
                    sample = None
                    message = '预热中，请保持完整正脸可见…'
                    if time.monotonic() - started >= 2:
                        proc.stdin.write(f'CAPTURE {crop}\n'.encode())
                        result = read_line(proc.stdout)
                        if result == 'OK':
                            sample = crop.read_bytes()
                            crop.unlink()
                            message = '已检测到有效人脸，确认录入吗？'
                        elif result == 'NO_FACE':
                            message = '未检测到有效人脸。请看预览：若过暗、无画面或不是人脸，请取消并检查红外照明/摄像头节点；若清晰则调整距离。'
                        else:
                            raise RuntimeError('人脸采集失败：' + result[:240])
                    GLib.idle_add(update, frame, sample, message)
                    stop.wait(.25)
        except Exception as error:
            GLib.idle_add(update, None, None, str(error))
        finally:
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()

    confirm.connect('clicked', choose)
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
