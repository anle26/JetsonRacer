# -*- coding: utf-8 -*-
"""Camera, keyboard input and dataset recording in one Jupyter widget."""
from functools import partial
import time

# The terminal entry point applies the Jetson OpenBLAS setting before OpenCV.
from tools.keyboard_drive import DIRECTIONS, KEY_TIMEOUT
from jetracer_baseline.manual_collection import ManualDriveCollector


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
                           continuous_update=True, layout=w.Layout(width='380px'))
        self.keys.observe(self._typed, names='value')
        self.arrows = []
        for key, label in [('a', '↖ Trái'), ('w', '↑ Tiến'),
                           ('d', '↗ Phải'), ('s', '↓ Lùi')]:
            button = w.Button(description=label, layout=w.Layout(width='90px'))
            button.on_click(partial(self._pulse, key))
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
            self._enable_input(self._armed)
        except Exception as exc:
            self._on_emergency()
            self._log('Lỗi khởi động: %s' % exc)

    def _metadata(self):
        data = super()._metadata()
        del data['controller_mapping']
        data.update(input='keyboard', steering=self.angle.value,
                    throttle=self.throttle.value, key_timeout_s=KEY_TIMEOUT)
        return data

    def _typed(self, change):
        old, new = change['old'], change['new']
        if not new or not new.startswith(old):
            return
        appended = new[len(old):].lower()
        if ' ' in appended:
            self._on_emergency()
        elif len(set(appended)) == 1 and appended[-1] in DIRECTIONS:
            self._pulse(appended[-1])

    def _pulse(self, key, _button=None):
        try:
            with self._driver_io_lock:
                if not self._armed or not self._recording or self._closed:
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
            with self._driver_io_lock:
                if (self._last_control_time is not None and
                        now - self._last_control_time >= KEY_TIMEOUT):
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
        from IPython.display import display
        w = self.widgets
        display(w.VBox([
            w.HBox([self.btn_camera, self.mode]), self.preview,
            w.HBox([self.session_name, self.record_video]),
            w.HBox([self.throttle, self.angle]),
            w.HBox([self.btn_arm, self.btn_emergency]),
            self.keys, w.HBox(self.arrows), self.command_view,
            self.status, self.output, self.btn_close]))
        return self
