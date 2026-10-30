"""Local (CPython) simulation harness for morse_core.MorseTrainer.

Run:
  python3 local_morse_test.py
"""

from morse_core import MorseTrainer


def run_demo():
    t = MorseTrainer(letter_gap_ms=500, logger=print)
    now = 0

    # idle high-high
    t.set_initial_button_states(1, 1)

    def step(ms, dot=1, dash=1):
        nonlocal now
        now += ms
        t.process_buttons(dot, dash, now)
        t.tick(now)

    # Enter "A" (.-): dot press/release, dash press/release, then pause
    step(200, dot=0, dash=1)  # dot press
    step(80, dot=1, dash=1)   # dot release

    step(250, dot=1, dash=0)  # dash press
    step(80, dot=1, dash=1)   # dash release

    step(700, dot=1, dash=1)  # letter gap commit

    top, bottom = t.get_display_lines()
    print("\nFinal display top='{}' bottom='{}'".format(top, bottom))
    print("Expected top to include: A")


if __name__ == "__main__":
    run_demo()
