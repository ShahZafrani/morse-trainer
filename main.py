from machine import Pin, I2C, PWM
from time import sleep_ms, ticks_ms, ticks_diff
import ssd1306

from morse_core import MorseTrainer

# ----- Hardware setup -----
i2c = I2C(0, scl=Pin(22), sda=Pin(21))
oled = ssd1306.SSD1306_I2C(128, 64, i2c)

# Buttons are wired to GND when pressed, so use pull-ups:
# btn1 (GPIO18) = dot, btn2 (GPIO17) = dash
dot_btn = Pin(18, Pin.IN, Pin.PULL_UP)
dash_btn = Pin(17, Pin.IN, Pin.PULL_UP)

# Set this to your buzzer pin on real hardware.
# For Feather HUZZAH ESP8266 target, use GPIO13 (D7).
BUZZER_PIN = 13


class HardwareBuzzerSounder:
    """Morse-style sidetone for hardware buzzer."""

    SIDETONE_HZ = 650
    WPM = 18
    DIT_MS = int(1200 / WPM)
    DAH_MS = DIT_MS * 3
    INTRA_GAP_MS = DIT_MS

    def __init__(self, pin_num):
        self.enabled = True
        try:
            self.pwm = PWM(Pin(pin_num))
            self._set_duty(0)
        except Exception as exc:
            print("[SOUND] Buzzer init failed:", exc)
            self.pwm = None
            self.enabled = False

    def _set_duty(self, value):
        try:
            self.pwm.duty(value)
        except Exception:
            self.pwm.duty_u16(value)

    def beep(self, freq, duration_ms, duty=512):
        if not self.enabled or self.pwm is None:
            return
        try:
            self.pwm.freq(freq)
            self._set_duty(duty)
            sleep_ms(duration_ms)
        finally:
            self._set_duty(0)

    def symbol(self, symbol):
        if symbol == ".":
            self.beep(self.SIDETONE_HZ, self.DIT_MS, 420)
        else:
            self.beep(self.SIDETONE_HZ, self.DAH_MS, 420)

    def play_code(self, code):
        i = 0
        while i < len(code):
            self.symbol(code[i])
            if i < len(code) - 1:
                sleep_ms(self.INTRA_GAP_MS)
            i += 1

    def commit(self, _code, decoded):
        if decoded == "?":
            self.beep(300, self.DAH_MS, 480)

    def training_result(self, ok, _target, _decoded):
        if ok:
            self.beep(700, self.DIT_MS, 350)
            sleep_ms(self.DIT_MS)
            self.beep(900, self.DIT_MS, 350)
        else:
            self.beep(260, self.DAH_MS + self.DIT_MS, 480)


class I2CKeyboardReader:
    """Minimal non-blocking I2C keyboard reader.

    Assumes keyboard returns one byte from readfrom(addr, 1).
    Printable ASCII is returned as single-char strings.
    Special keys return symbolic names so they won't overlap with A-Z/0-9.
    """

    # These values are placeholders for the keyboard PMOD special keys.
    # If your module uses different scan codes, update this map.
    SPECIAL_BYTE_MAP = {
        0x81: "LSHIFT",
        0x82: "RSHIFT",
        0x83: "ALT",
        0x84: "SYM",
    }

    def __init__(self, bus, candidate_addrs=(0x08, 0x10, 0x20, 0x3F)):
        self.bus = bus
        self.addr = None
        self.last_byte = 0

        found = bus.scan()
        for a in candidate_addrs:
            if a in found:
                self.addr = a
                break

        if self.addr is None and found:
            self.addr = found[0]

        if self.addr is not None:
            print("[KBD] using I2C addr", hex(self.addr))
        else:
            print("[KBD] no I2C keyboard found")

    def read_key(self):
        if self.addr is None:
            return None

        try:
            raw = self.bus.readfrom(self.addr, 1)
        except Exception:
            return None

        if not raw:
            return None

        b = raw[0]
        if b == 0:
            self.last_byte = 0
            return None

        # Basic de-dup on held key
        if b == self.last_byte:
            return None
        self.last_byte = b

        if b in self.SPECIAL_BYTE_MAP:
            return self.SPECIAL_BYTE_MAP[b]

        if 32 <= b <= 126:
            return chr(b)

        # Unknown non-ASCII byte: keep quiet by default
        return None


sounder = HardwareBuzzerSounder(BUZZER_PIN)
keyboard = I2CKeyboardReader(i2c)
trainer = MorseTrainer(
    diff_fn=ticks_diff,
    logger=print,
    training_enabled=True,
    training_pool="all",
    input_mode="morse",
    sounder=sounder,
)
print("[BOOT] Morse trainer starting")
trainer.set_initial_button_states(dot_btn.value(), dash_btn.value())

# Button gestures (morse mode):
# - short press/release: next training target
# - hold >1200ms: reset training score
# - hold >2500ms: toggle training pool all<->letters
# - hold >4000ms: toggle input mode morse<->key
#
# Key mode commands (from I2C keyboard special keys):
# - LSHIFT: toggle input mode
# - RSHIFT: next target
# - ALT: toggle training pool
# - SYM: reset score
both_down_since = None
both_reset_fired = False
both_pool_fired = False
both_input_mode_fired = False


def draw(top_text, bottom_code, status):
    oled.fill(0)

    target = status.get("target") or "-"
    score = "{}/{}".format(status.get("correct", 0), status.get("total", 0))
    pool = "A" if status.get("pool") == "all" else "L"
    mode = "M" if status.get("mode") == "morse" else "K"

    oled.text("{}{} TG:{} {}".format(mode, pool, target, score), 0, 0)
    oled.text(top_text[-21:], 0, 16)
    oled.text("Code:", 0, 48)
    oled.text(bottom_code, 42, 48)
    oled.show()


first_top, first_bottom = trainer.get_display_lines()
draw(first_top, first_bottom, trainer.get_training_status())

while True:
    now = ticks_ms()

    dot_state = dot_btn.value()
    dash_state = dash_btn.value()
    both_pressed = (dot_state == 0 and dash_state == 0)

    mode = trainer.get_training_status().get("mode")

    # Keep button gestures in morse mode only (avoid conflicts in key mode)
    if mode == "morse":
        if both_pressed:
            if both_down_since is None:
                both_down_since = now
                both_reset_fired = False
                both_pool_fired = False
                both_input_mode_fired = False
            else:
                hold_ms = ticks_diff(now, both_down_since)
                if (not both_reset_fired) and hold_ms > 1200:
                    trainer.reset_training_score()
                    both_reset_fired = True
                if (not both_pool_fired) and hold_ms > 2500:
                    trainer.toggle_training_pool()
                    both_pool_fired = True
                if (not both_input_mode_fired) and hold_ms > 4000:
                    trainer.toggle_input_mode()
                    both_input_mode_fired = True
        else:
            if both_down_since is not None and (not both_reset_fired) and (not both_pool_fired) and (not both_input_mode_fired):
                trainer.next_training_target()
            both_down_since = None
            both_reset_fired = False
            both_pool_fired = False
            both_input_mode_fired = False

        if not both_pressed:
            trainer.process_buttons(dot_state, dash_state, now)

    else:
        # Key mode: commands mapped to non-alphanumeric special keys
        key = keyboard.read_key()
        if key is not None:
            if key == "LSHIFT":
                trainer.toggle_input_mode()
            elif key == "RSHIFT":
                trainer.next_training_target()
            elif key == "ALT":
                trainer.toggle_training_pool()
            elif key == "SYM":
                trainer.reset_training_score()
            elif len(key) == 1 and key.isalnum():
                trainer.preview_key(key)

    trainer.tick(now)

    top, bottom = trainer.get_display_lines()
    draw(top, bottom, trainer.get_training_status())
    sleep_ms(20)
