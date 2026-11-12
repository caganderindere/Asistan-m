import { createOffice } from './office.js';
import { createLive } from './live.js?v=7';
import { createTerminalView } from './terminal.js?v=7';
import { monitorSilence } from './vad.js?v=7';

const $ = (id) => document.getElementById(id);
const orb = $('orb');
const statusEl = $('status');
const toolLine = $('toolLine');
const notice = $('notice');
const conn = $('conn');
const history = $('history');
const turnTemplate = $('turnTemplate');
const OBJECT_PANES = { printer: 'outputs', clock: 'memory', shelf: 'project', table: 'feed', board: 'tasks' };
const openObject = (id) => { if (OBJECT_PANES[id]) showPane(OBJECT_PANES[id]); };
const office = createOffice($('office'), (id) => { if (id !== 'cagan') selectAgent(id); }, openObject);
const terminal = createTerminalView($('terminalWrap'));
// The terminal's own office: Claude Code at the lead's desk, its subagents at the others.
const termOffice = createOffice($('termOffice'), () => {}, openObject);
const ESC = '\x1b';
// Spoken answers to Claude Code's permission prompt in the terminal.
const YES = new Set(['evet', 'onayla', 'onaylıyorum', 'tamam', 'olur', 'devam']);
const NO = new Set(['hayır', 'reddet', 'iptal', 'yapma']);

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
let recording = null; // the utterance being waited for: { bargeIn, heard, cancel(), and with Silero hear()/finish() }
let sttFailures = 0;
let turnOpen = false; // a request is with Claude and its turn_end has not arrived
let currentTurn = null;
let ttsWarned = false;
let cpuNoticeShown = false;
let team = null; // the latest team snapshot
let termTeam = null; // the latest snapshot of the terminal's Claude and its subagents
let projectList = []; // every project, before the search box filters it
let busyProjects = new Set(); // projects whose team is at work
let openProjects = new Set(); // projects with a running terminal
const crewOf = new Map(); // each project's terminal team, by folder
const decisions = []; // what meetings decided, oldest first
const projectName = (path) => projectList.find((p) => p.path === path)?.name ?? path.split(/[\\/]/).pop();
let project = '';
let selectedAgent = null;
let liveMeeting = null; // the block showing a team meeting while it is going on
let outputCount = null; // reports seen so far; null until the first list arrives
let liveAvailable = false; // the server can carry Cuba's voice over Gemini Live
let away = false; // Cuba decides in the user's place
let hushed = false; // the user talked over Cuba: the rest of this turn is not read out
// Louder than ordinary speech detection, so Cuba's own voice cannot interrupt it.
const BARGE_IN_RMS = 0.03;
let mode = 'office'; // office: speech goes to Cuba on Gemini; terminal: to Claude Code

// Sentences are fetched as soon as they arrive and played strictly in order.
const speechQueue = [];
let playing = null; // the clip now audible
let speaking = false; // the queue is being worked through: a clip is loading or playing
let speechRun = 0; // bumped by stopSpeech so a loop that was awaiting a clip gives up

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
  ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`);
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
      liveAvailable = Boolean(msg.live);
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
    case 'terminal_team': {
      // Every project has its own terminal; the office shows the open project's.
      const here = !msg.project || msg.project === project;
      crewOf.set(msg.project ?? project, msg);
      noteActivity(`terminal:${msg.project}`, msg, here ? '' : projectName(msg.project));
      showHud();
      if (!here) break;
      termTeam = msg;
      termOffice.update(msg);
      $('termQuestion').hidden = !msg.question;
      $('termQuestion').textContent = msg.question;
      break;
    }
    case 'terminals':
      busyProjects = new Set(msg.busy);
      openProjects = new Set(msg.open);
      renderProjects();
      break;
    case 'usage':
      showUsage(msg);
      break;
    case 'chat':
      history.replaceChildren();
      currentTurn = null;
      for (const turn of msg.turns) {
        if (turn.meeting) history.append(meetingBlock(turn.meeting));
        else addTurn(turn.you).reply.textContent = turn.reply;
      }
      showLiveMeeting();
      scrollHistory();
      break;
    case 'meeting':
      // The team has finished talking; what was said stays in the conversation.
      if (!msg.project) { liveMeeting?.remove(); liveMeeting = null; }
      history.append(meetingBlock(msg.lines, '', msg.names, msg.decisions, msg.project && projectName(msg.project)));
      if (msg.decisions?.length) { decisions.push(...msg.decisions); office.setDecisions(decisions); termOffice.setDecisions(decisions); }
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
      if (handsFree && !hushed) enqueueSpeech(msg.text);
      break;
    case 'turn_end':
      turnOpen = false;
      hushed = false;
      // A turn that ends without speech leaves the "dur" listener recording;
      // close it so a fresh listen can start. A recording the user is talking into stays.
      if (!recording?.bargeIn) cancelRecording();
      toolLine.textContent = '';
      if (msg.error && currentTurn) addOp(currentTurn, { name: 'Durduruldu', summary: '' });
      currentTurn = null;
      if (handsFree) continueIfIdle(); else if (state === 'working') setState('idle');
      break;
    case 'away':
      showAway(msg);
      break;
    case 'outputs':
      // A new report: the office printer prints it (not on the first load).
      if (outputCount !== null && msg.items.length > outputCount) { office.print(); termOffice.print(); }
      outputCount = msg.items.length;
      showOutputs(msg.items);
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
  projectList = projects;
  // The terminal office follows the open project.
  const crew = crewOf.get(current);
  if (crew) { termTeam = crew; termOffice.update(crew); }
  const open = projects.find((p) => p.path === current);
  $('workdir').textContent = open?.name ?? current;
  $('workdir').title = current;
  $('projectCount').textContent = projects.length ? `· ${projects.length}` : '';
  if (pane === 'project') showProject();
  renderProjects();
}

function renderProjects() {
  const wanted = $('projectFilter').value.trim().toLocaleLowerCase('tr');
  const shown = projectList.filter(({ path, name }) => !wanted || `${name} ${path}`.toLocaleLowerCase('tr').includes(wanted));
  const current = project;
  $('projectList').replaceChildren(...shown.map(({ path, name }) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'project';
    button.title = path;
    if (path === current) button.setAttribute('aria-current', 'true');
    if (busyProjects.has(path)) button.dataset.state = 'busy';
    else if (openProjects.has(path)) button.dataset.state = 'open';
    button.append(Object.assign(document.createElement('b'), { textContent: name }));
    button.append(Object.assign(document.createElement('small'), { textContent: path }));
    button.addEventListener('click', () => chooseProject(path));
    const li = document.createElement('li');
    li.append(button);
    return li;
  }));
}

$('projectFilter').addEventListener('input', renderProjects);

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

const AGENT_STATE = { idle: 'boşta', working: 'çalışıyor', error: 'hata' };

function showRoster({ agents, review, phase }) {
  $('roster').replaceChildren(...agents.map((agent) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'member';
    button.style.setProperty('--who', office.color(agent.id));
    button.setAttribute('aria-pressed', String(agent.id === selectedAgent));
    let doing = AGENT_STATE[agent.state] ?? agent.state;
    if (phase === 'review' && review.members.includes(agent.id)) doing = review.speaker === agent.id ? 'konuşuyor' : 'toplantıda';
    else if (phase === 'meeting') doing = 'onay bekliyor';
    button.append(Object.assign(document.createElement('b'), { textContent: agent.name }));
    button.append(Object.assign(document.createElement('span'), { textContent: doing }));
    button.addEventListener('click', () => selectAgent(agent.id));
    const li = document.createElement('li');
    li.append(button);
    return li;
  }));
}

function meetingBlock(lines, speaker = '', given = null, decided = [], where = '') {
  const names = given ?? Object.fromEntries((team?.agents ?? []).map((a) => [a.id, a.name]));
  const block = document.createElement('article');
  block.className = 'meeting';
  block.append(Object.assign(document.createElement('h3'), { textContent: where ? `Ekip toplantısı · ${where}` : 'Ekip toplantısı' }));
  for (const line of lines) {
    const p = document.createElement('p');
    p.style.setProperty('--who', office.color(line.who));
    p.append(Object.assign(document.createElement('b'), { textContent: `${names[line.who] ?? line.who}: ` }), line.text);
    block.append(p);
  }
  if (speaker) {
    const p = Object.assign(document.createElement('p'), { className: 'waiting', textContent: `${names[speaker] ?? speaker} konuşuyor…` });
    p.style.setProperty('--who', office.color(speaker));
    block.append(p);
  }
  if (decided.length) {
    const list = Object.assign(document.createElement('ul'), { className: 'decisions' });
    list.append(...decided.map((d) => Object.assign(document.createElement('li'), { textContent: d })));
    block.append(list);
  }
  return block;
}

function showLiveMeeting() {
  const review = team?.review;
  if (!review) { liveMeeting?.remove(); liveMeeting = null; return; }
  const block = meetingBlock(review.lines, review.speaker);
  if (liveMeeting?.isConnected) liveMeeting.replaceWith(block); else history.append(block);
  liveMeeting = block;
  scrollHistory();
}

// ── Activity feed: who is doing and saying what ─────────────

const FEED_LIMIT = 300;
const feedItems = [];
const lastSeen = new Map(); // "source:agent" → the activity last put in the feed
const heardLines = new Map(); // source → meeting lines already in the feed

/** Put what is new in a team snapshot into the feed: started work, tool steps, meeting words. */
function noteActivity(source, snapshot, where = '') {
  const tag = (name) => (where ? `${name} · ${where}` : name);
  for (const agent of snapshot.agents) {
    const key = `${source}:${agent.id}`;
    const activity = agent.state === 'working' ? agent.activity : '';
    if (activity && activity !== lastSeen.get(key)) addFeed(agent.id, tag(agent.name), activity, 'work');
    if (!activity && lastSeen.get(key) && agent.state === 'idle') addFeed(agent.id, tag(agent.name), 'İşini bitirdi.', 'done');
    if (agent.state === 'error' && lastSeen.get(key) !== '!') addFeed(agent.id, tag(agent.name), 'Hata verdi.', 'error');
    lastSeen.set(key, agent.state === 'error' ? '!' : activity);
  }
  const lines = snapshot.review?.lines ?? [];
  const heard = snapshot.review ? heardLines.get(source) ?? 0 : 0;
  const names = { ...Object.fromEntries(snapshot.agents.map((a) => [a.id, a.name])), lider: 'Cuba' };
  for (const line of lines.slice(heard)) addFeed(line.who, tag(names[line.who] ?? line.who), line.text, 'talk');
  heardLines.set(source, lines.length);
}

function addFeed(who, name, text, kind) {
  feedItems.push({ who, name, text, kind, time: new Date() });
  if (feedItems.length > FEED_LIMIT) feedItems.shift();
  const feed = $('feed');
  const nearBottom = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 40;
  feed.append(feedRow(feedItems.at(-1)));
  while (feed.childElementCount > FEED_LIMIT) feed.firstElementChild.remove();
  $('feedEmpty').hidden = true;
  if (nearBottom) feed.scrollTop = feed.scrollHeight;
  if (pane !== 'feed') document.querySelector('.side-tabs [data-pane="feed"]').dataset.fresh = 'true';
}

function feedRow({ who, name, text, kind, time }) {
  const li = document.createElement('li');
  li.className = `feed-item ${kind}`;
  li.style.setProperty('--who', office.color(who));
  const head = document.createElement('p');
  head.append(Object.assign(document.createElement('b'), { textContent: name }),
    Object.assign(document.createElement('time'), { textContent: time.toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit', second: '2-digit' }) }));
  li.append(head, Object.assign(document.createElement('p'), { textContent: text }));
  return li;
}

// ── Header: the open project, the team, the time ────────────

function showHud() {
  const crews = [...crewOf.values()].flatMap((c) => c.agents);
  const working = [...(team?.agents ?? []), ...crews].filter((a) => a.state === 'working').length;
  const hud = $('hudTeam');
  hud.textContent = working ? `${working} ajan çalışıyor` : team?.phase === 'review' ? 'toplantıda' : 'hazır';
  hud.dataset.busy = String(working > 0);
}

const short = (n) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${Math.round(n / 1e3)}K` : String(n));

function showUsage({ claude, gemini }) {
  office.setUsage({ claude, gemini });
  termOffice.setUsage({ claude, gemini });
  const hud = $('hudTokens');
  hud.textContent = `C ${short(claude.input + claude.output)} · G ${short(gemini.input + gemini.output)}`;
  hud.title = `Claude: giriş ${claude.input.toLocaleString('tr-TR')}, çıkış ${claude.output.toLocaleString('tr-TR')}, `
    + `önbellek ${claude.cache.toLocaleString('tr-TR')}\nGemini: giriş ${gemini.input.toLocaleString('tr-TR')}, `
    + `çıkış ${gemini.output.toLocaleString('tr-TR')}`;
}

function tick() {
  const now = new Date();
  $('hudClock').textContent = now.toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' });
  $('hudDate').textContent = now.toLocaleDateString('tr-TR', { day: 'numeric', month: 'short', weekday: 'short' });
}
tick();
setInterval(tick, 10_000);

function showTeam(snapshot) {
  team = snapshot;
  noteActivity('team', snapshot);
  showHud();
  office.update(snapshot);
  showRoster(snapshot);
  showLiveMeeting();
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
  if (team) showRoster(team);
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
  // Only the barge-in recorder may listen while Cuba talks.
  if (recording && !recording.bargeIn) cancelRecording();
  // One player only: a sentence arriving while the previous one is still
  // loading must wait its turn, or the two are heard on top of each other.
  if (!speaking) speakQueue(speechRun);
}

async function speakQueue(run) {
  speaking = true;
  armBargeIn();
  while (run === speechRun && speechQueue.length) {
    setState('speaking');
    let blob;
    try {
      blob = await speechQueue.shift();
    } catch {
      if (!ttsWarned) { ttsWarned = true; showNotice('Ses alınamadı; yanıt yalnızca yazıyla gösteriliyor.'); }
      continue;
    }
    if (run !== speechRun || !handsFree) break;
    await playClip(blob);
  }
  if (run !== speechRun) return; // stopped; whoever stopped it decides what happens next
  speaking = false;
  if (recording?.bargeIn && !recording.heard) cancelRecording();
  continueIfIdle();
}

/** While Cuba talks, listen for the user starting to speak: then Cuba falls silent and listens. */
async function armBargeIn() {
  if (!handsFree || recording) return;
  let result;
  try {
    result = await recordUtterance({
      bargeIn: true,
      minRms: BARGE_IN_RMS,
      onSpeech: () => {
        hushed = turnOpen; // the rest of a reply still coming in is dropped
        stopSpeech();
        setState('listening');
      },
    });
  } catch {
    return;
  }
  await handleUtterance(result);
}

/** Play one clip to its end; resolves early if speech is stopped. */
function playClip(blob) {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    playing = audio;
    const done = () => {
      audio.onended = audio.onerror = null;
      URL.revokeObjectURL(url);
      if (playing === audio) playing = null;
      resolve();
    };
    audio.onended = audio.onerror = done;
    audio.stopNow = () => { audio.pause(); done(); };
    audio.play().catch(done);
  });
}

function stopSpeech() {
  speechRun += 1;
  speechQueue.length = 0;
  speaking = false;
  playing?.stopNow();
  playing = null;
}

// ── Speech input ────────────────────────────────────────────

// A Bluetooth headset's microphone switches it to its hands-free profile, which
// silences its stereo output: with another microphone at hand, use that one.
const HEADSET_MIC = /hands-free|handsfree|bluetooth|buds|airpods|headset/i;
let micStale = false; // a device came or went since the microphone was opened

async function pickMic() {
  const inputs = (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === 'audioinput');
  const usable = inputs.filter((d) => d.label && d.deviceId !== 'default' && d.deviceId !== 'communications');
  // Labels stay empty until microphone permission has been given once.
  if (!usable.some((d) => HEADSET_MIC.test(d.label))) return null;
  return usable.find((d) => !HEADSET_MIC.test(d.label))?.deviceId ?? null;
}

async function ensureMic() {
  const live = micStream?.getAudioTracks().some((t) => t.readyState === 'live');
  if (live && !micStale) return micStream;
  releaseMic();
  micStale = false;
  const deviceId = await pickMic();
  micStream = await navigator.mediaDevices.getUserMedia({
    audio: deviceId ? { deviceId: { exact: deviceId } } : true,
  });
  if (!deviceId && (await pickMic())) {
    // Permission was only just given, so the labels were unknown: choose again.
    releaseMic();
    return ensureMic();
  }
  return micStream;
}

navigator.mediaDevices?.addEventListener('devicechange', () => { micStale = true; });

function releaseMic() {
  speechDetector?.destroy();
  speechDetector = null;
  micStream?.getTracks().forEach((t) => t.stop());
  micStream = null;
}

// ── Speech detection: Silero VAD, with the loudness detector as a fallback ──

const VAD_ASSETS = 'https://cdn.jsdelivr.net/npm/@ricky0123/vad-web@0.0.31/dist/';
const ORT_ASSETS = 'https://cdn.jsdelivr.net/npm/onnxruntime-web@1.22.0/dist/';
const SAMPLE_RATE = 16000;
let speechDetector = null; // one Silero VAD on the open microphone; it hears everything, recordings take turns
let vadBroken = !window.vad; // the library did not load (offline): use the loudness detector

async function ensureDetector() {
  if (speechDetector && !micStale) return speechDetector;
  speechDetector?.destroy();
  speechDetector = null;
  const stream = await ensureMic();
  speechDetector = await window.vad.MicVAD.new({
    baseAssetPath: VAD_ASSETS,
    onnxWASMBasePath: ORT_ASSETS,
    model: 'v5',
    getStream: async () => stream,
    pauseStream: async () => {},
    resumeStream: async () => stream,
    positiveSpeechThreshold: 0.5,
    negativeSpeechThreshold: 0.35,
    redemptionMs: 900, // a pause this long ends the sentence
    minSpeechMs: 250,
    preSpeechPadMs: 400,
    onSpeechStart: () => {
      if (recording && !recording.bargeIn) recording.hear();
    },
    // Talking over Cuba needs real speech, not a click or Cuba's own echo.
    onSpeechRealStart: () => {
      if (recording?.bargeIn) recording.hear();
    },
    onSpeechEnd: (audio) => recording?.finish(wavBlob(audio)),
  });
  speechDetector.start();
  return speechDetector;
}

/** 16-bit mono WAV, the simplest thing Whisper reads. */
function wavBlob(samples) {
  const view = new DataView(new ArrayBuffer(44 + samples.length * 2));
  const text = (at, value) => [...value].forEach((c, i) => view.setUint8(at + i, c.charCodeAt(0)));
  text(0, 'RIFF'); view.setUint32(4, 36 + samples.length * 2, true); text(8, 'WAVE');
  text(12, 'fmt '); view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, SAMPLE_RATE, true); view.setUint32(28, SAMPLE_RATE * 2, true);
  view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  text(36, 'data'); view.setUint32(40, samples.length * 2, true);
  samples.forEach((s, i) => view.setInt16(44 + i * 2, Math.max(-1, Math.min(1, s)) * 0x7FFF, true));
  return new Blob([view], { type: 'audio/wav' });
}

function cancelRecording() {
  if (!recording) return;
  const current = recording;
  recording = null;
  current.cancel();
}

/** Record one utterance; resolves with its transcript, or null if cancelled. */
async function recordUtterance({ bargeIn = false, minRms, onSpeech, quiet = false } = {}) {
  if (!vadBroken) {
    try {
      await ensureDetector();
    } catch (error) {
      if (error?.name === 'NotAllowedError') throw error;
      console.warn('Silero VAD could not start; using the loudness detector', error);
      vadBroken = true;
    }
  }
  if (vadBroken) return recordByLoudness({ bargeIn, minRms, onSpeech, quiet });
  return new Promise((resolve) => {
    const current = {
      bargeIn,
      heard: false,
      hear() { if (!current.heard) { current.heard = true; onSpeech?.(); } },
      async finish(blob) {
        if (recording !== current) return;
        recording = null;
        resolve(await transcribe(blob, quiet));
      },
      cancel() { resolve(null); },
    };
    recording = current;
  });
}

/** The fallback: record until the loudness detector hears speech end. */
async function recordByLoudness({ bargeIn, minRms, onSpeech, quiet = false }) {
  const stream = await ensureMic();
  return new Promise((resolve) => {
    const recorder = new MediaRecorder(stream);
    const chunks = [];
    let discard = false;
    let stopMonitor = () => {};
    const current = {
      bargeIn,
      heard: false,
      cancel() {
        discard = true;
        stopMonitor();
        if (recorder.state === 'recording') recorder.stop();
      },
    };
    recording = current;
    recorder.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
    recorder.onstop = async () => {
      if (discard) { resolve(null); return; }
      if (recording === current) recording = null;
      resolve(await transcribe(new Blob(chunks, { type: recorder.mimeType }), quiet));
    };
    recorder.start();
    stopMonitor = monitorSilence(stream, () => {
      if (recorder.state === 'recording') recorder.stop();
    }, { minRms, onSpeech: () => { current.heard = true; onSpeech?.(); } });
  });
}

async function transcribe(blob, quiet = false) {
  if (quiet) {
    try {
      const r = await fetch('/api/transcribe', { method: 'POST', body: blob });
      return r.ok ? await r.json() : { text: '', meaningful: false };
    } catch {
      return { text: '', meaningful: false };
    }
  }
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
  if (!handsFree || turnOpen || speaking || recording) return;
  setState('listening');
  let result;
  try {
    result = await recordUtterance();
  } catch {
    stopAll(false);
    setState('error', MIC_DENIED);
    return;
  }
  await handleUtterance(result);
}

/** Pass on what the user said: to Claude Code in the terminal, otherwise to Cuba. */
async function handleUtterance(result) {
  if (!result || !handsFree) return;
  if (!result.meaningful) { setState('listening'); listen(); return; }
  turnOpen = true;
  if (mode === 'terminal') {
    const word = normalize(result.text);
    if (YES.has(word)) terminal.key('\r');
    else if (NO.has(word)) terminal.key(ESC);
    else terminal.say(result.text);
  } else {
    send({ type: 'say', text: result.text });
  }
  setState('working');
  listenForStop();
}

/** While Claude works the microphone listens only for "dur". */
async function listenForStop() {
  while (handsFree && turnOpen && !speaking) {
    let result;
    try { result = await recordUtterance(); } catch { return; }
    if (!result) return;
    if (normalize(result.text) === 'dur') {
      if (mode === 'terminal') terminal.key(ESC);
      stopAll(true);
      return;
    }
    if (state === 'transcribing') setState('working');
  }
}

function continueIfIdle() {
  if (!handsFree || speaking) return;
  if (turnOpen) { if (state !== 'working') setState('working'); return; }
  listen();
}

// ── Controls ────────────────────────────────────────────────

// ── Gemini Live: Cuba hears and answers in about half a second ──

const live = createLive({
  onSpeaking: (on) => { if (live.active) setState(on ? 'speaking' : 'listening'); },
  onEvent(event) {
    switch (event.type) {
      case 'ready':
        setState('listening');
        break;
      case 'user': {
        lastHeard = Date.now();
        currentTurn ??= addTurn('');
        let you = currentTurn.node.querySelector('.you');
        if (!you) {
          you = Object.assign(document.createElement('p'), { className: 'you' });
          currentTurn.node.prepend(you);
        }
        you.textContent += event.text;
        scrollHistory();
        break;
      }
      case 'cuba':
        (currentTurn ??= addTurn('')).reply.textContent += event.text;
        scrollHistory();
        break;
      case 'tool':
        toolLine.textContent = `⟳ ${event.name}${event.summary ? ': ' + event.summary : ''}`;
        addOp(currentTurn ??= addTurn(''), event);
        if (event.name === 'terminale_ver') addFeed('lider', 'Cuba', `Ekibe verdi → ${event.summary}`, 'order');
        break;
      case 'turn_complete':
        currentTurn = null;
        toolLine.textContent = '';
        break;
      case 'error':
        showNotice(event.message, 4000);
        break;
      case 'failed':
        // Live cannot be reached: carry on with the classic voice.
        liveAvailable = false;
        stopAll(false);
        showNotice(`${event.message} Klasik sese geçiyorum.`);
        startHandsFree();
        break;
      case 'closed':
        if (handsFree) stopAll(false);
        break;
    }
  },
});

async function startLive() {
  handsFree = true;
  setState('working', 'Cuba bağlanıyor…');
  try {
    await live.start(await ensureMic());
  } catch {
    live.stop();
    stopAll(false);
    setState('error', MIC_DENIED);
  }
}

function startHandsFree() {
  if (waking) cancelRecording(); // stop waiting for the name: the talk starts now
  lastHeard = Date.now();
  if (ws?.readyState !== WebSocket.OPEN) { showNotice('Sunucuya bağlı değil.'); return; }
  if (liveAvailable) { startLive(); return; }
  handsFree = true;
  sttFailures = 0;
  ttsWarned = false;
  if (mode === 'terminal') { turnOpen = false; listen(); return; }
  turnOpen = true; // the server answers "start" with a briefing turn or an immediate turn_end
  setState('working', 'Hazırlanıyor…');
  send({ type: 'start' });
}

function stopAll(notifyServer = true) {
  if (live.active) {
    // Ending a live talk only hangs up; the team carries on.
    live.stop();
    notifyServer = false;
  }
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
  if (mode === 'terminal') terminal.key(ESC);
  stopAll(false);
  send({ type: 'stop' });
}

// ── Wake word: say "Cuba" and it listens ───────────────────
// While waiting, each thing said is written down by the computer's own Whisper (nothing leaves
// the house) and searched for the name; Whisper knows "Cuba" from the vocabulary. This works in
// an iPhone home-screen app too, where the browser's speech recognition does not.

const SLEEP_AFTER_MS = 90_000;
let wakeOn = false;
let waking = false; // the loop waiting for the name is running
let lastHeard = Date.now();

/** Whether *text* says the name: "Cuba", and how it tends to be heard ("Kuba", "Küba", "Cuba'ya"). */
function saysName(text) {
  return normalize(text).split(/\s+/).some((word) => {
    const w = word.replace(/[kq]/g, 'c').replace(/ü/g, 'u');
    if (w.startsWith('cuba')) return true;
    if (w[0] !== 'c' || Math.abs(w.length - 4) > 1) return false; // "Tuba" is someone else
    // One letter off is still the name.
    const row = [0, 1, 2, 3, 4];
    for (let i = 1; i <= w.length; i += 1) {
      let prev = row[0];
      row[0] = i;
      for (let j = 1; j <= 4; j += 1) {
        const here = row[j];
        row[j] = Math.min(row[j] + 1, row[j - 1] + 1, prev + (w[i - 1] === 'cuba'[j - 1] ? 0 : 1));
        prev = here;
      }
    }
    return row[4] <= 1;
  });
}

function wakeLabel(text) { $('wakeToggle').querySelector('span').textContent = text; }

function setWake(on) {
  wakeOn = on && Boolean(navigator.mediaDevices?.getUserMedia);
  try { localStorage.setItem('cuba.wake', wakeOn ? '1' : '0'); } catch { /* private window */ }
  $('wakeToggle').setAttribute('aria-pressed', String(wakeOn));
  if (wakeOn) waitForName();
  else {
    if (waking) cancelRecording();
    if (!handsFree) releaseMic();
    wakeLabel('“Cuba” de');
  }
}

async function waitForName() {
  if (!wakeOn || waking || handsFree || replaced || ws?.readyState !== WebSocket.OPEN) return;
  waking = true;
  wakeLabel('Bekliyor…');
  try {
    await ensureMic();
    while (wakeOn && !handsFree && !replaced) {
      const result = await recordUtterance({ quiet: true });
      if (!result || !wakeOn || handsFree) break;
      if (!result.text.trim()) continue;
      wakeLabel(`Duydum: “${result.text.trim().slice(0, 22)}”`);
      if (saysName(result.text)) {
        lastHeard = Date.now();
        waking = false;
        startHandsFree();
        return;
      }
    }
  } catch (error) {
    if (error?.name === 'NotAllowedError') { setWake(false); showNotice(MIC_DENIED); }
  } finally {
    waking = false;
    if (wakeOn && !handsFree) wakeLabel('Bekliyor…');
  }
}

// A talk nobody has spoken in for a while goes back to sleep, so the line is not kept open for nothing.
setInterval(() => {
  if (wakeOn && handsFree && !speaking && !turnOpen && state !== 'speaking' && Date.now() - lastHeard > SLEEP_AFTER_MS) {
    stopAll(true);
    showNotice('Uyku moduna geçtim. "Cuba" demen yeterli.', 4000);
  }
  if (wakeOn && !handsFree) waitForName();
  else if (wakeOn && handsFree) wakeLabel('Konuşuyoruz');
}, 3000);

$('wakeToggle').addEventListener('click', () => setWake(!wakeOn));
try { if (localStorage.getItem('cuba.wake') === '1') setWake(true); } catch { /* private window */ }

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
  if (live.active) {
    currentTurn = addTurn(text);
    live.sendText(text);
    return;
  }
  cancelRecording();
  turnOpen = true;
  if (mode === 'terminal') terminal.say(text); else send({ type: 'say', text });
  setState('working');
  if (handsFree) listenForStop();
});
function showMode(next) {
  mode = next;
  document.body.dataset.mode = next;
  $('tabOffice').setAttribute('aria-selected', String(next === 'office'));
  $('tabTerminal').setAttribute('aria-selected', String(next === 'terminal'));
  $('officeWrap').hidden = next !== 'office';
  $('terminalMode').hidden = next !== 'terminal';
  $('sayText').placeholder = next === 'terminal' ? "Ya da Claude Code'a yaz" : "Ya da Cuba'ya yaz";
  if (next === 'terminal') showSubTab(subTab);
}

let subTab = 'shell';
function showSubTab(next) {
  subTab = next;
  $('subOffice').setAttribute('aria-selected', String(next === 'office'));
  $('subShell').setAttribute('aria-selected', String(next === 'shell'));
  $('termOfficeWrap').hidden = next !== 'office';
  $('terminalWrap').hidden = next !== 'shell';
  // The terminal connects on first view, so Claude starts even while the office is shown.
  terminal.show();
}
$('subOffice').addEventListener('click', () => showSubTab('office'));
$('subShell').addEventListener('click', () => showSubTab('shell'));
function showAway({ on, turns, max }) {
  away = on;
  document.body.dataset.away = String(on);
  const button = $('awayToggle');
  button.setAttribute('aria-pressed', String(on));
  button.querySelector('span').textContent = on ? `Uzak mod · ${turns}/${max}` : 'Uzaktayım';
}
$('awayToggle').addEventListener('click', () => send({ type: 'away', on: !away }));

function showOutputs(items) {
  $('outputsEmpty').hidden = items.length > 0;
  $('outputs').replaceChildren(...items.toReversed().map((item) => {
    const li = document.createElement('li');
    li.className = 'output';
    li.dataset.away = String(item.away);
    const head = document.createElement('p');
    head.className = 'output-head';
    head.append(Object.assign(document.createElement('time'), { textContent: item.time }));
    const tag = item.away ? (item.done ? 'Cuba bitirdi' : 'Cuba karar verdi') : 'Rapor';
    head.append(Object.assign(document.createElement('span'), { className: 'chip', textContent: tag }));
    li.append(head, Object.assign(document.createElement('p'), { textContent: item.summary }));
    if (item.report) {
      const details = document.createElement('details');
      details.append(Object.assign(document.createElement('summary'), { textContent: 'Tam rapor' }));
      details.append(Object.assign(document.createElement('pre'), { textContent: item.report }));
      li.append(details);
    }
    return li;
  }));
}

async function showProject() {
  const box = $('projectInfo');
  let info;
  try {
    info = await (await fetch('/api/project')).json();
  } catch {
    box.textContent = 'Proje bilgisi alınamadı.';
    return;
  }
  const row = (label, value) => {
    const p = document.createElement('p');
    p.className = 'kv';
    p.append(Object.assign(document.createElement('span'), { textContent: label }),
      Object.assign(document.createElement('b'), { textContent: value }));
    return p;
  };
  const parts = [
    Object.assign(document.createElement('h3'), { textContent: info.name }),
    Object.assign(document.createElement('p'), { className: 'path', textContent: info.path }),
    row('Dal', info.branch || 'git yok'),
    row('Değişen dosya', String(info.changed)),
  ];
  if (info.commits.length) {
    parts.push(Object.assign(document.createElement('h4'), { textContent: 'Son değişiklikler' }));
    const list = document.createElement('ol');
    list.className = 'commits';
    list.append(...info.commits.map(([when, what]) => {
      const li = document.createElement('li');
      li.append(Object.assign(document.createElement('span'), { textContent: what }),
        Object.assign(document.createElement('small'), { textContent: when }));
      return li;
    }));
    parts.push(list);
  }
  parts.push(Object.assign(document.createElement('h4'), { textContent: 'Ekip belgeleri' }));
  if (!info.docs.length) {
    parts.push(Object.assign(document.createElement('p'), {
      className: 'empty', textContent: 'Ekip bir iş yaptığında planı, test raporu ve sonucu burada belge olarak birikir.',
    }));
  }
  for (const doc of info.docs) {
    const details = document.createElement('details');
    details.className = 'paper';
    details.append(Object.assign(document.createElement('summary'), { textContent: doc.name }));
    details.append(Object.assign(document.createElement('pre'), { className: 'readme', textContent: doc.text }));
    parts.push(details);
  }
  if (info.readme) {
    parts.push(Object.assign(document.createElement('h4'), { textContent: 'README' }));
    parts.push(Object.assign(document.createElement('pre'), { className: 'readme', textContent: info.readme }));
  }
  box.replaceChildren(...parts);
}

// ── Memory: what Cuba knows about Çağan, and its diary ─────

let memoryFiles = {};
async function showMemory() {
  let data;
  try {
    data = await (await fetch('/api/memory')).json();
  } catch {
    $('memoryState').textContent = 'Hafıza okunamadı.';
    return;
  }
  memoryFiles = data.files;
  $('memoryText').value = memoryFiles[$('memoryFile').value] ?? '';
  $('memoryState').textContent = 'Cuba öğrendiklerini buraya yazar; yanlışı düzeltebilir, eksiği ekleyebilirsin.';
  $('diary').replaceChildren(...(data.diary.length ? data.diary.map(({ day, text }) => {
    const details = Object.assign(document.createElement('details'), { className: 'paper' });
    details.append(Object.assign(document.createElement('summary'), {
      textContent: new Date(`${day}T12:00`).toLocaleDateString('tr-TR', { weekday: 'long', day: 'numeric', month: 'long' }),
    }));
    details.append(Object.assign(document.createElement('pre'), { className: 'readme', textContent: text }));
    return details;
  }) : [Object.assign(document.createElement('p'), {
    className: 'empty', textContent: 'Her günün sonunda Cuba o günü buraya yazar ve senin hakkında öğrendiklerini deftere ekler.',
  })]));
}
$('memoryFile').addEventListener('change', () => { $('memoryText').value = memoryFiles[$('memoryFile').value] ?? ''; });
$('memorySave').addEventListener('click', async () => {
  const name = $('memoryFile').value;
  const text = $('memoryText').value;
  const response = await fetch('/api/memory', {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, text }),
  }).catch(() => null);
  if (response?.ok) memoryFiles[name] = text;
  $('memoryState').textContent = response?.ok ? 'Kaydedildi. Cuba bir sonraki konuşmada bunu bilir.' : 'Kaydedilemedi.';
});
$('diaryToday').addEventListener('click', async () => {
  $('memoryState').textContent = 'Bugünün günlüğü yazılıyor…';
  const response = await fetch('/api/diary', { method: 'POST' }).catch(() => null);
  const data = await response?.json().catch(() => ({}));
  $('memoryState').textContent = response?.ok
    ? `Yazıldı.${data.learned?.length ? ` Yeni öğrenilen: ${data.learned.join(' · ')}` : ''}`
    : data?.error ?? 'Yazılamadı.';
  if (response?.ok) showMemory();
});

let pane = 'talk';
function showPane(next) {
  pane = next;
  for (const tab of document.querySelectorAll('.side-tabs button')) {
    tab.setAttribute('aria-selected', String(tab.dataset.pane === next));
  }
  for (const section of document.querySelectorAll('.side [data-pane]')) {
    if (section.tagName !== 'BUTTON') section.hidden = section.dataset.pane !== next;
  }
  if (next === 'project') showProject();
  if (next === 'memory') showMemory();
  if (next === 'feed') {
    delete document.querySelector('.side-tabs [data-pane="feed"]').dataset.fresh;
    $('feed').scrollTop = $('feed').scrollHeight;
  }
}
for (const tab of document.querySelectorAll('.side-tabs button')) {
  tab.addEventListener('click', () => showPane(tab.dataset.pane));
}

$('tabOffice').addEventListener('click', () => showMode('office'));
$('tabTerminal').addEventListener('click', () => showMode('terminal'));

$('newSession').addEventListener('click', () => { stopAll(true); send({ type: 'new_session' }); });
document.addEventListener('keydown', (e) => {
  // Ctrl+K: type to Cuba without reaching for the mouse.
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); $('sayText').focus(); }
  // Inside the terminal Esc belongs to Claude Code, which stops its own turn with it.
  if (e.key === 'Escape' && !$('terminalWrap').contains(document.activeElement)) stopEveryone();
});

if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});

setState('idle');
connect();
