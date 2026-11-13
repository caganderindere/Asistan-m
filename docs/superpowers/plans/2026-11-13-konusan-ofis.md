# Konuşan Ofis (Faz 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pazarlama ekibi ücretsiz modellerle (OmniRoute `ofis` combo'su) çalışan, birbirine soru soran ve sesli Cuba'nın açtığı toplantıda söz alıp gerçekten cevap veren ofis çalışanlarına dönüşür.

**Architecture:** Sunucuda hafif bir ajan döngüsü (`server/worker.py`) OmniRoute'un OpenAI uyumlu ucunu araç çağırmayla kullanır. Çalışanlar arası mesajlar `server/office_bus.py` üzerinden geçer ve kaydedilir; mesaj atan çalışan, alıcının tek seferlik cevabını araç sonucu olarak alır (alıcı cevap verirken araç kullanamaz, bu yüzden zincir kendiliğinden biter). Canlı toplantı (`server/office_meeting.py`) ofiste mevcut `TerminalCrew.review` oynatmasıyla (balon + ses) gösterilir; sesli Cuba'ya dört yeni araç eklenir.

**Tech Stack:** Python 3.13, FastAPI, httpx (mevcut), pytest; düz JS (web/).

**Spec:** `docs/superpowers/specs/2026-11-13-konusan-ofis-design.md`

## Global Constraints

- Model erişimi yalnızca OmniRoute: `http://127.0.0.1:20128/v1/chat/completions`, anahtar `data/omniroute_key.txt` ya da `OMNIROUTE_API_KEY`, varsayılan model `ofis`.
- Yeni bağımlılık yok; HTTP için `httpx`.
- Sınırlar: bir görevde çalışan başına en çok 12 model çağrısı; bir görevde en çok 4 `mesaj_at`; toplantıda bir söz en çok 2 cümle (prompt ile) ve 300 karakter (kesme ile).
- Pazarlama çıktısı proje içinde `pazarlama/` altına yazılır; proje klasörü dışına ya da `pazarlama/` dışına yazma reddedilir.
- Silme, push, proje dışına yazma yok (ekip/CALISAN.md kuralları).
- Kullanıcıya görünen metin Türkçe.
- Yalnızca bu plandaki dosyalar commit'e eklenir (`git add <dosya>`); depoda başka commit edilmemiş iş var.

## Review Focus

- OmniRoute kapalı ya da anahtar yok: çalışan "hata" durumuna geçmeli, Cuba'ya `[EKİP RAPORU]` içinde "model erişimi yok" gitmeli; sessizce takılmamalı. (Task 1 ve Task 3 testleri)
- Ücretsiz sağlayıcı limiti (HTTP 429): aynı şekilde açık hata ve rapor, döngü durmalı. (Task 1 testi)
- Model `dosya_yaz` ile `../` ya da mutlak yol verirse: reddedilmeli, araç sonucu hata metni olmalı, dosya yazılmamalı. (Task 3 testi)
- Var olmayan bir çalışana `mesaj_at` / `soz_ver`: hata metni dönmeli, istisna fırlamamalı. (Task 3 ve Task 4 testleri)
- Toplantı açık değilken `soz_ver` ya da `toplanti_kapat`: Cuba'ya "açık toplantı yok" dönmeli. (Task 4 testi)

---

### Task 1: OmniRoute istemcisi

**Files:**
- Create: `server/omni.py`
- Test: `tests/test_omni.py`

**Interfaces:**
- Produces:
  - `class OmniError(Exception)`; `class OmniLimit(OmniError)` (429).
  - `def load_key(path: Path = ROOT / "data" / "omniroute_key.txt") -> str` — önce `OMNIROUTE_API_KEY`, yoksa dosya, yoksa `""`.
  - `class OmniClient(key: str, base_url: str = "http://127.0.0.1:20128/v1", model: str = "ofis", transport: httpx.AsyncBaseTransport | None = None, timeout: float = 60)`
  - `async def OmniClient.chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict` — `choices[0].message` sözlüğünü döner (`content`, isteğe bağlı `tool_calls`).
  - `OmniClient.available -> bool` (anahtar var mı).

- [ ] **Step 1: Failing tests** — `httpx.MockTransport` ile:
  - `test_chat_returns_message`: 200 + `{"choices":[{"message":{"content":"Merhaba"}}]}` → `msg["content"] == "Merhaba"`; isteğin `Authorization` başlığı `Bearer k`, gövdesinde `model == "ofis"`, `stream is False`.
  - `test_tools_are_sent_and_tool_calls_returned`: tools verilince gövdede `tools` var; cevaptaki `tool_calls` aynen döner.
  - `test_limit_raises_omnilimit`: 429 → `OmniLimit`.
  - `test_unreachable_raises_omnierror`: transport `httpx.ConnectError` fırlatır → `OmniError` ("OmniRoute'a ulaşılamadı" metniyle).
  - `test_no_key_raises`: `OmniClient("").chat(...)` → `OmniError`, `available is False`.
  - `test_load_key_prefers_env(monkeypatch, tmp_path)`.
- [ ] **Step 2:** `.venv/Scripts/python.exe -m pytest tests/test_omni.py -q` → FAIL (modül yok).
- [ ] **Step 3:** `server/omni.py`'yi yaz. 401/403 → `OmniError("OmniRoute anahtarı geçersiz")`, diğer 4xx/5xx → `OmniError` ile sunucunun `error.message`'ı.
- [ ] **Step 4:** Testler PASS.
- [ ] **Step 5:** `git add server/omni.py tests/test_omni.py && git commit -m "feat: OmniRoute client for office workers"`

### Task 2: Ofis mesaj kanalı

**Files:**
- Create: `server/office_bus.py`
- Test: `tests/test_office_bus.py`

**Interfaces:**
- Produces:
  - `@dataclass class Message: sender: str; to: str; text: str; channel: str = "birebir"; time: str = ""` (`time` boşsa `HH:MM` doldurulur).
  - `class OfficeBus(log_dir: Path, clock: Callable[[], datetime.datetime] = datetime.datetime.now)`
  - `OfficeBus.post(self, message: Message) -> Message` — kaydeder, `log_dir/YYYY-MM-DD.jsonl`'e bir satır ekler, abonelere verir.
  - `OfficeBus.subscribe(self, listener: Callable[[Message], None]) -> None`
  - `OfficeBus.recent(self, who: str, limit: int = 10) -> list[Message]` — `who`'nun gönderdiği ya da aldığı son mesajlar, eskiden yeniye.

- [ ] **Step 1: Failing tests:** `test_post_logs_and_notifies` (dosyada bir JSON satırı, dinleyici bir kez çağrıldı, `time` dolu), `test_recent_filters_by_person` (3 mesajdan ikisi `pazarlama`ya ait → 2 döner, sıra korunur), `test_listener_error_does_not_stop_post` (dinleyici istisna atar, `post` yine döner ve ikinci dinleyici çağrılır).
- [ ] **Step 2:** FAIL doğrula.
- [ ] **Step 3:** Uygula; bellekte en çok 200 mesaj tut.
- [ ] **Step 4:** PASS.
- [ ] **Step 5:** Commit `feat: office message bus`.

### Task 3: Ofis çalışanı (ajan döngüsü)

**Files:**
- Create: `server/worker.py`
- Modify: `server/prompts.py` (yeni `office_prompt(role: Role) -> str`, mevcut `worker_prompt` + `CALISAN.md` kullanır; "Ekip toplantısı" ve "Rapor" metinleri aynen kalır)
- Create: `ekip/OFIS_CALISANI.md` (araç kullanım kuralları: soru için `mesaj_at`, bitince `rapor_ver`; "soru soramazsın" yerine "bölüm arkadaşına `mesaj_at` ile danışabilirsin, en çok 4 kez")
- Test: `tests/test_worker.py`

**Interfaces:**
- Consumes: `OmniClient.chat`, `OmniError` (Task 1); `OfficeBus.post`, `OfficeBus.recent`, `Message` (Task 2).
- Produces:
  - `MAX_CALLS = 12`, `MAX_MESSAGES = 4`, `LINE_CHARS = 300`
  - `class OfficeWorker(role: Role, omni: OmniClient, bus: OfficeBus, colleagues: Callable[[str], "OfficeWorker | None"], search: Callable[[str], Awaitable[dict]] | None = None, on_activity: Callable[[str, str], None] = lambda who, what: None)`
  - `async def OfficeWorker.run(self, task: str, folder: Path) -> str` — görev döngüsü; dönen değer rapor metni. Hata durumunda `"HATA: <neden>"` ile başlayan rapor döner, istisna fırlatmaz.
  - `async def OfficeWorker.answer(self, sender: str, question: str, context: str = "") -> str` — araçsız tek çağrı; en çok 300 karakter.
  - Araçlar (OpenAI `tools` biçimi): `dosya_oku(yol)`, `dosya_yaz(yol, icerik)`, `web_ara(soru)` (yalnız `search` verildiyse), `mesaj_at(kime, metin)`, `rapor_ver(metin)`.
  - `on_activity(role_id, açıklama)` her araç çağrısında ve bitişte (`""`) çağrılır.

- [ ] **Step 1: Failing tests** (sahte `OmniClient`: sıradaki cevapları listeden veren bir sınıf):
  - `test_run_writes_file_and_reports`: model önce `dosya_yaz("pazarlama/plan.md", "# Plan")`, sonra `rapor_ver("Plan yazıldı")` çağırır → `tmp_path/"pazarlama/plan.md"` içeriği `# Plan`, dönüş `"Plan yazıldı"`.
  - `test_write_outside_pazarlama_is_refused`: `dosya_yaz("../x.md", ...)` ve `dosya_yaz("src/app.py", ...)` → dosya yok; modele dönen araç sonucu `"HATA"` içerir.
  - `test_mesaj_at_returns_colleague_answer_and_is_logged`: model `mesaj_at("icerik", "Ton ne?")` çağırır; `icerik` çalışanının `answer`ı `"Samimi"` döner → modele giden araç sonucu `"Samimi"` içerir; bus'ta iki mesaj (soru ve cevap) var.
  - `test_unknown_colleague`: `mesaj_at("yok", ...)` → araç sonucu `"HATA"` içerir.
  - `test_message_limit`: model 5 kez `mesaj_at` çağırır → 5.'si `"HATA"` (sınır), bus'ta 8 mesaj.
  - `test_call_limit_stops_loop`: model hep `dosya_oku` çağırır → tam 12 `chat` çağrısından sonra `"HATA"` ile başlayan rapor.
  - `test_omni_error_becomes_report`: `chat` `OmniError("OmniRoute'a ulaşılamadı")` fırlatır → rapor `"HATA: OmniRoute'a ulaşılamadı"`.
  - `test_answer_is_short_and_toolless`: `answer` çağrısında `chat`'e `tools=None` gider; 500 karakterlik cevap 300'e kesilir.
- [ ] **Step 2:** FAIL doğrula.
- [ ] **Step 3:** Uygula. Sistem mesajı: `office_prompt(role)` + `OFIS_CALISANI.md` + bus'taki `recent(role.id)` özeti. Model araç çağırmadan düz metin dönerse o metin rapor sayılır. Yol kontrolü: `(folder / yol).resolve()` `folder / "pazarlama"` altında olmalı (`dosya_oku` için proje klasörü yeterli).
- [ ] **Step 4:** PASS; ardından tüm paket: `.venv/Scripts/python.exe -m pytest -q`.
- [ ] **Step 5:** Commit `feat: office workers on free models`.

### Task 4: Canlı toplantı

**Files:**
- Create: `server/office_meeting.py`
- Test: `tests/test_office_meeting.py`

**Interfaces:**
- Consumes: `OfficeWorker.answer` (Task 3); `OmniClient.chat` (Task 1); `OfficeBus.post` (Task 2).
- Produces:
  - `class LiveMeeting(workers: Callable[[str], OfficeWorker | None], omni: OmniClient, bus: OfficeBus, show: Callable[[dict | None], Awaitable[None]])` — `show` toplantı durumunu ofise yollar (`{"members": [...], "speaker": id, "lines": [{"who","text"}], "names": {...}}`) ya da kapanınca `None`.
  - `async def open(self, topic: str, members: list[str]) -> dict` → `{"ok": True, "katilimcilar": [...]}`; bilinmeyen kişi varsa `{"error": ...}`.
  - `async def give_floor(self, who: str, question: str) -> dict` — Cuba'nın sorusunu satır olarak ekler, çalışanın `answer`ını (bağlam: konu + önceki satırlar) bekler, satırı ekler, `show` çağırır; `{"who", "text"}` döner. Açık toplantı yoksa `{"error": "Açık toplantı yok."}`.
  - `async def close(self) -> dict` → `{"kararlar": [...], "gorevler": [{"kim","is"}]}`; `omni.chat` ile JSON özet; özet bozuksa boş listeler; `show(None)`.
  - `@property is_open -> bool`.

- [ ] **Step 1: Failing tests:** `test_floor_gets_a_real_answer` (sahte çalışan `"Almanya'da bayi ağı"` der → dönüş ve `show`'a giden son satır bu; satırlar `[cuba soru, pazarlama cevap]`), `test_floor_without_meeting`, `test_unknown_member_on_open`, `test_close_summarizes_and_clears` (sahte omni JSON döner → kararlar geldi, `show(None)` çağrıldı, `is_open` False), `test_close_with_bad_json_returns_empty`.
- [ ] **Step 2:** FAIL doğrula.
- [ ] **Step 3:** Uygula; her satır `OfficeBus.post(Message(..., channel="toplanti"))` ile kaydedilir.
- [ ] **Step 4:** PASS.
- [ ] **Step 5:** Commit `feat: live meetings where members really answer`.

### Task 5: Cuba'ya araçlar ve sunucu bağlantısı

**Files:**
- Modify: `server/live.py` (`LIVE_TOOLS`'a 4 araç; `CubaTools.__init__`'e `office: "Office | None" = None`; `run` içinde dallar)
- Create: `server/office.py` (sunucunun ofis cephesi)
- Modify: `server/app.py` (Office'i kur, `cuba_tools()`'a ver, toplantı ve masa durumunu ofise yansıt)
- Modify: `server/terminal.py` (`TerminalCrew.office_work(desk: str, activity: str)`, `TerminalCrew.office_rest(desk: str)`, `TerminalCrew.show_meeting(review: dict | None)` — mevcut `_work`/`_rest`/`review` üzerinden)
- Modify: `server/prompts.py` (`write_terminal_team`: departmanı `Pazarlama` olan roller artık `cuba-ekip` alt ajanı olarak yazılmaz)
- Modify: `ekip/CANLI.md` (pazarlama işi `ekibe_ver` ile; toplantı `toplanti_ac` → `soz_ver` → `toplanti_kapat`; "bir çalışanın adına asla konuşma, cevabını bekle"; "rapor gelmeden geldi deme"; ofis bölümündeki "ikisi de terminale_ver ile verilir" cümlesi düzeltilir)
- Test: `tests/test_office.py`, `tests/test_live.py` (ekleme), `tests/test_terminal.py` (ekleme)

**Interfaces:**
- Consumes: Task 1–4.
- Produces:
  - `class Office(omni, bus, crew_for: Callable[[str], TerminalCrew], tell: Callable[[str], Awaitable[None]], push: Callable[[str], Awaitable[None]], search=None)` — `push(folder)` ofis görünümünü tarayıcıya yollar.
  - `Office.MEMBERS = ("pazarlama", "icerik", "sosyal")`
  - `async def give(self, who: str, task: str, folder: str) -> dict` — işi arka planda başlatır, hemen `{"ok": True, "not": "Ekip işe başladı; bitince [EKİP RAPORU] gelecek."}` döner; bitince `tell(f"[EKİP RAPORU — {proje}] {isim}: {rapor}")`.
  - `async def open_meeting(...)`, `give_floor(...)`, `close_meeting(...)` — `LiveMeeting`'e devreder; `give_floor` hemen `{"ok": True, "not": "Söz verildi; cevap gelince [SÖZ — isim] olarak duyacaksın."}` döner, cevap gelince `tell(f"[SÖZ — {isim}] {metin}")`.
  - Live araçları: `ekibe_ver(kim, proje, talimat)`, `toplanti_ac(konu, kisiler: array)`, `soz_ver(kim, soru)`, `toplanti_kapat()`. Proje çözümü mevcut `find_project` ile, `terminale_ver` ile aynı hata metni.

- [ ] **Step 1: Failing tests:**
  - `tests/test_office.py::test_give_reports_back` — sahte çalışan `"Bitti"` döner → `tell` `"[EKİP RAPORU"` ve `"Bitti"` içeren metinle çağrıldı; çalışırken `crew.snapshot()` içinde `pazarlama` `working`, sonra `idle`.
  - `tests/test_office.py::test_floor_answer_is_told_to_cuba` — `give_floor` hemen döner; görev bitince `tell` `"[SÖZ — Pazarlamacı]"` ile çağrıldı.
  - `tests/test_office.py::test_give_rejects_non_member` — `give("kidemli", ...)` → `{"error": ...}` (yazılım ekibi Faz 2'ye kadar terminalde).
  - `tests/test_live.py::test_office_tools_route_to_office` — `CubaTools(..., office=fake).run("soz_ver", {...})` sahte office'e ulaşır; `office=None` iken `{"error": ...}`.
  - `tests/test_terminal.py::test_marketing_is_not_a_terminal_subagent` — `write_terminal_team` sonrası `agents/pazarlama.md` yok, `agents/gelistirici.md` var.
  - `tests/test_terminal.py::test_office_work_and_meeting_show_on_crew` — `office_work("icerik","Yazıyor")` → `working`; `show_meeting({...})` → `phase == "review"`; `show_meeting(None)` → `review is None`.
- [ ] **Step 2:** FAIL doğrula.
- [ ] **Step 3:** Uygula. `app.py`'de: `OmniClient(load_key())`, `OfficeBus(data_dir / "ofis")`, `Office(..., crew_for=crew_for, tell=live.tell, push=lambda f: clients.send(crew_view(f)), search=search if gemini_key else None)`; bus dinleyicisi her mesajı `clients.send({"type": "office_message", ...})` ve `talk.add(isim, metin, "ofis")` ile yayar. Live kapalıysa `tell` Telegram'a (mevcut `meet` deseni).
- [ ] **Step 4:** Tüm paket PASS: `.venv/Scripts/python.exe -m pytest -q`.
- [ ] **Step 5:** Commit `feat: Cuba runs the marketing team and meetings on free models`.

### Task 6: Ofis akışında çalışan mesajları

**Files:**
- Modify: `web/app.js` (`case 'office_message'`: `addFeed(msg.sender, isim, "→ " + alıcı + ": " + metin, 'office')`)
- Modify: `web/style.css` (`.feed .office` küçük bir renk ayrımı, mevcut değişkenlerle)

**Interfaces:**
- Consumes: Task 5'in yayınladığı `{"type": "office_message", "sender", "to", "text", "channel"}`.

- [ ] **Step 1:** Uygula (UI; birim testi yok). Toplantı satırları zaten `review` ile balon ve sesle oynatılıyor; yalnızca birebir mesajlar akışa eklenir.
- [ ] **Step 2:** `node --check web/app.js` → çıktı yok.
- [ ] **Step 3: Uçtan uca elle doğrulama:** sunucuyu yeniden başlat; sesli Cuba'ya "Pazarlamacı, İçerikçi ve Sosyalci'yi toplantıya al, konu Almanya pazarı" de → ofiste üçü toplantı odasında; "Pazarlamacı, söz sende" → birkaç saniyede Pazarlamacı'nın balonu ve sesi, Cuba cevabı aktarır; "toplantıyı kapat" → `[TOPLANTI SONUCU]`. Sonra "Pazarlamacı'ya hedef kitle çalışması ver" → masasında çalışıyor, akışta İçerikçi'ye mesaj, projede `pazarlama/*.md`, `[EKİP RAPORU]`.
- [ ] **Step 4:** Commit `feat: show office messages in the feed`.
