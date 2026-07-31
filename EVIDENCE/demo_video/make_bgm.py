#!/usr/bin/env python3
"""Unprompt デモ用BGM合成(完全自作・権利フリー)。
静かなアンビエントパッド+疎なペンタトニックの鈴音。48kHz stereo WAV。"""
import wave, math, struct, random

SR = 48000
DUR = 120.0
N = int(SR * DUR)

def note(name):
    names = {'C':0,'C#':1,'D':2,'D#':3,'E':4,'F':5,'F#':6,'G':7,'G#':8,'A':9,'A#':10,'B':11}
    pc, octv = name[:-1], int(name[-1])
    midi = 12 * (octv + 1) + names[pc]
    return 440.0 * 2 ** ((midi - 69) / 12)

# コード進行: Am9 → Fmaj9 → Cmaj9 → Em7(各8秒・32秒ループ)
chords = [
    ['A2','E3','B3','C4','G4'],
    ['F2','C3','A3','E4','G4'],
    ['C3','G3','E4','B4','D5'],
    ['E2','B2','G3','D4','F#4'],
]
CHORD_LEN = 8.0

# 鈴音: Aマイナーペンタ、疎に(平均2.4秒に1音)、決定的シード
random.seed(20260731)
pent = ['A4','C5','D5','E5','G5','A5']
plucks = []  # (start_time, freq)
t = 2.0
while t < DUR - 8:
    plucks.append((t, note(random.choice(pent))))
    t += 1.6 + random.random() * 1.8

L = [0.0] * N
R = [0.0] * N

# パッド: 各コードを2秒クロスフェードで重ねる
for ci in range(int(DUR / CHORD_LEN) + 1):
    t0 = ci * CHORD_LEN
    chord = chords[ci % 4]
    s0 = int(t0 * SR); s1 = min(int((t0 + CHORD_LEN + 2.0) * SR), N)
    for nm in chord:
        f = note(nm)
        phL = random.random() * 6.28; phR = random.random() * 6.28
        detL = 1.0 + 0.0007; detR = 1.0 - 0.0007
        for s in range(s0, s1):
            tt = s / SR - t0
            # エンベロープ: 2秒アタック・2秒リリースの台形
            if tt < 2.0: env = tt / 2.0
            elif tt > CHORD_LEN: env = max(0.0, 1.0 - (tt - CHORD_LEN) / 2.0)
            else: env = 1.0
            if env <= 0: continue
            # ゆらぎ(6秒周期の呼吸)
            env *= 0.8 + 0.2 * math.sin(2 * math.pi * (s / SR) / 6.0 + phL)
            w = 2 * math.pi * f * s / SR
            base = math.sin(w * detL + phL) + 0.35 * math.sin(2 * w * detL + phL)
            L[s] += 0.030 * env * base
            base2 = math.sin(w * detR + phR) + 0.35 * math.sin(2 * w * detR + phR)
            R[s] += 0.030 * env * base2

# 鈴音: 減衰サイン+軽い倍音、L/R交互に振る
side = 1
for (st, f) in plucks:
    s0 = int(st * SR); s1 = min(s0 + int(3.0 * SR), N)
    pan = 0.35 * side; side = -side
    for s in range(s0, s1):
        tt = (s - s0) / SR
        env = math.exp(-tt * 1.8) * min(1.0, tt / 0.01)
        v = 0.050 * env * (math.sin(2 * math.pi * f * tt) + 0.2 * math.sin(2 * math.pi * f * 2 * tt))
        L[s] += v * (1 - pan) / 2 * 2
        R[s] += v * (1 + pan) / 2 * 2

# 全体フェード(イン3秒・アウト6秒)+ソフトクリップ
out = wave.open('/private/tmp/claude-501/-Users-kishimotosatoshi-Documents-MERGE2026-MERGE2026-FABLE5-AUTONOMOUS-DELIBERATION-v4-0-20260728/89c56fd4-883d-45e5-9bdc-87446ac8a2c9/scratchpad/bgm.wav', 'w')
out.setnchannels(2); out.setsampwidth(2); out.setframerate(SR)
frames = bytearray()
for s in range(N):
    tsec = s / SR
    g = 1.0
    if tsec < 3.0: g = tsec / 3.0
    if tsec > DUR - 6.0: g = min(g, (DUR - tsec) / 6.0)
    l = math.tanh(L[s] * g * 1.2); r = math.tanh(R[s] * g * 1.2)
    frames += struct.pack('<hh', int(l * 32000), int(r * 32000))
out.writeframes(bytes(frames)); out.close()
print('bgm.wav written')
