import time

import pigpio


class FanError(RuntimeError):
    pass


class FanController:
    def __init__(
        self,
        pin,
        frequency_hz=25000,
        min_start_duty_pct=10,
        tach_pin=None,
        tach_pulses_per_rev=2,
        pi_factory=pigpio.pi,
    ):
        self.pin = pin
        self.frequency_hz = frequency_hz
        self.min_start_duty_pct = min_start_duty_pct
        self.tach_pin = tach_pin
        self.tach_pulses_per_rev = tach_pulses_per_rev
        self._duty_pct = 0
        self._tach_callback = None
        self._tach_pulses = 0
        self._tach_read_pulses = 0
        self._tach_read_at = time.monotonic()

        self._pi = pi_factory()
        if not self._pi.connected:
            raise FanError(
                "could not connect to pigpiod - start it with "
                "'sudo systemctl start pigpiod' (see the README)"
            )
        # The fan spins up to full speed on its own if the PWM line reads as
        # disconnected, so drive the pin low immediately rather than leaving it
        # floating between construction and the first commanded duty.
        self.set_duty(0)
        if tach_pin is not None:
            self._start_tach(tach_pin)

    @classmethod
    def from_config(cls, config):
        return cls(
            pin=config["pin"],
            frequency_hz=config["frequency_hz"],
            min_start_duty_pct=config["min_start_duty_pct"],
            tach_pin=config["tach_pin"],
            tach_pulses_per_rev=config["tach_pulses_per_rev"],
        )

    def set_duty(self, percent):
        percent = max(0, min(100, float(percent)))
        # The fan needs roughly min_start_duty_pct to break static friction, so
        # a lower non-zero request would leave it stalled and silent rather than
        # slow. Zero still means off.
        if 0 < percent < self.min_start_duty_pct:
            percent = self.min_start_duty_pct

        result = self._pi.hardware_PWM(
            self.pin, self.frequency_hz, round(percent / 100 * 1_000_000)
        )
        if result != 0:
            raise FanError(
                f"pigpio hardware_PWM failed on GPIO{self.pin} (error {result})"
            )

        self._duty_pct = percent
        return percent

    @property
    def duty_pct(self):
        return self._duty_pct

    def read_rpm(self):
        """Average RPM since the previous call, or None with no tach wired.

        Counting between calls rather than sampling instantaneously means a slow
        poll gives a steadier figure, at the cost of lagging a speed change by
        up to one polling interval.
        """
        if self._tach_callback is None:
            return None

        now = time.monotonic()
        pulses = self._tach_pulses
        elapsed = now - self._tach_read_at
        counted = pulses - self._tach_read_pulses
        self._tach_read_at = now
        self._tach_read_pulses = pulses

        if elapsed <= 0:
            return 0.0
        return counted / self.tach_pulses_per_rev * 60.0 / elapsed

    def _start_tach(self, tach_pin):
        # The tach is an open-collector output, so it only pulls low - without
        # the pull-up there is no high level for it to pull away from and the
        # edge count stays at zero.
        self._pi.set_mode(tach_pin, pigpio.INPUT)
        self._pi.set_pull_up_down(tach_pin, pigpio.PUD_UP)
        # Well inside the ~2ms between edges at this fan's top speed, but long
        # enough to swallow contact bounce on the open-collector transition.
        self._pi.set_glitch_filter(tach_pin, 100)
        self._tach_read_at = time.monotonic()
        self._tach_callback = self._pi.callback(
            tach_pin, pigpio.FALLING_EDGE, self._on_tach_edge
        )

    def _on_tach_edge(self, gpio, level, tick):
        self._tach_pulses += 1

    def cleanup(self):
        try:
            if self._tach_callback is not None:
                self._tach_callback.cancel()
                self._tach_callback = None
            self.set_duty(0)
        finally:
            self._pi.stop()
