// Silence detection: call onSilence once speech has started and then stopped.
const MONITOR_INTERVAL_MS = 100;
const CALIBRATION_MS = 400;
const SILENCE_AFTER_SPEECH_MS = 1500;
const MAX_UTTERANCE_MS = 30000;
const MIN_SPEECH_RMS = 0.015;

export function monitorSilence(stream, onSilence) {
  const context = new AudioContext();
  const analyser = context.createAnalyser();
  analyser.fftSize = 2048;
  context.createMediaStreamSource(stream).connect(analyser);
  const samples = new Float32Array(analyser.fftSize);

  const startedAt = Date.now();
  let noiseFloor = 0;
  let speechStartedAt = null;
  let lastSpeechAt = 0;

  // An interval rather than requestAnimationFrame: rAF stops in a background tab.
  const timer = setInterval(() => {
    analyser.getFloatTimeDomainData(samples);
    const rms = Math.sqrt(samples.reduce((sum, s) => sum + s * s, 0) / samples.length);
    const now = Date.now();
    if (now - startedAt < CALIBRATION_MS) {
      noiseFloor = Math.max(noiseFloor, rms);
      return;
    }
    if (rms > Math.max(MIN_SPEECH_RMS, noiseFloor * 2.5)) {
      speechStartedAt ??= now;
      lastSpeechAt = now;
    }
    if (
      speechStartedAt !== null
      && (now - lastSpeechAt >= SILENCE_AFTER_SPEECH_MS || now - speechStartedAt >= MAX_UTTERANCE_MS)
    ) {
      clearInterval(timer);
      onSilence();
    }
  }, MONITOR_INTERVAL_MS);

  return () => {
    clearInterval(timer);
    void context.close();
  };
}
