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
| `cagan.md` | Cuba'nın senin hakkında öğrendikleri, bölüm bölüm (Tercihler, Projeler, İnsanlar…) |
| `gunluk\YYYY-MM-DD.md` | Her günün günlüğü: ne istendi, ne yapıldı, ne yarım kaldı |
| `gorevler.md` | Görevler (`- [ ]` / `- [x]`) |
| `takvim.md` | `## YYYY-MM-DD` altında randevular |
| `notlar.md` | Notlar |
| `hatirlatmalar.json` | Hatırlatma kayıtları |

Hepsi düz metin; elle de düzenleyebilirsin — en kolayı panodaki **Hafıza** sekmesi.

Cuba'yla her konuşma (sesli ya da Telegram) `data\konusmalar\` altına günlük olarak yazılır.
Gün bitince Cuba o günün günlüğünü yazar, senin hakkında yeni öğrendiklerini `cagan.md`'nin
uygun bölümüne ekler (hiçbir şeyi silmez) ve ertesi gün konuşmaya dünün sayfasını hatırlayarak başlar.
Hafıza sekmesindeki **Bugünü şimdi yaz** günü beklemeden yazdırır.

## Projeler ve toplantılar

Her projenin kendi terminali var: Cuba'ya "BalBal'a şunu ekle" deyip ardından "Portfolyo'da
şuna bak" dersen iki ekip aynı anda çalışır, biri ötekini durdurmaz. Proje listesinde çalışan
projelerin noktası mor yanıp söner; ofis o an açık olan projenin ekibini gösterir, **Akış**
sekmesi hepsini.

Bir işi iki ya da daha fazla alt ajan yaptıysa ekip iş bitince toplanır. Toplantı Gemini'de
yazılır (Claude token'ı harcamaz): ajanlar birbirine adıyla cevap verir, itirazı kime
yapıldıysa o yanıtlar, anlaşınca biter. Kararlar konuşmaya ve panoya düşer; önerilen işleri
Cuba sana sorar.

Ofiste yazıcıya (raporlar), panoya (görünüm değiştirir: görevler, ajanlar, token, kararlar),
saate (hafıza), kitaplığa (proje belgeleri) ve toplantı masasına (akış) tıklayabilirsin.
Başlıktaki **Token · bugün** bugün harcanan Claude (bu bilgisayardaki tüm Claude Code
oturumları) ve Gemini token'ını gösterir.

## Tek Cuba, tek ofis

Sesle, yazıyla ya da Telegram'dan konuştuğun hep aynı Cuba: aynı araçlar, aynı hafıza, günün
tek konuşma geçmişi. Ofis açık projenin gerçek ekibini gösterir; **Terminal** sekmesi aynı
projenin ham Claude Code ekranıdır ve oraya yazdığın doğrudan Claude Code'a gider.

Cuba kendinden emin bir müdür: sana "patron" der, fikrini söyler. Sesini Hafıza sekmesindeki
**Cuba'nın sesi** listesinden seçersin (varsayılan Algenib: kalın, pürüzlü).

**Ekip büyür.** "Cuba, bir tasarımcı işe al" dersen yeni bir uzman alınır: Claude Code alt ajanı
olur, ofiste boş masalardan birine oturur, toplantılarda kendi sesiyle konuşur (en fazla dört
kişi; `data\ekip.json`). Kod yazan ajanın masasının üstünde yazdığı kod hologram olarak akar.

**Toplantılar sesli.** Her ajan kendi sesiyle konuşur, konuşanın ağzı oynar. Ofisin üstündeki
**Toplantı sesi** düğmesiyle kapatabilirsin.

## "Cuba" de, dinlesin

Ses panelindeki **“Cuba” de** düğmesini açarsan küreye dokunmana gerek kalmaz: "Cuba" demen
yeterli; iPhone'da ana ekran uygulamasında da çalışır. Ad bilgisayardaki Whisper ile tanınır,
bekleme sırasında ses dışarı çıkmaz; düğme ne duyduğunu gösterir. Bir buçuk dakika kimse
konuşmazsa uykuya döner.

## Telefondan

**Canlı konuşma (Tailscale).** Bilgisayar evde açık kalır, telefon mikrofon ve hoparlör olur.

1. Bilgisayara ve telefona [Tailscale](https://tailscale.com/download) kur, ikisinde de aynı hesapla gir.
2. Bilgisayarda bir kez: `tailscale serve --bg 8765`
3. Cuba'yı yeniden başlat; pencerede `Telefondan: https://<bilgisayar>.<ağ>.ts.net` yazar.
4. Telefonda o adresi Chrome/Safari ile aç, **Ana ekrana ekle** de. Küreye dokun, konuş.

Adres yalnızca senin Tailscale cihazlarından açılır; internete açık değildir. Tailscale adı
kendiliğinden bulunmazsa `config.json`'a `"remote_hosts": ["pc.agin.ts.net"]` yaz.

**Telegram (yazı, sesli mesaj, bildirim, onay).**

1. Telegram'da @BotFather'a `/newbot` yaz, verdiği token'ı al.
2. `data\telegram.json` dosyası oluştur: `{"token": "123456:ABC..."}`
3. Cuba'yı yeniden başlat. Pencerede ve sayfada bir eşleme kodu çıkar; bota `/esle <kod>` yaz.

Bundan sonra bot yalnızca sana cevap verir. Yazabilir ya da sesli mesaj atabilirsin; Cuba
aynı araçlarla iş verir. Sen ekran başında değilken (ya da uzak moddayken) biten işler,
toplantı kararları ve **Evet/Hayır düğmeli** onay soruları telefonuna gelir.
Komutlar: `/durum`, `/uzak` (uzak modu aç-kapa), `/dur` (terminali durdur).

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

- Canlı konuşmada (varsayılan) sesin Gemini Live'a (Google) gider; klasik modda ses
  bilgisayardan çıkmaz, yazıya dökme yerel Whisper ile yapılır.
- Cuba'nın hafıza dosyaları, günlükler ve Telegram mesajları Gemini'ye gider; ekibe verilen
  işler ve projen Claude'a (Anthropic) gider.
- Seslendirilen yanıtlar ve hatırlatmalar Microsoft Edge seslendirme hizmetine gider
  (resmi olmayan erişim yolu; internet gerekir, ileride çalışmayı bırakabilir).
- Sunucu yalnızca bu bilgisayardan (`127.0.0.1`) ve kurduysan senin Tailscale cihazlarından
  erişilebilir. Ekip araç kurabilir (`pip`, `uv`, `npm`, `npx`, `winget`) ama paket kaldıramaz.
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
