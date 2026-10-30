"""Hardware-agnostic Morse trainer core logic.

This module is pure Python so it can run in both MicroPython and CPython.
"""

MORSE_TO_CHAR = {
    ".-": "A", "-...": "B", "-.-.": "C", "-..": "D", ".": "E", "..-.": "F",
    "--.": "G", "....": "H", "..": "I", ".---": "J", "-.-": "K", ".-..": "L",
    "--": "M", "-.": "N", "---": "O", ".--.": "P", "--.-": "Q", ".-.": "R",
    "...": "S", "-": "T", "..-": "U", "...-": "V", ".--": "W", "-..-": "X",
    "-.--": "Y", "--..": "Z",
    ".----": "1", "..---": "2", "...--": "3", "....-": "4", ".....": "5",
    "-....": "6", "--...": "7", "---..": "8", "----.": "9", "-----": "0"
}

LETTER_SET = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
TRAINING_POOLS = ("all", "letters")
INPUT_MODES = ("morse", "key")
CHAR_TO_MORSE = dict((v, k) for (k, v) in MORSE_TO_CHAR.items())


class NoopSounder:
    """Simple sound abstraction. Platforms can override with real sound output."""

    def symbol(self, _symbol):
        pass

    def play_code(self, code):
        for s in code:
            self.symbol(s)

    def commit(self, _code, _decoded):
        pass

    def training_result(self, _ok, _target, _decoded):
        pass


class MorseTrainer:
    def __init__(
        self,
        debounce_ms=120,
        letter_gap_ms=1200,
        max_text_chars=20,
        max_code_len=8,
        morse_map=None,
        diff_fn=None,
        logger=None,
        training_enabled=True,
        training_pool="all",
        input_mode="morse",
        sounder=None,
    ):
        self.debounce_ms = debounce_ms
        self.letter_gap_ms = letter_gap_ms
        self.max_text_chars = max_text_chars
        self.max_code_len = max_code_len
        self.morse_map = morse_map or MORSE_TO_CHAR

        self.diff_fn = diff_fn or (lambda a, b: a - b)
        self.logger = logger or (lambda *_args, **_kwargs: None)
        self.sounder = sounder or NoopSounder()

        self.text_out = ""
        self.current_code = ""
        self.last_input_ms = 0

        self.prev_dot = 1
        self.prev_dash = 1
        self.last_dot_press_ms = 0
        self.last_dash_press_ms = 0
        self.last_heartbeat_ms = 0

        # Training mode state
        self.training_enabled = training_enabled
        self.training_total = 0
        self.training_correct = 0
        self.training_target = None
        self.training_pool = "all"
        self._training_order = []
        self._training_index = 0
        self.input_mode = "morse"
        self.set_training_pool(training_pool, log=False)
        self.set_input_mode(input_mode, log=False)

    def _peek_target(self):
        if not self._training_order:
            return None
        return self._training_order[self._training_index % len(self._training_order)]

    def _advance_target(self):
        if not self._training_order:
            self.training_target = None
            return None
        self._training_index = (self._training_index + 1) % len(self._training_order)
        self.training_target = self._peek_target()
        return self.training_target

    def _allowed_targets(self):
        if self.training_pool == "letters":
            return LETTER_SET
        return set("0123456789") | LETTER_SET

    def _active_morse_map(self):
        allowed = self._allowed_targets()
        out = {}
        for code, ch in self.morse_map.items():
            if ch in allowed:
                out[code] = ch
        return out

    def _rebuild_training_order(self):
        active_map = self._active_morse_map()
        self._training_order = sorted(set(active_map.values()))
        self._training_index = 0
        self.training_target = self._peek_target() if self.training_enabled else None

    def set_training_pool(self, pool, log=True):
        if pool not in TRAINING_POOLS:
            raise ValueError("Invalid training pool '{}'. Use one of {}".format(pool, TRAINING_POOLS))
        self.training_pool = pool
        self._rebuild_training_order()
        if log:
            self.logger("[TRAIN] Pool set to '{}'".format(self.training_pool))
            if self.training_target is not None:
                self.logger("[TRAIN] Target: {}".format(self.training_target))

    def toggle_training_pool(self):
        if self.training_pool == "all":
            self.set_training_pool("letters")
        else:
            self.set_training_pool("all")

    def set_input_mode(self, mode, log=True):
        if mode not in INPUT_MODES:
            raise ValueError("Invalid input mode '{}'. Use one of {}".format(mode, INPUT_MODES))
        self.input_mode = mode
        if log:
            self.logger("[MODE] Input mode: {}".format(self.input_mode))

    def toggle_input_mode(self):
        if self.input_mode == "morse":
            self.set_input_mode("key")
        else:
            self.set_input_mode("morse")

    def preview_key(self, key_char):
        if not key_char:
            return None
        ch = key_char.upper()
        code = CHAR_TO_MORSE.get(ch)
        if code is None:
            self.logger("[KEY] '{}' has no Morse mapping".format(key_char))
            return None

        self.current_code = code
        self.text_out += ch
        if len(self.text_out) > self.max_text_chars:
            self.text_out = self.text_out[-self.max_text_chars :]

        self.logger("[KEY] {} -> {}".format(ch, code))
        self.sounder.play_code(code)
        return code

    def next_training_target(self):
        target = self._advance_target()
        if target is not None:
            self.logger("[TRAIN] New target: {}".format(target))
        return target

    def reset_training_score(self):
        self.training_total = 0
        self.training_correct = 0
        self.logger("[TRAIN] Score reset")

    def set_initial_button_states(self, dot_state, dash_state):
        self.prev_dot = dot_state
        self.prev_dash = dash_state
        self.logger(
            "[BOOT] Initial button states: dot={}, dash={} (1=idle, 0=pressed)".format(
                self.prev_dot, self.prev_dash
            )
        )
        if self.training_enabled and self.training_target is not None:
            self.logger("[TRAIN] Target: {}".format(self.training_target))

    def append_symbol(self, symbol, now_ms):
        if len(self.current_code) < self.max_code_len:
            self.current_code += symbol
            self.logger("[INPUT] {} -> current_code='{}'".format(symbol, self.current_code))
            self.sounder.symbol(symbol)
        else:
            self.logger("[WARN] current_code full, ignoring symbol '{}'".format(symbol))
        self.last_input_ms = now_ms

    def commit_letter(self):
        if not self.current_code:
            return None

        code = self.current_code
        decoded = self.morse_map.get(code, "?")

        self.text_out += decoded
        if len(self.text_out) > self.max_text_chars:
            self.text_out = self.text_out[-self.max_text_chars :]

        self.current_code = ""
        self.logger("[COMMIT] '{}' -> '{}' | text='{}'".format(code, decoded, self.text_out))
        self.sounder.commit(code, decoded)

        if self.training_enabled and self.training_target is not None:
            self.training_total += 1
            ok = decoded == self.training_target
            if ok:
                self.training_correct += 1
            self.logger(
                "[TRAIN] pool='{}' target='{}' got='{}' result={} score={}/{}".format(
                    self.training_pool,
                    self.training_target,
                    decoded,
                    "OK" if ok else "MISS",
                    self.training_correct,
                    self.training_total,
                )
            )
            self.sounder.training_result(ok, self.training_target, decoded)
            self._advance_target()
            self.logger("[TRAIN] Next target: {}".format(self.training_target))

        return decoded

    def process_buttons(self, dot_state, dash_state, now_ms):
        if dot_state != self.prev_dot:
            self.logger("[STATE] DOT changed: {} -> {}".format(self.prev_dot, dot_state))
        if dash_state != self.prev_dash:
            self.logger("[STATE] DASH changed: {} -> {}".format(self.prev_dash, dash_state))

        # Edge detect press (HIGH -> LOW)
        if self.prev_dot == 1 and dot_state == 0:
            dt = self.diff_fn(now_ms, self.last_dot_press_ms)
            if dt > self.debounce_ms:
                self.logger("[PRESS] DOT, dt={}ms".format(dt))
                self.append_symbol(".", now_ms)
                self.last_dot_press_ms = now_ms
            else:
                self.logger("[DEBOUNCE] DOT ignored, dt={}ms".format(dt))

        if self.prev_dash == 1 and dash_state == 0:
            dt = self.diff_fn(now_ms, self.last_dash_press_ms)
            if dt > self.debounce_ms:
                self.logger("[PRESS] DASH, dt={}ms".format(dt))
                self.append_symbol("-", now_ms)
                self.last_dash_press_ms = now_ms
            else:
                self.logger("[DEBOUNCE] DASH ignored, dt={}ms".format(dt))

        self.prev_dot = dot_state
        self.prev_dash = dash_state

    def tick(self, now_ms):
        if self.current_code and self.diff_fn(now_ms, self.last_input_ms) > self.letter_gap_ms:
            self.commit_letter()

        if self.diff_fn(now_ms, self.last_heartbeat_ms) > 1000:
            self.logger(
                "[HEARTBEAT] dot={}, dash={}, code='{}', text='{}'".format(
                    self.prev_dot, self.prev_dash, self.current_code, self.text_out
                )
            )
            self.last_heartbeat_ms = now_ms

    def get_training_status(self):
        return {
            "enabled": self.training_enabled,
            "pool": self.training_pool,
            "mode": self.input_mode,
            "target": self.training_target,
            "correct": self.training_correct,
            "total": self.training_total,
        }

    def get_display_lines(self):
        top = self.text_out[-self.max_text_chars :]
        bottom = self.current_code if self.current_code else "_"
        return top, bottom

    def _has_descendant(self, prefix, active_map, max_depth):
        for code in active_map:
            if code.startswith(prefix) and len(code) <= max_depth:
                return True
        return False

    def get_recommended_tree_depth(self):
        # Letters are depth<=4, numbers add depth 5
        return 5 if self.training_pool == "all" else 4

    def get_morse_tree_by_level_ascii(self, max_depth=None, width=80):
        """Render Morse tree by levels (top-down), centered to reduce clutter.

        Example style:
          . E      - T
         .. I   .- A    -. N   -- M
        """
        active_map = self._active_morse_map()
        if max_depth is None:
            max_depth = self.get_recommended_tree_depth()

        lines = ["root ∅".center(width).rstrip()]

        depth = 1
        while depth <= max_depth:
            # Keep only meaningful nodes (having descendants in active map)
            prefixes = [""]
            i = 0
            while i < depth:
                next_prefixes = []
                for p in prefixes:
                    next_prefixes.append(p + ".")
                    next_prefixes.append(p + "-")
                prefixes = next_prefixes
                i += 1

            node_pairs = []
            for code in prefixes:
                if self._has_descendant(code, active_map, max_depth):
                    ch = active_map.get(code, "")
                    node_pairs.append((code, ch))

            if not node_pairs:
                depth += 1
                continue

            def centered_join(labels, preferred_gap=2, min_gap=1):
                n = len(labels)
                if n == 1:
                    return labels[0].center(width).rstrip()

                label_len = 0
                for lbl in labels:
                    label_len += len(lbl)

                # pick the widest gap that still fits (bounded by preferred_gap)
                gap = preferred_gap
                while gap >= min_gap:
                    total = label_len + (n - 1) * gap
                    if total <= width:
                        line = (" " * gap).join(labels)
                        return line.center(width).rstrip()
                    gap -= 1

                return None

            spaced_labels = []
            compact_labels = []
            for code, ch in node_pairs:
                if ch:
                    spaced_labels.append("{} {}".format(code, ch))
                    compact_labels.append("{}{}".format(code, ch))
                else:
                    spaced_labels.append(code)
                    compact_labels.append(code)

            line = centered_join(spaced_labels, preferred_gap=2, min_gap=1)
            if line is None:
                line = centered_join(compact_labels, preferred_gap=2, min_gap=1)
            if line is None:
                # final fallback: hard clip compact line
                line = (" ".join(compact_labels))[: width - 1].center(width).rstrip()

            lines.append(line)

            depth += 1

        return lines

    def get_morse_tree_vertical_ascii(self, max_depth=5, width=80):
        """Older branch-style renderer kept for compatibility."""
        active_map = self._active_morse_map()

        lines = []

        def walk(prefix, depth, indent, branch_label, is_last):
            if prefix == "":
                lines.append("root=∅")
            else:
                ch = active_map.get(prefix, "_")
                connector = "└─" if is_last else "├─"
                line = "{}{} {}  {}={}".format(indent, connector, branch_label, prefix, ch)
                lines.append(line)

            if depth >= max_depth:
                return

            dot_code = prefix + "."
            dash_code = prefix + "-"
            show_dot = self._has_descendant(dot_code, active_map, max_depth)
            show_dash = self._has_descendant(dash_code, active_map, max_depth)

            children = []
            if show_dot:
                children.append((dot_code, "."))
            if show_dash:
                children.append((dash_code, "-"))

            idx = 0
            while idx < len(children):
                code, label = children[idx]
                child_last = idx == (len(children) - 1)
                next_indent = indent + ("   " if is_last and prefix != "" else "│  " if prefix != "" else "")
                walk(code, depth + 1, next_indent, label, child_last)
                idx += 1

        walk("", 0, "", "", True)

        out = []
        for line in lines:
            out.append(line if len(line) <= width else line[: width - 1])
        return out

    def get_morse_tree_ascii(self, max_depth=5, width=80):
        # Backward-compatible alias now pointing to level-based view
        return self.get_morse_tree_by_level_ascii(max_depth=max_depth, width=width)
