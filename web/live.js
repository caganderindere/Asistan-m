// Talking to Cuba over Gemini Live: microphone up as 16 kHz PCM, Cuba's voice down as 24 kHz PCM.

const CHUNK = 640; // 40 ms of 16 kHz audio per message

// Runs on the audio thread: turns the microphone into 16-bit samples, a chunk at a time.
const CAPTURE = `
class Capture extends AudioWorkletProcessor {
  constructor() { super(); this.chunk = new Int16Array(${CHUNK}); this.filled = 0; }
  process(inputs) {
    const samples = inputs[0][0];
    if (samples) {
      for (let i = 0; i < samples.length; i++) {
        this.chunk[this.filled++] = Math.max(-1, Math.min(1, samples[i])) * 0x7FFF;
        if (this.filled === this.chunk.length) {
          this.port.postMessage(this.chunk.buffer.slice(0));
          this.filled = 0;
        }
      }
    }
    return true;
  }
}
registerProcessor('cuba-capture', Capture);
`;

/**
 * onEvent receives the server's events (ready, user, cuba, tool, turn_complete, error, failed, closed);
 * onSpeaking(true|false) tells when Cuba's voice starts and stops.
 */
export function createLive({ onEvent, onSpeaking }) {
  let ws = null;
  let mic = null; // { context, source, node }
  let player = null; // AudioContext at 24 kHz
  let playing = new Set();
  let nextAt = 0;

  function play(buffer) {
    player ??= new AudioContext({ sampleRate: 24000 });
    const pcm = new Int16Array(buffer);
    const audio = player.createBuffer(1, pcm.length, 24000);
    const channel = audio.getChannelData(0);
    for (let i = 0; i < pcm.length; i++) channel[i] = pcm[i] / 0x8000;
    const source = player.createBufferSource();
    source.buffer = audio;
    source.connect(player.destination);
    // Chunks are laid end to end; a gap means Cuba had paused, so start now.
    nextAt = Math.max(nextAt, player.currentTime + 0.03);
    source.start(nextAt);
    nextAt += audio.duration;
    if (!playing.size) onSpeaking(true);
    playing.add(source);
    source.onended = () => {
      playing.delete(source);
      if (!playing.size) onSpeaking(false);
    };
  }

  /** The user talked over Cuba: what was still queued is dropped at once. */
  function silence() {
    for (const source of playing) {
      source.onended = null;
      source.stop();
    }
    if (playing.size) onSpeaking(false);
    playing = new Set();
    nextAt = 0;
  }

  async function startMic(stream) {
    const context = new AudioContext({ sampleRate: 16000 });
    const url = URL.createObjectURL(new Blob([CAPTURE], { type: 'application/javascript' }));
    await context.audioWorklet.addModule(url);
    URL.revokeObjectURL(url);
    const source = context.createMediaStreamSource(stream);
    const node = new AudioWorkletNode(context, 'cuba-capture');
    node.port.onmessage = (e) => { if (ws?.readyState === WebSocket.OPEN) ws.send(e.data); };
    source.connect(node);
    mic = { context, source, node };
  }

  return {
    get active() { return ws !== null; },

    async start(stream) {
      if (ws) return;
      ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/live`);
      ws.binaryType = 'arraybuffer';
      const socket = ws;
      ws.onmessage = (e) => {
        if (typeof e.data !== 'string') { play(e.data); return; }
        const event = JSON.parse(e.data);
        if (event.type === 'interrupted') silence();
        onEvent(event);
      };
      ws.onclose = () => {
        if (ws !== socket) return;
        this.stop();
        onEvent({ type: 'closed' });
      };
      await startMic(stream);
    },

    sendText(text) {
      if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'text', text }));
    },

    stop() {
      const socket = ws;
      ws = null;
      socket?.close();
      silence();
      if (mic) {
        mic.source.disconnect();
        mic.node.disconnect();
        void mic.context.close();
        mic = null;
      }
    },
  };
}
