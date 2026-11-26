# -*- coding: utf-8 -*-
"""Camera, keyboard input and dataset recording in one Jupyter widget."""
from pathlib import Path
import time
import uuid

# The terminal entry point applies the Jetson OpenBLAS setting before OpenCV.
from tools.keyboard_drive import DIRECTIONS
from jetracer_baseline.manual_collection import ManualDriveCollector

HOLD_TIMEOUT = 0.40


class KeyboardDrivePanel(ManualDriveCollector):
    def __init__(self, **kwargs):
        super().__init__(driver_kind='dryrun', **kwargs)
        w = self.widgets
        self.mode = w.ToggleButtons(options=[('Thử phím', 'dryrun'),
                                             ('Lái thật', 'nvidia')])
        self.session_name.value = 'speed_vong_01'
        self.session_name.description = 'Tên phiên'
        self.record_video.description = 'Lưu thêm video'
        self.record_video.value = False
        self.throttle = w.FloatSlider(description='Ga', value=0.15, min=0.05,
                                      max=0.30, step=0.01)
        self.angle = w.FloatSlider(description='Lái', value=0.45, min=0.05,
                                   max=0.60, step=0.05)
        self.keys = w.Text(placeholder='Bấm vào đây rồi giữ W, A, S hoặc D',
                           layout=w.Layout(width='380px')).add_class('drive-keys')
        self._panel_id = 'drive-' + uuid.uuid4().hex
        self._browser_ready = False
        self._armed_at = 0.0
        self._last_clock = 0.0
        self._clock = w.HTML(layout=w.Layout(display='none')).add_class('drive-clock')
        self._events = w.Text(continuous_update=True, layout=w.Layout(display='none'))
        self._events.add_class('drive-events')
        self._events.observe(self._browser_event, names='value')
        self.arrows = []
        for key, label in [('a', '↖ Trái'), ('w', '↑ Tiến'),
                           ('d', '↗ Phải'), ('s', '↓ Lùi')]:
            button = w.Button(description=label, layout=w.Layout(width='90px'))
            button.add_class('drive-' + key)
            self.arrows.append(button)
        self.btn_camera.description = 'Mở camera'
        self.btn_arm.description = 'Bắt đầu ghi và lái'
        self.btn_emergency.description = 'Dừng xe và lưu phiên'
        self.btn_close.description = 'Đóng camera'
        self._enable_input(False)

    def _enable_input(self, enabled):
        for widget in [self.keys] + self.arrows:
            widget.disabled = not enabled
        for widget in (self.mode, self.session_name, self.record_video,
                       self.btn_arm, self.throttle, self.angle):
            widget.disabled = enabled

    def _on_arm(self, _button=None):
        if self._closed or self._armed:
            return
        if not self._browser_ready:
            self._set_status('Hãy cho chạy JavaScript ở đầu ra của ô notebook, rồi thử lại.')
            return
        if time.monotonic() - self._frame_received_at > 1.0:
            self._set_status('Hãy mở camera và chờ thấy ảnh trực tiếp.')
            return
        try:
            if self._driver is not None and self.driver_kind != self.mode.value:
                self._driver.close()
                self._driver = None
            self.driver_kind = self.mode.value
            self._ensure_driver()
            self._zero_command()
            self.keys.value = ''
            self._armed = True
            self._on_start_recording()
            self._armed = self._recording
            self._armed_at = time.monotonic()
            self._clock.value = '<span data-tick="%s"></span>' % self._armed_at
            self._enable_input(self._armed)
        except Exception as exc:
            self._on_emergency()
            self._log('Lỗi khởi động: %s' % exc)

    def _metadata(self):
        data = super()._metadata()
        del data['controller_mapping']
        data.update(input='keyboard', steering=self.angle.value,
                    throttle=self.throttle.value, key_timeout_s=HOLD_TIMEOUT)
        return data

    def _browser_event(self, change):
        message = change['new']
        if message == 'ready':
            self._browser_ready = True
            return
        try:
            _sequence, timestamp, action, key = message.split('|')
            issued = float(timestamp)
        except ValueError:
            return
        if not self._armed or self._closed:
            return
        if action == 'stop':
            self._on_emergency()
            return
        if action == 'release':
            self._zero_command()
            return
        if action not in ('press', 'hold') or key not in DIRECTIONS:
            return
        # Echo the kernel's clock so delayed browser input expires even if
        # the laptop and Jetson wall clocks differ.
        if not self._armed_at <= issued <= time.monotonic() <= issued + HOLD_TIMEOUT:
            return
        try:
            with self._driver_io_lock:
                if not self._armed or not self._recording or self._closed:
                    return
                if action == 'hold' and self._last_control_time is None:
                    return
                steer, gas = DIRECTIONS[key]
                command = (steer * self.angle.value, gas * self.throttle.value)
                self._driver.set(*command)
                with self._state_lock:
                    self._steering_raw, self._throttle_raw = steer, gas
                    self._steering_cmd, self._throttle_cmd = command
                    self._deadman_pressed = True
                    self._last_control_time = time.monotonic()
                self.command_view.value = self._command_html()
        except Exception as exc:
            self._on_emergency()
            self._log('Lỗi điều khiển: %s' % exc)

    def _control_loop(self):
        while not self._stop_event.wait(0.025):
            now = time.monotonic()
            if self._armed and now - self._last_clock >= 0.10:
                self._clock.value = '<span data-tick="%s"></span>' % now
                self._last_clock = now
            with self._driver_io_lock:
                if (self._last_control_time is not None and
                        now - self._last_control_time >= HOLD_TIMEOUT):
                    self._zero_command()
            if not self.keys.disabled and self._armed and (
                    not self._recording or now - self._frame_received_at > 1.0):
                self._on_emergency()
            elif not self.keys.disabled and not self._armed:
                self._enable_input(False)

    def _on_emergency(self, _button=None):
        super()._on_emergency()
        self._enable_input(False)
        if self.last_session_dir:
            self._set_status('Xe đã dừng. Thư mục phiên: ' + self.last_session_dir)

    def close(self):
        super().close()
        self.keys.disabled = True
        for button in self.arrows:
            button.disabled = True

    def show(self):
        from IPython.display import Javascript, display
        w = self.widgets
        display(w.VBox([
            w.HBox([self.btn_camera, self.mode]), self.preview,
            w.HBox([self.session_name, self.record_video]),
            w.HBox([self.throttle, self.angle]),
            w.HBox([self.btn_arm, self.btn_emergency]),
            self.keys, w.HBox(self.arrows), self.command_view,
            self.status, self.output, self.btn_close, self._clock,
            self._events]).add_class(self._panel_id))
        script = Path(__file__).with_name('keyboard_drive_input.js').read_text(encoding='utf-8')
        display(Javascript(script.replace('__PANEL_ID__', self._panel_id)))
        return self
