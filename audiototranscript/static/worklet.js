// Mono PCM sender: resamples to 16 kHz and posts Int16 chunks of 4096 samples.
const CHUNK = 4096;
const TARGET_RATE = 16000;

class PcmSender extends AudioWorkletProcessor {
  constructor() {
    super();
    this.out = new Float32Array(CHUNK);
    this.n = 0;
    this.pos = 0;   // fractional read position in the current block (-1 = prev sample)
    this.prev = 0;
  }

  push(v) {
    this.out[this.n++] = v;
    if (this.n === CHUNK) this.flush();
  }

  flush() {
    const i16 = new Int16Array(CHUNK);
    let sum = 0;
    for (let i = 0; i < CHUNK; i++) {
      const v = Math.max(-1, Math.min(1, this.out[i]));
      sum += v * v;
      i16[i] = v < 0 ? v * 32768 : v * 32767;
    }
    this.n = 0;
    this.port.postMessage({ pcm: i16.buffer, rms: Math.sqrt(sum / CHUNK) }, [i16.buffer]);
  }

  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch || !ch.length) return true;
    if (sampleRate === TARGET_RATE) {
      for (let i = 0; i < ch.length; i++) this.push(ch[i]);
      return true;
    }
    const step = sampleRate / TARGET_RATE;
    const n = ch.length;
    while (this.pos < n - 1) {
      const i = Math.floor(this.pos);
      const frac = this.pos - i;
      const a = i < 0 ? this.prev : ch[i];
      this.push(a + (ch[i + 1] - a) * frac);
      this.pos += step;
    }
    this.pos -= n;
    this.prev = ch[n - 1];
    return true;
  }
}

registerProcessor('pcm-sender', PcmSender);
