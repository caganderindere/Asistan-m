# Claude Ses Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Yerel çalışan, Claude Code'a bağlı, eller serbest Türkçe sesli tarayıcı arayüzü (`D:\ClaudeSes`).

**Architecture:** FastAPI sunucusu (`127.0.0.1:8765`) tek bir uzun ömürlü `claude -p` sürecini stream-json ile sürer; olayları WebSocket üzerinden tarayıcıya aktarır. Tarayıcı mikrofonu ve sessizlik algılamayı yapar, sesi `POST /api/transcribe` ile Whisper'a, cümleleri `POST /api/tts` ile Edge sesine gönderir.

**Tech Stack:** Python 3.13 (uv), FastAPI, uvicorn, faster-whisper, edge-tts, soundfile, numpy, pytest, pytest-asyncio, httpx; tarayıcıda düz HTML/CSS/JS (derleme yok); uçtan uca test için Python Playwright.

**Spec:** `docs/superpowers/specs/2026-11-10-claude-ses-design.md`

## Global Constraints

- Her şey `D:\ClaudeSes` altında; `UV_CACHE_DIR=D:\ClaudeSes\.uv-cache`, `PLAYWRIGHT_BROWSERS_PATH=D:\ClaudeSes\.pw-browsers`.
- Sunucu yalnızca `127.0.0.1`, port `8765`.
- Claude komutu: `claude -p --input-format stream-json --output-format stream-json --verbose --include-partial-messages --permission-mode bypassPermissions --append-system-prompt <VOICE_PROMPT> [--resume <oturum>]`, çalışma klasörü `D:\`.
- `VOICE_PROMPT` = `"Türkçe, kısa ve konuşma diliyle yanıt ver; kod, yol ve uzun çıktıları yazıya bırak, sesle özetle."`
- Claude alt sürecinin ortamından `CLAUDECODE` ve `CLAUDE_CODE_ENTRYPOINT` kaldırılır (bu oturumun içinden başlatıldığında iç içe oturum reddini önler). Alt süreç G/Ç'si UTF-8.
- Ses: `tr-TR-AhmetNeural`; Whisper modeli `base`, `device="cpu"`, `compute_type="int8"`, `language="tr"`.
- Sessizlik algılama: 400 ms kalibrasyon, eşik `max(0.015, gürültü*2.5)`, konuşmadan sonra 1500 ms sessizlik, en fazla 30000 ms.
- Arayüz metinleri Türkçe. Python testleri: `.venv\Scripts\python -m pytest`.
- Her commit mesajı şu satırla biter: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`

## Review Focus

1. Claude yalnızca araç kullanıp hiç metin üretmeden turu bitirir → `turn_end` yine gönderilir, mikrofon yeniden açılır (Task 5 testi).
2. Whisper sessizlik/gürültüde uydurma metin döndürür ("Altyazı M.K.", "İzlediğiniz için teşekkürler") → bu metinler ve 2 karakterden kısa metinler Claude'a gönderilmez (Task 4 testi).
3. Dur, uzun süren bir komut sırasında basılır → kesme isteği gönderilir; 3 sn içinde `result` gelmezse süreç öldürülüp aynı oturumla yeniden başlatılır (Task 3 testi).
4. Arayüz iki sekmede açılır → yalnızca son bağlanan sekme etkin; eskisine `{"type":"replaced"}` gider (Task 5 testi).
5. Türkçe karakterli metin ("ğüşıöç İĞÜŞ") Claude'a giderken ve dönerken bozulmaz (Task 3 testi).

---

### Task 1: Proje iskeleti, ayarlar, oturum kaydı

**Files:**
- Create: `pyproject.toml`, `server/__init__.py`, `server/config.py`, `server/session_store.py`, `tests/__init__.py`, `tests/test_config.py`, `tests/test_session_store.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class Config: port: int = 8765; workdir: str = "D:\\"; voice: str = "tr-TR-AhmetNeural"; whisper_model: str = "base"`
  - `load_config(path: Path) -> Config` — dosya yoksa varsayılanlar; bilinmeyen anahtarlar yok sayılır.
  - `class SessionStore: __init__(self, path: Path); load(self) -> str | None; save(self, session_id: str) -> None; clear(self) -> None`
  - Proje kökü sabiti: `server/config.py` içinde `ROOT = Path(__file__).resolve().parent.parent`

- [ ] **Step 1: Ortamı kur**

Run (PowerShell, `D:\ClaudeSes`): `$env:UV_CACHE_DIR='D:\ClaudeSes\.uv-cache'; uv venv --python 3.13 .venv; uv pip install --python .venv\Scripts\python.exe fastapi uvicorn faster-whisper edge-tts soundfile numpy pytest pytest-asyncio httpx playwright`
Expected: kurulum hatasız biter. `pyproject.toml` yalnızca proje adı, `requires-python = ">=3.13"`, bu bağımlılıklar ve `[tool.pytest.ini_options] asyncio_mode = "auto"` içerir.

- [ ] **Step 2: Testleri yaz**

```python
# tests/test_config.py
def test_defaults_when_missing(tmp_path):
    c = load_config(tmp_path / "config.json")
    assert (c.port, c.workdir, c.voice, c.whisper_model) == (8765, "D:\\", "tr-TR-AhmetNeural", "base")

def test_overrides_and_ignores_unknown(tmp_path):
    p = tmp_path / "config.json"
    p.write_text('{"voice": "tr-TR-EmelNeural", "junk": 1}', encoding="utf-8")
    c = load_config(p)
    assert c.voice == "tr-TR-EmelNeural" and c.port == 8765

# tests/test_session_store.py
def test_roundtrip_and_clear(tmp_path):
    s = SessionStore(tmp_path / "data" / "session.json")
    assert s.load() is None
    s.save("abc-123"); assert s.load() == "abc-123"
    s.clear(); assert s.load() is None

def test_corrupt_file_is_none(tmp_path):
    p = tmp_path / "session.json"; p.write_text("{bozuk", encoding="utf-8")
    assert SessionStore(p).load() is None
```

- [ ] **Step 3: Çalıştır, FAIL gör** — `.venv\Scripts\python -m pytest tests -v` → ImportError.
- [ ] **Step 4: `server/config.py` ve `server/session_store.py` yaz** — `save` üst klasörü oluşturur.
- [ ] **Step 5: Çalıştır, PASS gör** — 4 test geçer.
- [ ] **Step 6: Commit** — `git add pyproject.toml server tests && git commit -m "feat: config and session store"`

---

### Task 2: Claude olay ayrıştırıcı (gerçek kayıtlarla)

**Files:**
- Create: `tools/capture_claude.py`, `tests/fixtures/claude_text.jsonl`, `tests/fixtures/claude_tool.jsonl`, `tests/fixtures/claude_interrupt.jsonl`, `server/claude_events.py`, `tests/test_claude_events.py`

**Interfaces:**
- Produces (`server/claude_events.py`):
  - `@dataclass class SessionInit: session_id: str`
  - `@dataclass class TextDelta: text: str`
  - `@dataclass class ToolUse: name: str; summary: str` — `summary` ≤ 80 karakter: Bash için `command`, Read/Edit/Write için `file_path`, Glob/Grep için `pattern`, diğerlerinde boş.
  - `@dataclass class TurnResult: session_id: str; is_error: bool`
  - `Event = SessionInit | TextDelta | ToolUse | TurnResult`
  - `parse_line(line: str) -> list[Event]` — tanınmayan/bozuk satır → `[]`.
  - `user_message(text: str) -> str` — stdin'e yazılacak tek satır JSON (sonunda `\n`).
  - `interrupt_request(request_id: str) -> str` — kesme kontrol isteği satırı.

- [ ] **Step 1: Gerçek akışı kaydet**

`tools/capture_claude.py <çıktı.jsonl> <mesaj> [--interrupt-after-tool]`: Global Constraints'teki komutu (`--resume` olmadan, çalışma klasörü `D:\ClaudeSes`) başlatır, `user_message(mesaj)` yazar, stdout satırlarını dosyaya kaydeder, `result` satırında durur. `--interrupt-after-tool` ilk araç kullanımında `interrupt_request("int-1")` yazar.
Run: üç kayıt — `"Merhaba de, başka bir şey yapma."` → `claude_text.jsonl`; `"Bu klasördeki dosyaları listele ve kaç tane olduğunu söyle."` → `claude_tool.jsonl`; `"PowerShell'de 20 saniye bekle sonra bitti de."` `--interrupt-after-tool` → `claude_interrupt.jsonl`.
Expected: her dosya `system/init`, metin parçaları ve `result` satırı içerir; kesme kaydında `result` 3 sn içinde gelir mi not edilir (gelmiyorsa Task 3'teki öldür-yeniden başlat yolu tek yol olur). Satırların gerçek alan adları `parse_line`'ın temelidir; bu plandaki alan adlarıyla çelişirse kayıt kazanır.

- [ ] **Step 2: Testleri yaz** — kayıtlara karşı:

```python
def events(name): return [e for l in open(FIX/name, encoding="utf-8") for e in parse_line(l)]

def test_text_fixture():
    ev = events("claude_text.jsonl")
    assert isinstance(ev[0], SessionInit) and ev[0].session_id
    assert "Merhaba" in "".join(e.text for e in ev if isinstance(e, TextDelta))
    assert isinstance(ev[-1], TurnResult) and not ev[-1].is_error

def test_tool_fixture_has_summary():
    tools = [e for e in events("claude_tool.jsonl") if isinstance(e, ToolUse)]
    assert tools and all(len(t.summary) <= 80 for t in tools)

def test_garbage_lines():
    assert parse_line("") == [] and parse_line("{bozuk") == [] and parse_line('{"type":"x"}') == []

def test_user_message_roundtrip_turkish():
    line = user_message("ğüşıöç İĞÜŞ")
    assert line.endswith("\n") and json.loads(line)["message"]["content"] == "ğüşıöç İĞÜŞ"
```

- [ ] **Step 3: FAIL gör → Step 4: `parse_line`, `user_message`, `interrupt_request` yaz → Step 5: PASS gör**
- [ ] **Step 6: Commit** — `git commit -m "feat: parse claude stream-json events"`

---

### Task 3: Claude köprüsü

**Files:**
- Create: `server/claude_bridge.py`, `tests/fake_claude.py`, `tests/test_claude_bridge.py`

**Interfaces:**
- Consumes: Task 2 olayları ve `user_message`, `interrupt_request`; Task 1 `SessionStore`.
- Produces:
  - `build_command(claude_exe: str, session_id: str | None) -> list[str]` (Global Constraints'teki bayraklar).
  - `child_env(base: Mapping[str, str]) -> dict[str, str]` — `CLAUDECODE`, `CLAUDE_CODE_ENTRYPOINT` çıkarılır, `PYTHONIOENCODING=utf-8`.
  - `class ClaudeBridge:`
    - `__init__(self, workdir: str, store: SessionStore, command_factory: Callable[[str | None], list[str]])`
    - `async start(self) -> None` — kayıtlı oturumla başlatır.
    - `async send(self, text: str) -> None`
    - `events(self) -> AsyncIterator[Event]` — süreç kapanırsa `start()` ile yeniden başlatıp sürer.
    - `async interrupt(self, timeout: float = 3.0) -> None` — kesme isteği; `timeout` içinde `TurnResult` yoksa süreci öldürür, aynı oturumla yeniden başlatır ve bir `TurnResult(session_id, is_error=True)` üretir.
    - `async new_session(self) -> None` — `store.clear()`, süreci yeniden başlatır.
    - `async close(self) -> None`
  - `SessionInit`/`TurnResult` geldikçe `store.save(session_id)`.

- [ ] **Step 1: Sahte claude yaz** — `tests/fake_claude.py`: stdin'den satır okur; mesaj içeriği `"yavaş"` ise kesme isteği gelene kadar bekler (`--ignore-interrupt` bayrağıyla hiç yanıt vermez); `"öl"` ise `exit(1)`; diğerlerinde `system/init`, gelen metni yankılayan bir metin parçası ve `result` yazar. Satır biçimleri Task 2 kayıtlarından kopyalanır.
- [ ] **Step 2: Testleri yaz**

```python
async def test_echo_turkish(bridge):          # fake_claude ile
    await bridge.send("ğüşıöç İĞÜŞ")
    ev = await collect_until_result(bridge)
    assert "ğüşıöç İĞÜŞ" in text_of(ev) and store.load()

async def test_crash_restarts_with_same_session(bridge):
    await bridge.send("merhaba"); await collect_until_result(bridge); sid = store.load()
    await bridge.send("öl"); await bridge.send("tekrar")
    ev = await collect_until_result(bridge)
    assert "tekrar" in text_of(ev) and sid in last_command_args()   # --resume sid

async def test_interrupt_answered(bridge):
    await bridge.send("yavaş"); await asyncio.sleep(0.2); await bridge.interrupt(timeout=3)
    assert isinstance((await collect_until_result(bridge))[-1], TurnResult)

async def test_interrupt_ignored_kills_and_resumes(bridge_ignoring):
    await bridge_ignoring.send("yavaş"); t = time.monotonic()
    await bridge_ignoring.interrupt(timeout=1)
    r = (await collect_until_result(bridge_ignoring))[-1]
    assert r.is_error and time.monotonic() - t < 3

def test_child_env_strips_nesting():
    assert "CLAUDECODE" not in child_env({"CLAUDECODE": "1", "PATH": "x"})
```

- [ ] **Step 3: FAIL → Step 4: `ClaudeBridge` (asyncio subprocess, stdout okuyucu görev + `asyncio.Queue`) → Step 5: PASS**
- [ ] **Step 6: Commit** — `git commit -m "feat: claude process bridge with restart and interrupt"`

---

### Task 4: Cümle bölme, konuşma tanıma, seslendirme

**Files:**
- Create: `server/sentences.py`, `server/stt.py`, `server/tts.py`, `tests/test_sentences.py`, `tests/test_stt_filter.py`, `tests/test_tts.py`

**Interfaces:**
- Produces:
  - `class SentenceSplitter: feed(self, text: str) -> list[str]; flush(self) -> list[str]` — tam cümleleri (`.`, `!`, `?`, `…`, satır sonu) döndürür; ` ``` ` kod bloğu içindeki metni ve `speakable` ile boş kalan cümleleri atar; "3.5", "v1.2" gibi sayı içi noktada bölmez.
  - `speakable(sentence: str) -> str` — satır içi `` `kod` ``, Windows/Unix yolları ve URL'ler çıkarılır; markdown işaretleri (`*`, `#`, `-` madde başı) silinir.
  - `class Transcriber: __init__(self, model: str); transcribe(self, audio: bytes) -> str` — faster-whisper, `cpu/int8`, `language="tr"`, `vad_filter=True`; giriş WebM/WAV baytları (PyAV ile çözülür).
  - `is_meaningful(text: str) -> bool` — `len(text.strip()) >= 2` ve uydurma listesinde değil: `"altyazı m.k."`, `"izlediğiniz için teşekkürler"`, `"abone olmayı unutmayın"` (küçük harf, noktalama yok sayılarak karşılaştırılır).
  - `async synthesize(text: str, voice: str) -> bytes` — edge-tts MP3 → soundfile ile WAV baytları.

- [ ] **Step 1: Testleri yaz**

```python
def test_splits_streamed_chunks():
    s = SentenceSplitter()
    assert s.feed("Merhaba. Üç dosya") == ["Merhaba."]
    assert s.feed(" buldum! Sürüm 3.5 hazır") == ["Üç dosya buldum!"]
    assert s.flush() == ["Sürüm 3.5 hazır"]

def test_skips_code_block():
    s = SentenceSplitter()
    out = s.feed("Şunu çalıştır:\n```\nrm -rf x.\n```\nTamam.") + s.flush()
    assert out == ["Şunu çalıştır:", "Tamam."]

def test_speakable_strips_paths_and_code():
    assert speakable("Dosya `a.py` içinde, D:\\yazılım\\x.txt yolunda.") == "Dosya içinde, yolunda."

@pytest.mark.parametrize("t,ok", [("", False), ("a", False), ("Altyazı M.K.", False),
    ("İzlediğiniz için teşekkürler.", False), ("dosyaları listele", True)])
def test_is_meaningful(t, ok): assert is_meaningful(t) is ok

async def test_synthesize_returns_wav(monkeypatch):   # edge_tts.Communicate sahte MP3 akışı döndürür
    wav = await synthesize("Merhaba", "tr-TR-AhmetNeural")
    assert wav[:4] == b"RIFF"
```
`test_synthesize_returns_wav` için gerçek MP3 baytları `tests/fixtures/merhaba.mp3` dosyasından gelir (bir kez gerçek edge-tts ile üretilip kaydedilir). Gerçek ağla bir test daha: `@pytest.mark.network` — varsayılan çalıştırmada atlanır (`-m "not network"` `pyproject` `addopts`).

- [ ] **Step 2: FAIL → Step 3: dört birimi yaz → Step 4: PASS** (`-m network` ile ağ testi de bir kez geçer)
- [ ] **Step 5: Commit** — `git commit -m "feat: sentence splitting, transcription filter, tts"`

---

### Task 5: Sunucu (HTTP + WebSocket)

**Files:**
- Create: `server/app.py`, `tests/test_app.py`

**Interfaces:**
- Consumes: Task 1–4.
- Produces: `create_app(config: Config, bridge: ClaudeBridge, transcriber, synth: Callable[[str, str], Awaitable[bytes]]) -> FastAPI` ve `main()` (uvicorn, `127.0.0.1:config.port`).
  - `GET /` → `web/index.html`; `GET /static/*` → `web/`.
  - `POST /api/transcribe` (gövde: ses baytları) → `{"text": str, "meaningful": bool}`.
  - `POST /api/tts` `{"text": str}` → `audio/wav`; hata → 502 `{"error": "tts"}`.
  - `WS /ws` istemci → sunucu: `{"type":"say","text"}`, `{"type":"stop"}`, `{"type":"new_session"}`.
  - `WS /ws` sunucu → istemci: `{"type":"status","state":"ready|starting|error","detail":str}`, `{"type":"user_text","text"}`, `{"type":"tool","name","summary"}`, `{"type":"text","text"}` (ham parça, ekranda gösterim için), `{"type":"sentence","text"}` (seslendirilecek), `{"type":"turn_end","error":bool}`, `{"type":"replaced"}`.
  - Tek etkin istemci: yeni bağlantı gelince eskisine `replaced` gönderilip kapatılır.
  - `claude` bulunamazsa `status` `error`, `detail`: `"Claude Code bulunamadı ya da giriş yapılmamış. Bir terminalde 'claude' yazıp giriş yapın."`

- [ ] **Step 1: Testleri yaz** (FastAPI `TestClient`, sahte köprü — kuyruğa elle olay basılır)

```python
def test_turn_streams_sentences_and_end(client, fake_bridge):
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "say", "text": "selam"})
        fake_bridge.push(TextDelta("Merhaba. Nasılsın?"), TurnResult("s1", False))
        msgs = read_until(ws, "turn_end")
    assert [m["text"] for m in msgs if m["type"] == "sentence"] == ["Merhaba.", "Nasılsın?"]
    assert fake_bridge.sent == ["selam"]

def test_tool_only_turn_still_ends(client, fake_bridge):
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "say", "text": "listele"})
        fake_bridge.push(ToolUse("Bash", "dir"), TurnResult("s1", False))
        msgs = read_until(ws, "turn_end")
    assert any(m["type"] == "tool" for m in msgs) and msgs[-1] == {"type": "turn_end", "error": False}

def test_second_tab_replaces_first(client):
    with client.websocket_connect("/ws") as a:
        with client.websocket_connect("/ws") as b:
            assert read_until(a, "replaced")[-1]["type"] == "replaced"

def test_stop_calls_interrupt(client, fake_bridge): ...   # {"type":"stop"} → fake_bridge.interrupted is True
def test_transcribe_filters(client, fake_transcriber):     # "Altyazı M.K." → meaningful False
def test_tts_failure_is_502(client, failing_synth):        # → 502
```

- [ ] **Step 2: FAIL → Step 3: `create_app` yaz** — köprü olaylarını okuyan tek arka plan görevi, `SentenceSplitter` tur başına sıfırlanır, `TurnResult`'ta `flush()` sonra `turn_end` → **Step 4: PASS**
- [ ] **Step 5: Commit** — `git commit -m "feat: http and websocket server"`

---

### Task 6: Tarayıcı arayüzü (Yerleşim A)

**Files:**
- Create: `web/index.html`, `web/style.css`, `web/app.js`, `web/vad.js`

**Interfaces:**
- Consumes: Task 5 HTTP/WS sözleşmesi.
- Produces: `vad.js` → `export function monitorSilence(stream: MediaStream, onSilence: () => void): () => void` (Global Constraints'teki değerler; `setInterval` 100 ms, `requestAnimationFrame` değil).

Davranış (spec "Konuşma akışı", "Arayüz", "Durdurma"):
- Durum makinesi `idle | listening | transcribing | working | speaking | error`; küre sınıfı duruma göre (renkler spec tablosundaki gibi), altında durum yazısı ve canlı işlem satırı (`⟳ <name>: <summary>`).
- Küreye tıklama: eller serbest aç/kapa. `listening` → sessizlikte kayıt durur → `/api/transcribe` → `meaningful` değilse yeniden dinle; değilse `say`.
- `working` sırasında mikrofon açık; tanınan metin küçük harfe çevrilip noktalama atıldığında `"dur"` ise `stop` gönderilir.
- `sentence` mesajları kuyruğa girer; sırayla `/api/tts` → `Audio` ile çalınır (`speaking`, mikrofon kapalı). TTS hatasında cümle atlanır, bir kez uyarı gösterilir.
- `turn_end` ve kuyruk boşalınca → `listening`. Whisper 3 kez üst üste hata verirse eller serbest kapanır.
- Mikrofon izni reddedilirse eller serbest kapanır, küre `error`, yazı: "Mikrofon izni gerekli: adres çubuğundaki kilit simgesinden mikrofona izin verin."
- `Esc` / Dur düğmesi: ses durur, kuyruk boşalır, kayıt iptal, `stop` gönderilir, eller serbest kapanır.
- WS koparsa 2 sn aralıkla yeniden bağlanır; `replaced` gelince "Başka bir sekmede açıldı" gösterilir ve yeniden bağlanmaz.
- Üst satır: `D:\`, bağlantı noktası, **Yeni konuşma**. Alt: son konuşma, `▸ N işlem` açılır listesi, kaydırılabilir geçmiş.

- [ ] **Step 1: Dosyaları yaz**
- [ ] **Step 2: Elle tarama** — sunucu çalışırken `http://127.0.0.1:8765` açılır; tarayıcı konsolunda hata yok; küre `idle` (gri) görünür; sayfa 360 px genişlikte yatay kaydırma yapmaz.
- [ ] **Step 3: Commit** — `git commit -m "feat: voice orb web interface"`

---

### Task 7: Başlatıcı, kısayol, uçtan uca test

**Files:**
- Create: `start.cmd`, `tools/make_shortcut.ps1`, `tests/e2e/test_voice_turn.py`, `README.md`

**Interfaces:**
- Consumes: Task 5 `main()`, Task 6 arayüzü.

- [ ] **Step 1: `start.cmd`** — `cd /d D:\ClaudeSes`, `.venv\Scripts\python -m server.app` başlatır; sunucu `GET /` yanıt verince tarayıcıyı `http://127.0.0.1:8765` ile açar (sunucu içinde `webbrowser.open`, port dinlemeye başladıktan sonra). Pencere kapanınca sunucu ve `claude` alt süreci kapanır (`ClaudeBridge.close` uygulama kapanışında).
- [ ] **Step 2: `tools/make_shortcut.ps1`** — masaüstüne `Claude Ses.lnk` → `start.cmd`, çalışma klasörü `D:\ClaudeSes`. Çalıştır, kısayolun oluştuğunu doğrula.
- [ ] **Step 3: Uçtan uca testi yaz** — Playwright Chromium; `addInitScript` ile `getUserMedia` yerine, `/api/tts` ile üretilmiş `"Merhaba, bana sadece tamam de."` sesini çalan bir `MediaStreamDestination` akışı verilir (Jarvis testindeki yöntem). Gerçek sunucu ve gerçek `claude` ile:
  - küreye tıkla → durumlar sırasıyla `listening → transcribing → working → speaking → listening` görülür (en fazla 120 sn);
  - ekranda kullanıcı metni "Merhaba" içerir, Claude yanıtı boş değildir, en az bir `Audio.play` çağrılır;
  - ikinci turda Dur düğmesi `working` sırasında basılır → küre `idle`, yeni `Audio.play` olmaz.
  Run: `$env:PLAYWRIGHT_BROWSERS_PATH='D:\ClaudeSes\.pw-browsers'; .venv\Scripts\python -m playwright install chromium; .venv\Scripts\python -m pytest tests/e2e -v -m e2e`
  Expected: PASS.
- [ ] **Step 4: Tüm birim testleri** — `.venv\Scripts\python -m pytest tests -v` → PASS.
- [ ] **Step 5: `README.md`** — başlatma, `config.json` alanları, gizlilik notu (spec "Gizlilik" bölümünden), sorun giderme (`claude` girişi, mikrofon izni).
- [ ] **Step 6: Commit** — `git commit -m "feat: launcher, desktop shortcut, e2e test"`
