"""Interactive local shell Morse trainer.

Uses the same MorseTrainer core as hardware firmware.

Keys:
  ;  -> toggle input mode (morse/key)
  .  -> dot (morse mode)
  -  -> dash (morse mode)
  [A-Z0-9] -> preview key as Morse (key mode)
  n  -> next training target (morse mode)
  r  -> reset training score (morse mode)
  m  -> toggle training pool (morse mode)
  t  -> toggle tree view (morse mode)
  s  -> toggle sound (morse mode)
  x  -> clear current code (morse mode)
  c  -> clear decoded text (morse mode)
  Esc -> quit
"""

import sys
import time
import select
import termios
import tty

from morse_core import MorseTrainer


class TerminalBellSounder:
    """Local sound adapter (terminal bell based).

    Terminal bell has no frequency control, but we still mimic Morse timing.
    """

    WPM = 18
    DIT_S = 1.2 / WPM
    DAH_S = DIT_S * 3
    INTRA_GAP_S = DIT_S

    def __init__(self):
        self.enabled = True

    def _bell(self):
        if self.enabled:
            sys.stdout.write("\a")
            sys.stdout.flush()

    def symbol(self, symbol):
        self._bell()
        if symbol == ".":
            time.sleep(self.DIT_S)
        else:
            time.sleep(self.DAH_S)

    def play_code(self, code):
        i = 0
        while i < len(code):
            self.symbol(code[i])
            if i < len(code) - 1:
                time.sleep(self.INTRA_GAP_S)
            i += 1

    def commit(self, _code, decoded):
        if decoded == "?":
            self._bell()
            time.sleep(self.DAH_S)

    def training_result(self, ok, _target, _decoded):
        if ok:
            self._bell()
            time.sleep(self.DIT_S)
            self._bell()
        else:
            self._bell()
            time.sleep(self.DAH_S)


class RawMode:
    def __init__(self, stream):
        self.stream = stream
        self.fd = stream.fileno()
        self.old = None

    def __enter__(self):
        self.old = termios.tcgetattr(self.fd)
        tty.setcbreak(self.fd)
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.old is not None:
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old)


def interactive_session():
    if not sys.stdin.isatty():
        print("This interactive mode requires a TTY (run directly in a shell).")
        return 1

    start = time.monotonic()

    def now_ms():
        return int((time.monotonic() - start) * 1000)

    logs = []

    def logger(msg):
        logs.append(msg)
        if len(logs) > 10:
            del logs[0]

    sounder = TerminalBellSounder()
    trainer = MorseTrainer(
        logger=logger,
        training_enabled=True,
        training_pool="all",
        input_mode="morse",
        sounder=sounder,
    )
    trainer.set_initial_button_states(1, 1)

    dot_state = 1
    dash_state = 1
    last_render = -999
    show_tree = True

    def press_dot():
        nonlocal dot_state
        t = now_ms()
        dot_state = 0
        trainer.process_buttons(dot_state, dash_state, t)
        dot_state = 1
        trainer.process_buttons(dot_state, dash_state, t + 1)

    def press_dash():
        nonlocal dash_state
        t = now_ms()
        dash_state = 0
        trainer.process_buttons(dot_state, dash_state, t)
        dash_state = 1
        trainer.process_buttons(dot_state, dash_state, t + 1)

    def render():
        top, bottom = trainer.get_display_lines()
        tr = trainer.get_training_status()
        tree_lines = trainer.get_morse_tree_by_level_ascii(
            max_depth=trainer.get_recommended_tree_depth(), width=80
        )

        print("\x1b[2J\x1b[H", end="")
        print("Morse Trainer (Local Shell)")
        print(
            "Mode: {} | Target: {} | Score: {}/{} | Pool: {}".format(
                tr.get("mode"), tr.get("target"), tr.get("correct"), tr.get("total"), tr.get("pool")
            )
        )
        print("TEXT: {}".format(top or ""))
        print("CODE: {}".format(bottom))
        print()

        if show_tree:
            print("Morse tree (level view, centered, 80-col):")
            for line in tree_lines:
                print(line)
            print()

        print("Keys: ; input-mode | Esc quit")
        if tr.get("mode") == "morse":
            print("Morse mode keys: . dot | - dash | n next | r reset | m pool | t tree | s sound | x clear code | c clear text")
        else:
            print("Key mode keys: type A-Z or 0-9 to preview Morse sound/code")
        print("-" * 80)
        for line in logs:
            print(line)
        sys.stdout.flush()

    with RawMode(sys.stdin):
        while True:
            t = now_ms()
            trainer.tick(t)

            if t - last_render >= 100:
                render()
                last_render = t

            r, _, _ = select.select([sys.stdin], [], [], 0.02)
            if not r:
                continue

            ch = sys.stdin.read(1)
            if ch == "\x1b":
                break

            mode = trainer.get_training_status().get("mode")

            # Global non-alphanumeric mode switch (safe in key mode)
            if ch == ";":
                trainer.toggle_input_mode()
                continue

            if mode == "key":
                # In key mode, letters/numbers are always treated as preview input
                if ch.isalnum():
                    trainer.preview_key(ch)
                continue

            # Morse-mode controls
            if ch == ".":
                press_dot()
            elif ch == "-":
                press_dash()
            elif ch == "n":
                trainer.next_training_target()
            elif ch == "r":
                trainer.reset_training_score()
            elif ch == "m":
                trainer.toggle_training_pool()
            elif ch == "t":
                show_tree = not show_tree
                logger("[LOCAL] Tree view {}".format("ON" if show_tree else "OFF"))
            elif ch == "s":
                sounder.enabled = not sounder.enabled
                logger("[LOCAL] Sound {}".format("ON" if sounder.enabled else "OFF"))
            elif ch == "x":
                trainer.current_code = ""
                logger("[LOCAL] Cleared current code")
            elif ch == "c":
                trainer.text_out = ""
                logger("[LOCAL] Cleared decoded text")

    print("\nBye!")
    return 0


if __name__ == "__main__":
    raise SystemExit(interactive_session())
