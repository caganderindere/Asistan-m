# Claude Ses — Tasarım

Tarih: 2026-11-10 · Durum: onay bekliyor

## Amaç

Bilgisayarda yerel çalışan, Claude Code'a bağlı, eller serbest Türkçe sesli bir arayüz.
Kullanıcı konuşur, Claude işi yapar ve sesli yanıt verir; döngü kullanıcı durdurana kadar sürer.

**Başarı ölçütü:** Masaüstü kısayoluyla açılır, küreye bir kez tıklandıktan sonra tuşa basmadan
art arda sesli konuşma yapılabilir; Claude'un o an ne yaptığı ekranda görünür ve tek tuşla durdurulur.

## Kullanıcının kararları

| Konu | Karar |
|---|---|
| Konum | `D:\ClaudeSes` |
| Claude yetkisi | Tam yetki, onay sorulmaz (`--permission-mode bypassPermissions`) |
| Çalışma klasörü | `D:\` kökü |
| Yapı | Bağımsız küçük uygulama (Jarvis'e eklenmez) |
| Yerleşim | A — ortada ses küresi |

## Gizlilik

- Konuşma tanıma yereldir (Whisper); ses kaydı bilgisayardan çıkmaz.
- Yazıya dökülen metin Claude'a, yani Anthropic'e gider.
- Seslendirilen yanıt metni Microsoft Edge seslendirme hizmetine gider (resmi olmayan erişim yolu, internet gerekir).
- Sunucu yalnızca `127.0.0.1` adresini dinler; ağdaki başka cihazlar erişemez.

## Mimari

```
Tarayıcı (index.html)  ⇄ WebSocket ⇄  Yerel sunucu (FastAPI, 127.0.0.1)
  mikrofon, sessizlik algılama          ├─ claude_bridge  → claude.exe (tek, açık oturum)
  küre, konuşma, ses çalma              ├─ stt            → faster-whisper (yerel, CPU)
                                        └─ tts            → edge-tts (tr-TR-AhmetNeural)
```

### Birimler

| Birim | Görevi | Bağımlılığı |
|---|---|---|
| `server/app.py` | HTTP + WebSocket uç noktaları, birimleri bağlar | FastAPI, uvicorn |
| `server/claude_bridge.py` | `claude` sürecini başlatır, mesaj yazar, olay akışını ayrıştırır, keser, çökünce yeniden başlatır | `claude` komutu |
| `server/sentences.py` | Akan metni cümlelere böler; kod bloklarını, yolları ve komut çıktısını sesli okunacak metinden ayıklar | — |
| `server/stt.py` | WAV/WebM ses → Türkçe metin | faster-whisper |
| `server/tts.py` | Cümle → WAV ses | edge-tts, soundfile |
| `server/session_store.py` | Son oturum kimliğini `data/session.json` içinde saklar | — |
| `server/config.py` + `config.json` | Port (8765), çalışma klasörü (`D:\`), ses (`tr-TR-AhmetNeural`), Whisper modeli (`base`); dosya yoksa bu varsayılanlar | — |
| `web/index.html`, `web/app.js`, `web/style.css` | Küre, konuşma, işlem satırı, düğmeler; mikrofon ve ses çalma | Tarayıcı API'leri |
| `start.cmd` + masaüstü kısayolu | Sunucuyu başlatır, tarayıcıyı açar | — |

### Claude bağlantısı

Sunucu tek bir uzun ömürlü süreç çalıştırır:

```
claude -p --input-format stream-json --output-format stream-json --verbose
       --include-partial-messages --permission-mode bypassPermissions
       --append-system-prompt "<sesli yanıt talimatı>" [--resume <oturum>]
```

- Çalışma klasörü `D:\` olarak verilir.
- Her kullanıcı cümlesi standart girdiye tek satırlık bir JSON kullanıcı mesajı olarak yazılır.
- Standart çıktıdaki olaylardan şunlar kullanılır: metin parçaları (yanıt akışı), araç kullanımı
  (canlı işlem satırı), sonuç (tur bitti, oturum kimliği).
- Sesli yanıt talimatı: "Türkçe, kısa ve konuşma diliyle yanıt ver; kod, yol ve uzun çıktıları
  yazıya bırak, sesle özetle."
- Abonelik kullanılır; API anahtarı gerekmez.

## Konuşma akışı

1. Kullanıcı küreye tıklar → eller serbest mod başlar (tıklama, mikrofon ve otomatik ses çalma izni için gereklidir).
2. Tarayıcı mikrofonu açar. İlk 400 ms ortam gürültüsünü ölçer; konuşma başladıktan sonra 1,5 sn sessizlikte veya 30 sn sınırında kaydı bitirir.
3. Ses sunucuya gider → Whisper Türkçe metne çevirir → metin ekranda görünür.
4. Metin boşsa mikrofon yeniden açılır. Değilse Claude'a gönderilir.
5. Claude çalışırken araç olayları canlı işlem satırında görünür (`⟳ Bash: git status`). Bu sırada mikrofon "dur" kelimesini dinler.
6. Yanıt metni geldikçe cümlelere bölünür; her cümle seslendirilip sırayla çalınır.
7. Son cümle bitince mikrofon yeniden açılır. Claude konuşurken mikrofon kapalıdır (yankı önlemi).

## Arayüz (Yerleşim A)

- Üst satır: çalışma klasörü (`D:\`), bağlantı durumu, **Yeni konuşma** düğmesi.
- Orta: ses küresi ve altında durum yazısı, canlı işlem satırı.
- Alt: son kullanıcı cümlesi ve Claude yanıtı; "▸ N işlem" ile açılan ayrıntı listesi; tüm geçmiş için kaydırılabilir alan.
- **Dur (Esc)** düğmesi her zaman görünür.

| Küre | Durum |
|---|---|
| Mavi, nabız | Dinliyor |
| Mor, dönen | Claude düşünüyor / çalışıyor |
| Yeşil, sesle titreşen | Konuşuyor |
| Gri | Bekliyor (eller serbest kapalı) |
| Kırmızı | Hata; açıklaması altında yazar |

## Durdurma

- **Dur** düğmesi veya `Esc`: ses çalmayı keser, Claude'a kesme sinyali gönderir (süreç durmazsa sonlandırılıp aynı oturumla yeniden başlatılır), eller serbest modu kapatır.
- Claude çalışırken söylenen "dur" aynı işi yapar. Claude konuşurken mikrofon kapalı olduğu için o anda yalnızca düğme veya `Esc` çalışır.
- Durdurma Claude'un yetkisini kısıtlamaz; yalnızca o anki işi keser.

## Hata durumları

| Durum | Davranış |
|---|---|
| Edge sesi alınamadı | Yanıt yalnızca yazıyla gösterilir, kırmızı olmayan uyarı çıkar, döngü sürer |
| Whisper hata verdi | Uyarı gösterilir, mikrofon yeniden açılır; 3 ardışık hatada eller serbest kapanır |
| `claude` süreci kapandı | Aynı oturum kimliğiyle yeniden başlatılır, kullanıcıya bildirilir |
| `claude` bulunamadı / giriş yapılmamış | Kırmızı küre, çözüm metni (`claude` komutunu bir kez çalıştırıp giriş yapma) |
| Mikrofon izni yok | Eller serbest kapanır, izin verme yolu gösterilir |
| WebSocket koptu | Tarayıcı 2 sn aralıkla yeniden bağlanır |

## Kurulum

- `D:\ClaudeSes\.venv`: Python 3.13 (uv ile), paketler: fastapi, uvicorn, faster-whisper, edge-tts, soundfile, numpy.
- uv önbelleği `D:\ClaudeSes\.uv-cache`; Whisper `base` modeli mevcut Hugging Face önbelleğinden kullanılır.
- Masaüstüne `Claude Ses` kısayolu → `start.cmd` → sunucu + `http://127.0.0.1:8765` tarayıcıda.
- Pencere kapanınca sunucu ve `claude` süreci kapanır.

## Test

- **Birim testleri (pytest):** cümle bölme ve ayıklama; Claude olay akışı ayrıştırma (kayıtlı örnek
  satırlarla); oturum kaydetme; durdurma ve yeniden başlatma mantığı (sahte süreçle).
- **Uçtan uca:** Playwright ile tarayıcıya sahte mikrofondan Türkçe ses verilir; gerçek Claude'dan
  yanıt gelip seslendirildiği ve mikrofonun yeniden açıldığı doğrulanır. Ayrıca Dur düğmesi test edilir.
- **Kullanıcıya bırakılan:** gerçek mikrofon ve hoparlörle deneme.

## Kapsam dışı

Uyandırma kelimesi ("Hey Claude"), Claude konuşurken sözünü kesme, telefondan/ağdan erişim,
birden çok paralel konuşma, ses ayarları ekranı (ses `config.json` içinden değiştirilir).
