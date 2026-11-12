// Silence detection: call onSilence once speech has started and then stopped.
const MONITOR_INTERVAL_MS = 100;
const CALIBRATION_MS = 400;
const SILENCE_AFTER_SPEECH_MS = 1500;
const MAX_UTTERANCE_MS = 30000;
const MIN_SPEECH_RMS = 0.008;
// Calibration can catch the end of Cuba's own voice or the user starting to
// speak at once; a floor that high would make the user's voice count as noise.
const MAX_NOISE_FLOOR = 0.012;
// How much louder than the room a sound must be to count as speech.
const SPEECH_OVER_NOISE = 1.8;
// Quiet moments pull the floor toward the room's real noise, a little each tick.
const FLOOR_ADAPT = 0.05;
const SPEECH_TICKS = 2;

/**
 * Options: onSpeech, called once when speech starts; minRms, a louder floor
 * (used while Cuba talks, so its own voice through speakers is not taken for the user's).
 */
export function monitorSilence(stream, onSilence, { onSpeech = null, minRms = MIN_SPEECH_RMS } = {}) {
  const context = new AudioContext();
  const analyser = context.createAnalyser();
  analyser.fftSize = 2048;
  context.createMediaStreamSource(stream).connect(analyser);
  const samples = new Float32Array(analyser.fftSize);

  const startedAt = Date.now();
  let noiseFloor = 0;
  let speechStartedAt = null;
  let lastSpeechAt = 0;
  let loudTicks = 0;

  // An interval rather than requestAnimationFrame: rAF stops in a background tab.
  const timer = setInterval(() => {
    analyser.getFloatTimeDomainData(samples);
    const rms = Math.sqrt(samples.reduce((sum, s) => sum + s * s, 0) / samples.length);
    const now = Date.now();
    if (now - startedAt < CALIBRATION_MS) {
      noiseFloor = Math.min(MAX_NOISE_FLOOR, Math.max(noiseFloor, rms));
      return;
    }
    if (rms > Math.max(minRms, noiseFloor * SPEECH_OVER_NOISE)) {
      // A click or a cough is one tick; speech holds for a few.
      loudTicks += 1;
      if (loudTicks >= SPEECH_TICKS && speechStartedAt === null) {
        speechStartedAt = now;
        onSpeech?.();
      }
      lastSpeechAt = now;
    } else {
      loudTicks = 0;
      noiseFloor = Math.min(MAX_NOISE_FLOOR, noiseFloor + (rms - noiseFloor) * FLOOR_ADAPT);
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
