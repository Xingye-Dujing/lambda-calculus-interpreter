"""Generate a quiet, paper-like ambient loop for the promo.

No external dependencies. The result is a mono 22.05 kHz 16-bit WAV.
"""

import math
import random
import struct
import wave
from pathlib import Path

SR = 22050
DURATION = 48.0
N = int(SR * DURATION)
rng = random.Random(7)

# D minor-ish, deliberately low and unresolved.
chords = [
    [73.42, 110.00, 146.83, 174.61],  # D2 A2 D3 F3
    [58.27, 87.31, 116.54, 174.61],   # Bb1 F2 Bb2 F3
    [65.41, 98.00, 130.81, 196.00],   # C2 G2 C3 G3
    [73.42, 110.00, 146.83, 220.00],  # D2 A2 D3 A3
]
chord_len = DURATION / len(chords)


def smoothstep(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return x * x * (3.0 - 2.0 * x)


samples = []
for i in range(N):
    t = i / SR
    idx = min(len(chords) - 1, int(t / chord_len))
    local = (t - idx * chord_len) / chord_len
    chord = chords[idx]
    # Slow breathing pad, no sharp attacks.
    env = 0.55 + 0.45 * math.sin(math.pi * local)
    value = 0.0
    for j, f in enumerate(chord):
        detune = 1.0 + (j - 1.5) * 0.0009
        value += math.sin(2.0 * math.pi * f * detune * t + j * 0.7) / (j + 2)
    # A very quiet high air layer.
    value += 0.025 * math.sin(2.0 * math.pi * 880.0 * t + 0.3)
    value += 0.012 * math.sin(2.0 * math.pi * 1318.5 * t + 1.1)
    value *= env / 2.1
    # Gentle noise floor, more like paper than rain.
    value += rng.uniform(-1.0, 1.0) * 0.0018
    # Global fade to keep the loop kind.
    fade = min(smoothstep(t / 3.0), smoothstep((DURATION - t) / 3.0))
    samples.append(int(max(-1.0, min(1.0, value * fade)) * 12000))

out = Path(__file__).resolve().parents[1] / "public" / "audio" / "ambient.wav"
out.parent.mkdir(parents=True, exist_ok=True)
with wave.open(str(out), "w") as f:
    f.setnchannels(1)
    f.setsampwidth(2)
    f.setframerate(SR)
    f.writeframes(b"".join(struct.pack("<h", s) for s in samples))
print(out, out.stat().st_size)
