# Project Requirements Notes (Draft)

These notes capture target hardware and behavior while core functionality is refined locally.

## Target Hardware

- **MCU board**: Adafruit Feather HUZZAH ESP8266 (battery-powered in final build)
- **Display**: SSD1306 OLED (same as current simulation)
- **Inputs**:
  - 2x push buttons (dot/dash input)
  - I2C keyboard PMOD: https://www.solder.party/docs/keyboard-pmod/
- **Audio output**: speaker/buzzer for Morse and feedback tones

## Morse Trainer Functional Goals

- Dot input on one control, dash input on another
- Parse dot/dash sequences into Morse characters
- Display:
  - running decoded text (top)
  - current dot/dash sequence in progress (bottom)
- Training mode:
  - active target character
  - correctness tracking / score
  - support both target pools:
    - letters-only
    - letters+numbers
- Local interactive mode should mirror hardware behavior closely

## Local Development Priority (Current Phase)

- Continue refining **core logic locally** (hardware-agnostic)
- Keep logic centralized in `morse_core.py`
- Use local interactive shell harness for rapid iteration
- Defer final hardware integration details until core UX is stable

## Planned ESP8266 Hardware Mapping (proposed)

- I2C bus (OLED + keyboard):
  - SDA: GPIO4 (D2)
  - SCL: GPIO5 (D1)
- Dot button: GPIO14 (D5), pull-up, active-low to GND
- Dash button: GPIO12 (D6), pull-up, active-low to GND
- Buzzer: GPIO13 (D7), PWM output

## ESP8266 Boot-Safety Notes

- Avoid using boot-strapping pins for GND buttons where possible:
  - GPIO0, GPIO2, GPIO15

## Future Integration Tasks

- Add keyboard PMOD input adapter (I2C)
- Add buzzer feedback adapter (tone patterns)
- Add deploy script for board upload/reset loop
- Add smoke-test checklist for on-device validation
