# -*- coding: utf-8 -*-
"""Lái bằng bàn phím và thu ảnh trong Terminal của JupyterLab trên Jetson."""

import argparse
from contextlib import ExitStack, contextmanager
import os
import platform
import select
import signal
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))

# JetPack 4 NumPy wheels can select an unsupported OpenBLAS kernel on Nano.
# Set this before camera imports OpenCV and NumPy, as in the BTC notebook.
if sys.platform == 'linux' and platform.machine() == 'aarch64':
    os.environ.setdefault('OPENBLAS_CORETYPE', 'ARMV8')

from jetracer_baseline.camera import LatestFrameGrabber, build_source
from jetracer_baseline.config import load_config
from jetracer_baseline.control.driver import build_driver
from jetracer_baseline.manual_collection import DatasetSessionWriter


# A terminal sends repeated characters while a key is held, no key-up event.
KEY_TIMEOUT = 0.25
DIRECTIONS = {'w': (0, 1), 'a': (-1, 1), 'd': (1, 1), 's': (0, -1)}


@contextmanager
def terminal_input():
    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)

    def read_keys():
        if not select.select([fd], [], [], 0.02)[0]:
            return ''
        data = os.read(fd, 4096)
        return data.decode('ascii', 'ignore') if data else 'x'

    try:
        tty.setcbreak(fd)
        # Receive Ctrl-Z as a key so it cannot suspend an active driver.
        attrs = termios.tcgetattr(fd)
        attrs[6][termios.VSUSP] = b'\x00'
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        termios.tcflush(fd, termios.TCIFLUSH)
        yield read_keys
    finally:
        termios.tcsetattr(fd, termios.TCSAFLUSH, old)


def drive(read_keys, camera, driver, writer, throttle, steering):
    armed = False
    direction = (0, 0)
    command = (0.0, 0.0)
    expiry = next_sample = 0.0
    previous_id = -1
    last_frame_time = next_status = time.monotonic()
    recording = False
    print('R: bat ghi va mo lai | W: tien | A/D: tien + re trai/phai | S: lui')
    print('Space: cat ga va khoa lai (R de mo lai) | X: dung va luu phien')
    while True:
        keys = read_keys()
        now = time.monotonic()
        if 'x' in keys or '\x03' in keys:
            return
        if writer.error:
            raise writer.error
        if camera.error or camera.eof:
            raise IOError('Camera da dung: %s' % (camera.error or 'het anh'))

        # Sample the previous command before applying newly received input.
        if now >= next_sample:
            frame, frame_id = camera.read()
            if frame is not None and frame_id != previous_id:
                last_frame_time = now
                previous_id = frame_id
                if recording:
                    writer.write(frame, frame_id, time.time(), now,
                                 direction[0], direction[1], command[0], command[1],
                                 direction != (0, 0), False)
            if now - last_frame_time > 1.0:
                raise IOError('Camera khong cap nhat anh.')
            next_sample = now + 0.2

        # ESC sequences include letters (e.g. arrow-left ends in D).
        if ' ' in keys or '\x1b' in keys or '\x1a' in keys:
            driver.stop()
            armed = False
            direction = (0, 0)
            command = (0.0, 0.0)
            print('Da khoa lai. R de tiep tuc.')
        elif 'r' in keys and not armed:
            recording = armed = True
            print('Dang ghi. Giu W/A/D/S de lai.')
        elif armed and keys and keys[-1] in DIRECTIONS:
            direction = DIRECTIONS[keys[-1]]
            command = (direction[0] * steering, direction[1] * throttle)
            driver.set(*command)
            expiry = now + KEY_TIMEOUT
        elif direction != (0, 0) and now >= expiry:
            driver.stop()
            direction = (0, 0)
            command = (0.0, 0.0)
        if recording and now >= next_status:
            print('Da luu %d anh | lai %+.2f | ga %+.2f' %
                  (writer.count, command[0], command[1]), flush=True)
            next_status = now + 2.0


def interrupted(_signal, _frame):
    raise KeyboardInterrupt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session', default='speed_keyboard')
    parser.add_argument('--throttle', type=float, default=0.15)
    parser.add_argument('--steering', type=float, default=0.45)
    parser.add_argument('--dry-run', action='store_true',
                        help='Thu camera va phim, khong gui lenh toi xe.')
    args = parser.parse_args()
    if not 0 < args.throttle <= 0.30 or not 0 < args.steering <= 0.60:
        parser.error('Can 0 < throttle <= 0.30 va 0 < steering <= 0.60.')
    if os.name != 'posix' or not sys.stdin.isatty():
        parser.error('Chay lenh nay trong Terminal tren Jetson.')
    for sig in (signal.SIGHUP, signal.SIGTERM):
        signal.signal(sig, interrupted)

    os.chdir(ROOT)
    cfg = load_config('configs/default.yaml')
    with ExitStack() as stack:
        camera = LatestFrameGrabber(build_source(cfg, 'csi'))
        stack.callback(camera.stop)
        camera.start()
        if camera.error or camera.read()[0] is None:
            raise IOError('Khong mo duoc camera: %s' % camera.error)
        backend = 'dryrun' if args.dry_run else 'nvidia'
        writer = DatasetSessionWriter('data/driving', args.session, metadata={
            'input': 'keyboard', 'driver': backend, 'target_fps': 5,
            'throttle': args.throttle, 'steering': args.steering})
        stack.callback(writer.close)
        driver = build_driver(backend, cfg)
        stack.callback(driver.close)
        driver.stop()
        print('Thu muc:', os.path.abspath(writer.session_dir))
        try:
            with terminal_input() as read_keys:
                drive(read_keys, camera, driver, writer, args.throttle, args.steering)
        finally:
            driver.stop()
    if writer.error:
        raise writer.error
    print('Da luu %d anh vao %s' % (writer.count, writer.session_dir))


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('Da dung phien.')
