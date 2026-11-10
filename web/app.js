import { createOffice } from './office.js';
import { monitorSilence } from './vad.js';

const $ = (id) => document.getElementById(id);
const orb = $('orb');
const statusEl = $('status');
const toolLine = $('toolLine');
const notice = $('notice');
const conn = $('conn');
const history = $('history');
const turnTemplate = $('turnTemplate');
const office = createOffice($('office'), selectAgent);

const TASK_STATUS = {
  proposed: 'onay bekliyor', queued: 'sırada', running: 'çalışıyor',
  done: 'bitti', error: 'hata', stopped: 'durduruldu',
};

const STATUS = {
  idle: 'Başlamak için küreye dokun',
  listening: 'Dinliyorum…',
  transcribing: 'Anlıyorum…',
  working: 'Düşünüyorum…',
  speaking: 'Konuşuyorum…',
};
const MAX_STT_FAILURES = 3;
const MIC_DENIED = 'Mikrofon izni gerekli: adres çubuğundaki kilit simgesinden mikrofona izin verin.';

let ws = null;
let replaced = false;
let state = 'idle';
let handsFree = false;
let micStream = null;
let recording = null; // { recorder, stopMonitor, discard }
let sttFailures = 0;
let turnOpen = false; // a request is with Claude and its turn_end has not arrived
let currentTurn = null;
let ttsWarned = false;
let cpuNoticeShown = false;
let team = null; // the latest team snapshot
let project = '';
let selectedAgent = null;

// Sentences are fetched as soon as they arrive and played strictly in order.
const speechQueue = [];
let playing = null; // HTMLAudioElement

function setState(next, text) {
  state = next;
  orb.dataset.state = next === 'transcribing' ? 'working' : next;
  statusEl.textContent = text ?? STATUS[next] ?? '';
  orb.setAttribute('aria-label', handsFree ? 'Sesli konuşmayı bitir' : 'Sesli konuşmayı başlat');
}

function showNotice(text, ms = 6000) {
  notice.textContent = text;
  notice.hidden = false;
  clearTimeout(showNotice.timer);
  if (ms) showNotice.timer = setTimeout(() => { notice.hidden = true; }, ms);
}

function send(message) {
  if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify(message));
}

// ── Connection ──────────────────────────────────────────────

function connect() {
  ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onopen = () => { conn.dataset.state = 'ready'; conn.textContent = 'Claude bağlı'; };
  ws.onmessage = (e) => handle(JSON.parse(e.data));
  ws.onclose = () => {
    conn.dataset.state = 'error';
    if (replaced) return;
    conn.textContent = 'Bağlantı koptu, yeniden deneniyor…';
    setTimeout(connect, 2000);
  };
}

function handle(msg) {
  switch (msg.type) {
    case 'status':
      if (msg.state === 'error') {
        conn.dataset.state = 'error';
        conn.textContent = 'Claude yok';
        stopAll(false);
        setState('error', msg.detail);
      }
      if (msg.stt_device === 'cpu' && !cpuNoticeShown) {
        cpuNoticeShown = true;
        showNotice('Ses tanıma işlemcide çalışıyor (daha yavaş).');
      }
      break;
    case 'projects':
      showProjects(msg);
      break;
    case 'team':
      showTeam(msg);
      break;
    case 'chat':
      history.replaceChildren();
      currentTurn = null;
      for (const turn of msg.turns) addTurn(turn.you).reply.textContent = turn.reply;
      scrollHistory();
      break;
    case 'notice':
      showNotice(msg.text);
      break;
    case 'lead_turn':
      // A team report reached the lead; it is about to speak unprompted.
      turnOpen = true;
      setState('working', 'Ekipten rapor geldi…');
      break;
    case 'user_text':
      currentTurn = addTurn(msg.text);
      scrollHistory();
      break;
    case 'text':
      (currentTurn ??= addTurn('')).reply.textContent += msg.text;
      scrollHistory();
      break;
    case 'tool':
      toolLine.textContent = `⟳ ${msg.name}${msg.summary ? ': ' + msg.summary : ''}`;
      addOp(currentTurn ??= addTurn(''), msg);
      break;
    case 'sentence':
      if (handsFree) enqueueSpeech(msg.text);
      break;
    case 'turn_end':
      turnOpen = false;
      // A turn that ends without speech leaves the "dur" listener recording;
      // close it so a fresh listen can start.
      cancelRecording();
      toolLine.textContent = '';
      if (msg.error && currentTurn) addOp(currentTurn, { name: 'Durduruldu', summary: '' });
      currentTurn = null;
      if (handsFree) continueIfIdle(); else if (state === 'working') setState('idle');
      break;
    case 'session_reset':
      history.replaceChildren();
      currentTurn = null;
      showNotice('Yeni konuşma başladı.', 3000);
      break;
    case 'replaced':
      replaced = true;
      stopAll(false);
      setState('error', 'Başka bir sekmede açıldı.');
      break;
  }
}

// ── History ─────────────────────────────────────────────────

function addTurn(userText) {
  const node = turnTemplate.content.firstElementChild.cloneNode(true);
  const you = node.querySelector('.you');
  if (userText) you.textContent = userText; else you.remove();
  history.append(node);
  return { node, reply: node.querySelector('.reply'), ops: node.querySelector('.ops'), count: 0 };
}

function addOp(turn, { name, summary }) {
  turn.count += 1;
  turn.ops.hidden = false;
  turn.ops.querySelector('summary').textContent = `▸ ${turn.count} işlem`;
  const li = document.createElement('li');
  li.textContent = summary ? `${name}: ${summary}` : name;
  turn.ops.querySelector('ol').append(li);
}

function scrollHistory() {
  history.scrollTop = history.scrollHeight;
}

// ── Projects ────────────────────────────────────────────────

function showProjects({ current, projects }) {
  if (project && project !== current) {
    // The team moved: whatever the lead was saying in the old project is over.
    turnOpen = false;
    currentTurn = null;
    stopSpeech();
    toolLine.textContent = '';
    selectAgent(null);
    if (handsFree) continueIfIdle(); else setState('idle');
  }
  project = current;
  $('workdir').textContent = current;
  $('projectList').replaceChildren(...projects.map(({ path, name }) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'project';
    button.title = path;
    if (path === current) button.setAttribute('aria-current', 'true');
    button.append(Object.assign(document.createElement('b'), { textContent: name }));
    button.append(Object.assign(document.createElement('small'), { textContent: path }));
    button.addEventListener('click', () => chooseProject(path));
    const li = document.createElement('li');
    li.append(button);
    return li;
  }));
}

function chooseProject(path) {
  if (path === project) return;
  const busy = team?.agents.some((a) => a.state === 'working');
  if (busy && !confirm('Ekip şu an çalışıyor. Proje değiştirirsen süren işler yarıda kalır. Yine de geçilsin mi?')) return;
  send({ type: 'select_project', path });
}

$('addProject').addEventListener('submit', (e) => {
  e.preventDefault();
  const input = $('projectPath');
  if (!input.value.trim()) return;
  send({ type: 'add_project', path: input.value });
  input.value = '';
});

// ── Team ────────────────────────────────────────────────────

function showTeam(snapshot) {
  team = snapshot;
  office.update(snapshot);
  const question = $('question');
  question.hidden = !snapshot.question;
  question.textContent = snapshot.question;
  showTasks(snapshot);
  showAgentCard();
}

function showTasks({ tasks, agents }) {
  const names = Object.fromEntries(agents.map((a) => [a.id, a.name]));
  $('tasksEmpty').hidden = tasks.length > 0;
  $('tasks').replaceChildren(...tasks.toReversed().map((task) => {
    const li = document.createElement('li');
    li.className = 'task-item';
    li.style.setProperty('--who', office.color(task.to));
    const head = document.createElement('p');
    head.className = 'task-head';
    head.append(Object.assign(document.createElement('b'), { textContent: `#${task.id} ${names[task.to] ?? task.to}` }));
    const chip = Object.assign(document.createElement('span'), { className: 'chip', textContent: TASK_STATUS[task.status] ?? task.status });
    chip.dataset.status = task.status;
    head.append(chip);
    li.append(head, Object.assign(document.createElement('p'), { textContent: task.text }));
    if (task.result) {
      const details = document.createElement('details');
      details.append(Object.assign(document.createElement('summary'), { textContent: 'Rapor' }));
      details.append(Object.assign(document.createElement('p'), { textContent: task.result }));
      li.append(details);
    }
    return li;
  }));
}

function selectAgent(id) {
  selectedAgent = id === selectedAgent ? null : id;
  office.select(selectedAgent);
  showAgentCard();
}

function showAgentCard() {
  const card = $('agentCard');
  const agent = team?.agents.find((a) => a.id === selectedAgent);
  card.hidden = !agent;
  if (!agent) return;
  card.style.setProperty('--who', office.color(agent.id));
  $('agentName').textContent = agent.name;
  $('agentMeta').textContent = `${agent.department}, ${agent.model}`;
  $('agentWhere').textContent = office.where(agent);
  const task = team.tasks.find((t) => t.id === agent.task);
  $('agentTask').textContent = task ? `Görev #${task.id}: ${task.text}` : agent.duty;
  $('agentLog').replaceChildren(...agent.log.map((line) => Object.assign(document.createElement('li'), { textContent: line })));
}

$('agentClose').addEventListener('click', () => selectAgent(null));

// ── Speech output ───────────────────────────────────────────

function enqueueSpeech(text) {
  const audio = fetch('/api/tts', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  }).then((r) => (r.ok ? r.blob() : Promise.reject(new Error('tts'))));
  audio.catch(() => {}); // handled when its turn comes
  speechQueue.push(audio);
  // The microphone stays closed while the assistant talks so it cannot hear itself.
  cancelRecording();
  if (!playing) playNext();
}

async function playNext() {
  const next = speechQueue.shift();
  if (!next) {
    playing = null;
    continueIfIdle();
    return;
  }
  setState('speaking');
  let blob;
  try {
    blob = await next;
  } catch {
    if (!ttsWarned) { ttsWarned = true; showNotice('Ses alınamadı; yanıt yalnızca yazıyla gösteriliyor.'); }
    playNext();
    return;
  }
  if (!handsFree) return;
  const url = URL.createObjectURL(blob);
  const audio = new Audio(url);
  playing = audio;
  const done = () => { URL.revokeObjectURL(url); if (playing === audio) playNext(); };
  audio.onended = done;
  audio.onerror = done;
  audio.play().catch(done);
}

function stopSpeech() {
  speechQueue.length = 0;
  if (playing) { playing.onended = null; playing.onerror = null; playing.pause(); }
  playing = null;
}

// ── Speech input ────────────────────────────────────────────

async function ensureMic() {
  if (micStream) return micStream;
  micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  return micStream;
}

function releaseMic() {
  micStream?.getTracks().forEach((t) => t.stop());
  micStream = null;
}

function cancelRecording() {
  if (!recording) return;
  recording.discard = true;
  recording.stopMonitor();
  if (recording.recorder.state === 'recording') recording.recorder.stop();
  recording = null;
}

/** Record one utterance; resolves with its transcript, or null if cancelled. */
async function recordUtterance() {
  const stream = await ensureMic();
  return new Promise((resolve) => {
    const recorder = new MediaRecorder(stream);
    const chunks = [];
    const current = { recorder, discard: false, stopMonitor: () => {} };
    recording = current;
    recorder.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
    recorder.onstop = async () => {
      if (current.discard) { resolve(null); return; }
      if (recording === current) recording = null;
      resolve(await transcribe(new Blob(chunks, { type: recorder.mimeType })));
    };
    recorder.start();
    current.stopMonitor = monitorSilence(stream, () => {
      if (recorder.state === 'recording') recorder.stop();
    });
  });
}

async function transcribe(blob) {
  if (state === 'listening') setState('transcribing');
  try {
    const r = await fetch('/api/transcribe', { method: 'POST', body: blob });
    if (!r.ok) throw new Error('stt');
    sttFailures = 0;
    return await r.json();
  } catch {
    sttFailures += 1;
    showNotice('Ses tanınamadı, tekrar dinliyorum.');
    if (sttFailures >= MAX_STT_FAILURES) {
      stopAll(true);
      setState('error', 'Ses tanıma üst üste başarısız oldu; küreye dokunup tekrar deneyin.');
    }
    return { text: '', meaningful: false };
  }
}

const normalize = (t) => t.toLocaleLowerCase('tr').replace(/[^\p{L}\s]/gu, '').trim();

async function listen() {
  if (!handsFree || turnOpen || playing || recording) return;
  setState('listening');
  let result;
  try {
    result = await recordUtterance();
  } catch {
    stopAll(false);
    setState('error', MIC_DENIED);
    return;
  }
  if (!result || !handsFree) return;
  if (!result.meaningful) { setState('listening'); listen(); return; }
  turnOpen = true;
  send({ type: 'say', text: result.text });
  setState('working');
  listenForStop();
}

/** While Claude works the microphone listens only for "dur". */
async function listenForStop() {
  while (handsFree && turnOpen && !playing && !speechQueue.length) {
    let result;
    try { result = await recordUtterance(); } catch { return; }
    if (!result) return;
    if (normalize(result.text) === 'dur') { stopAll(true); return; }
    if (state === 'transcribing') setState('working');
  }
}

function continueIfIdle() {
  if (!handsFree || playing || speechQueue.length) return;
  if (turnOpen) { if (state !== 'working') setState('working'); return; }
  listen();
}

// ── Controls ────────────────────────────────────────────────

function startHandsFree() {
  if (ws?.readyState !== WebSocket.OPEN) { showNotice('Sunucuya bağlı değil.'); return; }
  handsFree = true;
  sttFailures = 0;
  ttsWarned = false;
  turnOpen = true; // the server answers "start" with a briefing turn or an immediate turn_end
  setState('working', 'Hazırlanıyor…');
  send({ type: 'start' });
}

function stopAll(notifyServer = true) {
  const wasActive = handsFree || turnOpen;
  handsFree = false;
  turnOpen = false;
  cancelRecording();
  releaseMic();
  stopSpeech();
  toolLine.textContent = '';
  if (notifyServer && wasActive) send({ type: 'stop' });
  setState('idle');
}

/** Stop the lead and the whole team, even when the lead itself is silent. */
function stopEveryone() {
  stopAll(false);
  send({ type: 'stop' });
}

orb.addEventListener('click', () => {
  if (replaced) return;
  if (handsFree) stopAll(true); else startHandsFree();
});
$('stop').addEventListener('click', stopEveryone);
$('sayForm').addEventListener('submit', (e) => {
  e.preventDefault();
  const input = $('sayText');
  const text = input.value.trim();
  if (!text) return;
  if (ws?.readyState !== WebSocket.OPEN) { showNotice('Sunucuya bağlı değil.'); return; }
  input.value = '';
  cancelRecording();
  turnOpen = true;
  send({ type: 'say', text });
  setState('working');
  if (handsFree) listenForStop();
});
$('newSession').addEventListener('click', () => { stopAll(true); send({ type: 'new_session' }); });
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') stopEveryone(); });

setState('idle');
connect();
