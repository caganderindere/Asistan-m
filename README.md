# Claude Ses

Claude Code üzerinde çalışan, Türkçe konuşan eller serbest kişisel asistan.
Sen konuşursun; asistan bilgisayarında işi yapar, planını ve notlarını tutar,
hatırlatma kurar ve Emel'in sesiyle yanıt verir.

## Başlatma

- Masaüstündeki **Claude Ses** kısayoluna çift tıkla (ya da `start.cmd`).
  Ses tanıma modeli yüklenince tarayıcıda `http://127.0.0.1:8765` açılır.
- **Küreye dokun**: günün ilk açılışıysa asistan günün planını okur, sonra dinler.
  Konuş, susunca gönderilir; yanıt bitince yeniden dinler.
- **Dur** düğmesi ya da `Esc` her şeyi durdurur. Claude çalışırken "dur" demek de yeter
  (asistan konuşurken mikrofon kapalıdır; o sırada düğmeyi kullan).
- **Yeni konuşma** sohbet geçmişini sıfırlar; plan, not ve hatırlatmalar kalır.
- Kapatmak için küçültülmüş "Claude Ses" komut penceresini kapat. Claude da onunla kapanır.

Kısayol silinirse: `powershell -ExecutionPolicy Bypass -File D:\ClaudeSes\tools\make_shortcut.ps1`

## Ekip ve ofis

Sen yalnızca **Takım Lideri** ile konuşursun. Lider işi dört çalışana dağıtır; her biri
ayrı bir Claude Code sürecidir ve kendi modelinde çalışır.

| Departman | Çalışan | Varsayılan model | İş |
|---|---|---|---|
| Yönetim | Takım Lideri | `claude-fable-5-2` | Seninle konuşur, planlar, dağıtır, raporlar |
| Mühendislik | Kıdemli Geliştirici | `claude-fable-5-2` | Zor işler |
| Mühendislik | Geliştirici | `claude-sonnet-5-5` | Orta işler |
| Kalite | Testçi | `claude-sonnet-5-5` | Test ve inceleme |
| Destek | Asistan | `claude-haiku-5-5` | Basit işler |

- **Akış:** işi söylersin, lider planı okuyup onayını ister, "tamam" deyince ekip başlar.
  Biten her işin raporu lidere gider; lider sana özetler.
- **Riskli işler** (silme, `git push`, paket kurma, proje dışına yazma): çalışan durur,
  lider sana sorar. Bu kural çalışanların talimatındadır, teknik bir kilit değildir.
- **Projeler (sol):** Claude Code'da kullandığın klasörler listelenir; tıklayınca ekip o
  klasöre geçer. Her projenin konuşması ve görevleri ayrı saklanır. Çalışan varken proje
  değiştirirsen süren işler yarıda kalır.
- **Ofis (orta):** çalışan masasında, plan onay beklerken herkes toplantı odasında,
  işini yeni bitiren mutfakta, uzun süredir boşta olan dinlenme alanında görünür.
  Birine tıklayınca görevi ve son yaptıkları açılır.
- Kurallar `asistan\ASISTAN.md`, `ekip\LIDER.md` ve `ekip\CALISAN.md` dosyalarındadır.

## Ayarlar — `config.json` (isteğe bağlı)

```json
{
  "voice": "tr-TR-EmelNeural",
  "vocabulary": ["Çağan", "Claude", "WordPress", "Nevka Kağıt", "Telsiz Mağaza", "BalBal Medya"],
  "whisper_model": "large-v3-turbo",
  "workdir": "D:\\",
  "port": 8765,
  "models": { "kidemli": "claude-opus-5-5" }
}
```

Yalnızca değiştirmek istediğin alanları yaz. `models` içinde `lider`, `kidemli`,
`gelistirici`, `testci`, `asistan` için model seçebilirsin. `vocabulary`, ses tanımanın doğru yazmasını
istediğin özel isimlerdir (müşteriler, siteler, kişiler). Erkek ses için `tr-TR-AhmetNeural`.
Değişiklikten sonra uygulamayı kapatıp aç.

## Asistanın hafızası — `asistan\`

| Dosya | İçerik |
|---|---|
| `ASISTAN.md` | Asistanın kuralları ve kişiliği (düzenleyebilirsin) |
| `gorevler.md` | Görevler (`- [ ]` / `- [x]`) |
| `takvim.md` | `## YYYY-MM-DD` altında randevular |
| `notlar.md` | Notlar |
| `hatirlatmalar.json` | Hatırlatma kayıtları |

Hepsi düz metin; elle de düzenleyebilirsin.

## Hatırlatmalar

Asistan "yarın saat üçte X'i hatırlat" deyince Windows Görev Zamanlayıcı'da
`\ClaudeSes\` altında tek seferlik bir görev kurar. Zamanı gelince bildirim çıkar ve
sesli okunur — uygulama kapalı olsa bile (bilgisayar ve oturum açık olmalı; bilgisayar
o saatte kapalıysa açılınca gelir).

```powershell
D:\ClaudeSes\.venv\Scripts\python.exe D:\ClaudeSes\tools\reminder.py list
D:\ClaudeSes\.venv\Scripts\python.exe D:\ClaudeSes\tools\reminder.py delete <id>
```

## Gizlilik

- Ses kaydın bilgisayardan çıkmaz; yazıya dökme yerel Whisper ile yapılır.
- Söylediklerinin yazısı ve asistanın okuduğu dosyalar Claude'a (Anthropic) gider.
- Seslendirilen yanıtlar ve hatırlatmalar Microsoft Edge seslendirme hizmetine gider
  (resmi olmayan erişim yolu; internet gerekir, ileride çalışmayı bırakabilir).
- Sunucu yalnızca bu bilgisayardan (`127.0.0.1`) erişilebilir.
- Ekip **tam yetkiyle** çalışır: Claude süreçleri izin sormadan dosya değiştirip komut
  çalıştırabilir. Plan onayı ve riskli iş sorusu talimatla sağlanır.

## Sorun giderme

| Belirti | Çözüm |
|---|---|
| Kırmızı küre: "Claude Code bulunamadı…" | Bir terminalde `claude` yazıp giriş yap, uygulamayı yeniden aç |
| "Mikrofon izni gerekli" | Adres çubuğundaki kilit simgesinden mikrofona izin ver |
| "Ses tanıma işlemcide çalışıyor" | Ekran kartı kullanılamadı; çalışır ama daha yavaştır. Başka bir uygulama (ör. Ollama) ekran kartı belleğini dolduruyor olabilir |
| Söylediğim algılanmıyor | Windows ses ayarlarında doğru mikrofonun varsayılan olduğundan emin ol |
| "Başka bir sekmede açıldı" | Uygulama yalnızca bir sekmede çalışır; diğer sekmeyi kullan |
| Ses yok, yalnızca yazı | İnternet bağlantısını kontrol et (Edge sesi çevrimiçi) |

Günlükler: `data\remind.log` (hatırlatmalar).

## Geliştirme

```powershell
.venv\Scripts\python -m pytest                     # birim testleri
.venv\Scripts\python -m pytest -m "network or gpu" # gerçek Edge sesi ve ekran kartında Whisper
$env:PLAYWRIGHT_BROWSERS_PATH='D:\ClaudeSes\.pw-browsers'
.venv\Scripts\python -m pytest -m e2e -s           # gerçek Claude ile uçtan uca (uygulama kapalıyken)
```
