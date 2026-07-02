import wave, math, struct
import os

def generate_tone(filename, freq_start, freq_end, duration, vol=0.5):
    sample_rate = 44100
    n_samples = int(sample_rate * duration)
    with wave.open(filename, 'w') as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sample_rate)
        for i in range(n_samples):
            t = i / sample_rate
            # exponential frequency sweep
            freq = freq_start + (freq_end - freq_start) * (i / n_samples)
            # soft envelope (fade in/out)
            env = math.sin(math.pi * i / n_samples)
            v = math.sin(2 * math.pi * freq * t) * vol * env
            packed = struct.pack('h', int(v * 32767))
            f.writeframes(packed)

if __name__ == '__main__':
    # Start sound: soft rising tone 400->600 over 0.15s
    generate_tone('static/sounds/start.wav', 400, 600, 0.15, 0.25)
    # Stop sound: soft falling tone 600->400 over 0.15s
    generate_tone('static/sounds/stop.wav', 600, 400, 0.15, 0.25)
