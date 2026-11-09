# Claude Ses — Tasarım

Tarih: 2026-11-10 · Durum: onaylandı (sürüm 2)

## Amaç

Bilgisayarda yerel çalışan, Claude Code üzerinde kurulu, eller serbest Türkçe **kişisel asistan**.
Kullanıcı konuşur; asistan bilgisayarda tam yetkiyle iş yapar, plan ve notları tutar, hatırlatma kurar
ve doğal Türkçe sesle yanıt verir.

**Başarı ölçütleri**
- Türkçe telaffuz doğal (Edge `tr-TR-EmelNeural`).
- Kullanıcının Türkçe konuşması ve özel isimleri doğru yazıya dökülür (Whisper `large-v3-turbo` + kelime listesi).
- Masaüstü kısayoluyla açılır; küreye bir kez tıklandıktan sonra tuşa basmadan art arda konuşulur.
- "Yarın saat üçte X'i hatırlat" denince, uygulama kapalı olsa bile o saatte bildirim gelir ve sesli okunur.
- "Bu hafta ne işlerim var" sorusu kalıcı plan dosyalarından yanıtlanır.
- Claude'un o an ne yaptığı ekranda görünür ve tek tuşla durdurulur.

## Kullanıcının kararları

| Konu | Karar |
|---|---|
| Konum | `D:\ClaudeSes` |
| Claude yetkisi | Tam yetki, onay sorulmaz (`--permission-mode bypassPermissions`) |
| Çalışma klasörü | `D:\` kökü |
| Yapı | Bağımsız küçük uygulama (Jarvis'e eklenmez) |
| Yerleşim | A — ortada ses küresi |
| Ses | `tr-TR-EmelNeural` (kadın) |
| Kapsam | Kişisel asistan: planlama, hafıza, hatırlatma |

## Gizlilik

- Konuşma tanıma yereldir (Whisper); ses kaydı bilgisayardan çıkmaz.
- Yazıya dökülen metin ve asistanın okuduğu plan/not dosyaları Claude'a, yani Anthropic'e gider.
- Seslendirilen metinler (yanıtlar ve hatırlatmalar) Microsoft Edge seslendirme hizmetine gider (resmi olmayan erişim yolu, internet gerekir).
- Sunucu yalnızca `127.0.0.1` adresini dinler.

## Mimari

```
Tarayıcı (index.html)  ⇄ WebSocket ⇄  Yerel sunucu (FastAPI, 127.0.0.1:8765)
  mikrofon, sessizlik algılama          ├─ claude_bridge → claude.exe (tek, açık oturum, asistan talimatı)
  küre, konuşma, ses çalma              ├─ stt           → faster-whisper large-v3-turbo (GPU, yoksa CPU)
                                        └─ tts           → edge-tts (tr-TR-EmelNeural)

Windows Görev Zamanlayıcı → tools\remind.py <id> → bildirim + sesli okuma   (uygulamadan bağımsız)
```

### Birimler

| Birim | Görevi | Bağımlılığı |
|---|---|---|
| `server/config.py` + `config.json` | Port (8765), çalışma klasörü (`D:\`), ses (`tr-TR-EmelNeural`), Whisper modeli (`large-v3-turbo`), kelime listesi; dosya yoksa bu varsayılanlar | — |
| `server/session_store.py` | Son oturum kimliğini `data/session.json` içinde saklar | — |
| `server/claude_events.py` | Claude stream-json satırlarını olaylara çevirir | — |
| `server/claude_bridge.py` | `claude` sürecini başlatır, mesaj yazar, olay akışını okur, keser, çökünce yeniden başlatır | `claude` komutu |
| `server/sentences.py` | Akan metni cümlelere böler; kod, yol ve komut çıktısını sesli metinden ayıklar | — |
| `server/stt.py` | Ses → Türkçe metin; GPU'yu dener, olmazsa CPU; kelime listesini ipucu olarak verir; uydurma metinleri eler | faster-whisper, CUDA 12 kitaplıkları |
| `server/tts.py` | Metin → WAV | edge-tts, soundfile |
| `server/app.py` | HTTP + WebSocket uç noktaları | FastAPI, uvicorn |
| `assistant/reminders.py` | Hatırlatma ekle / listele / sil; Windows zamanlanmış görevi oluşturur | PowerShell `ScheduledTasks` |
| `tools/reminder.py` | Claude'un kullandığı komut satırı: `add`, `list`, `delete` | `assistant/reminders.py` |
| `tools/remind.py` | Zamanı gelince bildirim gösterir ve metni sesli okur | `server/tts.py`, `winsound` |
| `asistan/ASISTAN.md` | Asistanın kişiliği ve kuralları (Claude'a `--append-system-prompt-file` ile verilir) | — |
| `asistan/` veri dosyaları | `gorevler.md`, `takvim.md`, `notlar.md`, `hatirlatmalar.json` | — |
| `web/` | Küre, konuşma, işlem satırı; mikrofon ve ses çalma | Tarayıcı API'leri |
| `start.cmd` + masaüstü kısayolu | Sunucuyu başlatır, tarayıcıyı açar | — |

### Claude bağlantısı

```
claude -p --input-format stream-json --output-format stream-json --verbose
       --include-partial-messages --permission-mode bypassPermissions
       --append-system-prompt-file D:\ClaudeSes\asistan\ASISTAN.md [--resume <oturum>]
```

- Çalışma klasörü `D:\`. Abonelik kullanılır; API anahtarı gerekmez.
- Talimat dosyası yalnızca bu uygulamanın oturumuna eklenir; D:'deki diğer Claude Code oturumlarını etkilemez.

## Kişisel asistan

### Talimat (`asistan/ASISTAN.md`)

- Kullanıcının kişisel asistanısın; Türkçe, kısa ve konuşma diliyle yanıt ver. Kod, yol ve uzun çıktıları yazıya bırak, sesle özetle.
- Her konuşmanın başında `D:\ClaudeSes\asistan\` içindeki `gorevler.md`, `takvim.md`, `notlar.md` dosyalarını oku.
- Görev, randevu veya not söylendiğinde ilgili dosyayı güncelle ve ne kaydettiğini tek cümleyle söyle.
- Hatırlatma istendiğinde `D:\ClaudeSes\.venv\Scripts\python.exe D:\ClaudeSes\tools\reminder.py add --at "YYYY-MM-DD HH:MM" --text "..."` çalıştır; "yarın", "akşam" gibi ifadeleri bugünün tarihine göre çöz ve kurduğun zamanı söyle.
- Belirsiz zaman ("sonra hatırlat") verilirse saati sor.
- "Günün planı" istendiğinde bugünün takvimi, açık görevler ve bugünkü hatırlatmaları özetle.

### Veri dosyaları

Düz metin; kullanıcı da elle açıp düzenleyebilir. `gorevler.md`: `- [ ]` listesi, isteğe bağlı tarih.
`takvim.md`: `## YYYY-MM-DD` başlıkları altında `HH:MM — açıklama`. `notlar.md`: serbest metin.
`hatirlatmalar.json`: `[{id, at, text, created}]`.

### Hatırlatmalar

- `reminder.py add` kaydı `hatirlatmalar.json`'a yazar ve Windows Görev Zamanlayıcı'da `\ClaudeSes\` klasörüne tek seferlik görev oluşturur:
  `pythonw.exe D:\ClaudeSes\tools\remind.py <id>`. Metin komut satırına değil dosyaya yazılır (Türkçe ve tırnak sorunları olmaz).
- Tarih PowerShell'e `DateTime` nesnesi olarak verilir (Türkçe bölge ayarındaki tarih biçiminden etkilenmez).
- Görev `StartWhenAvailable` ile kurulur: bilgisayar o saatte kapalıysa açılınca çalışır.
- `remind.py`: Windows bildirimi gösterir, metni Emel sesiyle seslendirip çalar; ses alınamazsa yalnızca bildirim. Çalıştıktan sonra kaydı "tamamlandı" işaretler, zamanlanmış görevi siler.
- `list` gelecekteki hatırlatmaları, `delete <id>` kaydı ve görevi siler.
- Bilgisayar açık ve kullanıcının oturumu açık olmalı; uygulamanın açık olması gerekmez.

### Günün planı

Uygulama açıldıktan sonra küreye ilk tıklamada, gün içinde ilk kez ise sunucu Claude'a
"Günün planını kısaca özetle." mesajını gönderir; asistan selamlayıp planı okur, sonra dinlemeye geçer.
Günün ilk açılışı `data/last_briefing.txt` içindeki tarihle anlaşılır.

## Konuşma tanıma

- Model `large-v3-turbo`, `language="tr"`, `vad_filter=True`.
- Önce GPU (`cuda`, `int8_float16`); CUDA 12 kitaplıkları (`nvidia-cublas-cu12`, `nvidia-cudnn-cu12`) uygulamanın kendi ortamına kurulur ve DLL klasörleri başlangıçta yüklenir. GPU başlatılamazsa CPU (`int8`) kullanılır ve arayüzde bir kez "Ses tanıma işlemcide çalışıyor (daha yavaş)" gösterilir.
- Kelime listesi (`config.json` → `vocabulary`) Whisper'a `initial_prompt` olarak verilir. Varsayılan: `["Çağan", "Claude", "WordPress", "Nevka Kağıt", "Telsiz Mağaza", "BalBal Medya"]`.
- Uydurma metinler ("Altyazı M.K.", "İzlediğiniz için teşekkürler", "Abone olmayı unutmayın") ve 2 karakterden kısa metinler Claude'a gönderilmez.

## Konuşma akışı

1. Kullanıcı küreye tıklar → eller serbest mod başlar (gerekirse önce günün planı okunur).
2. Tarayıcı mikrofonu açar. İlk 400 ms ortam gürültüsünü ölçer; konuşma başladıktan sonra 1,5 sn sessizlikte veya 30 sn sınırında kaydı bitirir.
3. Ses sunucuya gider → Whisper metne çevirir → metin ekranda görünür.
4. Metin anlamsızsa mikrofon yeniden açılır; değilse Claude'a gönderilir.
5. Claude çalışırken araç olayları canlı işlem satırında görünür. Bu sırada mikrofon "dur" kelimesini dinler.
6. Yanıt metni cümlelere bölünür; her cümle seslendirilip sırayla çalınır.
7. Son cümle bitince mikrofon yeniden açılır. Asistan konuşurken mikrofon kapalıdır.

## Arayüz (Yerleşim A)

- Üst satır: çalışma klasörü (`D:\`), bağlantı durumu, **Yeni konuşma**.
- Orta: ses küresi, durum yazısı, canlı işlem satırı.
- Alt: son kullanıcı cümlesi ve yanıt; "▸ N işlem" açılır listesi; kaydırılabilir geçmiş.
- **Dur (Esc)** her zaman görünür.

| Küre | Durum |
|---|---|
| Mavi, nabız | Dinliyor |
| Mor, dönen | Düşünüyor / çalışıyor |
| Yeşil, sesle titreşen | Konuşuyor |
| Gri | Bekliyor |
| Kırmızı | Hata; açıklaması altında |

## Durdurma

- **Dur** veya `Esc`: ses durur, Claude'a kesme isteği gider (3 sn içinde durmazsa süreç sonlandırılıp aynı oturumla yeniden başlatılır), eller serbest kapanır.
- Claude çalışırken söylenen "dur" aynı işi yapar; asistan konuşurken yalnızca düğme veya `Esc` çalışır.
- Durdurma yetkiyi kısıtlamaz, yalnızca o anki işi keser.

## Hata durumları

| Durum | Davranış |
|---|---|
| Edge sesi alınamadı | Yanıt yalnızca yazıyla, uyarı gösterilir, döngü sürer |
| Whisper hata verdi | Uyarı, mikrofon yeniden açılır; 3 ardışık hatada eller serbest kapanır |
| GPU başlatılamadı | CPU'ya geçilir, bir kez bilgi gösterilir |
| `claude` süreci kapandı | Aynı oturumla yeniden başlatılır, kullanıcıya bildirilir |
| `claude` bulunamadı / giriş yok | Kırmızı küre: "Claude Code bulunamadı ya da giriş yapılmamış. Bir terminalde 'claude' yazıp giriş yapın." |
| Mikrofon izni yok | Eller serbest kapanır, izin verme yolu gösterilir |
| WebSocket koptu | 2 sn aralıkla yeniden bağlanır |
| Hatırlatma görevi oluşturulamadı | `reminder.py` hata koduyla çıkar; Claude bunu kullanıcıya söyler |

## Kurulum

- `D:\ClaudeSes\.venv`: Python 3.13 (uv); paketler: fastapi, uvicorn, faster-whisper, edge-tts, soundfile, numpy, nvidia-cublas-cu12, nvidia-cudnn-cu12.
- uv önbelleği `D:\ClaudeSes\.uv-cache`; Whisper modeli `D:\ClaudeSes\models` (`HF_HOME`), yaklaşık 1,6 GB.
- Masaüstüne `Claude Ses` kısayolu → `start.cmd` → sunucu + `http://127.0.0.1:8765`. Pencere kapanınca sunucu ve `claude` kapanır; hatırlatmalar Windows'ta kalır.

## Test

- **Birim (pytest):** ayarlar, oturum kaydı, Claude olay ayrıştırma (gerçek kayıtlarla), köprü (sahte süreçle: Türkçe karakter, çökme, kesme), cümle bölme, uydurma metin eleme, TTS (kayıtlı MP3), sunucu sözleşmesi, hatırlatma ekle/listele/sil (zamanlayıcı sahte), tarih çözümleme, günün planı tetikleme.
- **Entegrasyon:** gerçek bir hatırlatmayı 1 dakika sonrasına kurup bildirimin ve sesin geldiğini doğrulama; Whisper'ın GPU'da yüklendiğini ve örnek Türkçe cümleyi doğru yazdığını doğrulama.
- **Uçtan uca:** Playwright ile sahte mikrofondan Türkçe ses; gerçek Claude ile tam tur, Dur düğmesi.
- **Kullanıcıya bırakılan:** gerçek mikrofon ve hoparlörle deneme.

## Kapsam dışı

Uyandırma kelimesi, asistan konuşurken sözünü kesme, telefon/ağ erişimi, Google Takvim veya
telefon eşitlemesi, tekrarlayan hatırlatmalar (her gün / her hafta), ses ayarları ekranı.
