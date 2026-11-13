# Konuşan Ofis — Faz 1 tasarımı

Tarih: 2026-11-13 · Durum: onay bekliyor

## Amaç ve neden
Çağan ekibin gerçek bir firma gibi çalışmasını istiyor: çalışanlar birbirine soru sorar, fikir alır, itiraz eder,
toplantıda tartışır; Cuba söz verdiğinde o kişi gerçekten cevap verir. Bugün bu yok: çalışanlar yalnızca Cuba'dan
görev alıp rapor veren, birbirinden habersiz Claude alt ajanları; "toplantı" ise işten sonra Gemini'nin tek seferde
yazdığı bir senaryo. Sesli Cuba'nın toplantı açma ya da söz verme aracı yok, bu yüzden "Pazarlamacı, söz sende"
cevapsız kalıyor.

İkinci neden maliyet: Çağan Claude token'ı harcamak istemiyor. Firma ücretsiz modellerle (OmniRoute üzerinden)
çalışmalı; Claude yalnızca takım koçu olmalı (Faz 3).

## Büyük resim (üç faz, bu belge yalnızca Faz 1)
1. **Konuşan ofis** — ortak mesajlaşma, gerçek toplantı ve söz verme; pazarlama ekibi tamamen yeni motora taşınır.
2. Yazılım ekibi de yeni motora geçer (dosya, komut, test araçları). Claude yalnızca istisna olarak nöbetçi.
3. Claude koç: gün/proje sonunda konuşmaları ve çıktıları okuyup her çalışana gelişim notu yazar; notlar prompt'a girer.

## Faz 1 hedefleri
- Ofis motoru: sunucuda çalışan, modelini OmniRoute'tan (OpenAI uyumlu `/v1/chat/completions`, araç çağırma ile)
  alan hafif ajanlar. Her çalışan bir rol prompt'u, kendi hafızası ve araçlarıyla bir döngüdür.
- Ortak mesaj kanalı: her çalışan bir başkasına yazabilir (`mesaj_at(kime, metin)`), gelen mesajı okuyup cevaplar.
  Her mesaj ofiste konuşma balonu ve o kişinin sesiyle görünür/duyulur; konuşma kaydına (`data/konusmalar`) düşer.
- Gerçek toplantı: Cuba (sesli, Gemini Live) `toplanti_ac(konu, kisiler)` ile toplantı açar, `soz_ver(kim, soru)` ile
  söz verir; söz verilen çalışan kendi rolü, hafızası ve ekibin son çıktılarıyla cevap verir, cevap Cuba'ya döner.
  Çalışanlar toplantıda birbirine de söz atabilir (biri diğerine soru sorarsa sıradaki söz onundur).
  `toplanti_kapat()` kararları ve önerilen işleri çıkarır (mevcut `[TOPLANTI SONUCU]` akışı).
- Pazarlama ekibi (Pazarlamacı, İçerikçi, Sosyalci) yeni motora taşınır. Cuba pazarlama işini `ekibe_ver(kim, talimat)`
  ile verir. Çalışan işi yaparken gerektiğinde bölüm arkadaşına danışır; çıktısını projede `pazarlama/` klasörüne yazar,
  raporunu Cuba'ya `[EKİP RAPORU]` olarak verir.
- Ofis görünümü: çalışan işteyken masasında "çalışıyor", toplantıdayken toplantı odasında, konuşurken balonla görünür.

## Faz 1'de olmayanlar
- Yazılım ekibinin taşınması (Faz 2): kod işi şimdilik terminaldeki Claude ekibinde kalır.
- Claude koçluğu (Faz 3).
- Çağan'ın çalışanlarla doğrudan sesli konuşması: Çağan Cuba'yla konuşur, Cuba söz verir.

## Başarısızlık sayılacak durumlar
- Ajanların kendi aralarında durmadan yazışıp kota tüketmesi ya da kısır döngüye girmesi.
- Çalışanın uydurması: olmayan dosyayı, kaynağı ya da rakamı varmış gibi söylemesi.
- Ücretsiz sağlayıcının limiti dolunca sistemin sessizce takılması; Çağan neden bir şey olmadığını her zaman görebilmeli.
- Sesli Cuba'nın gecikmesi: söz verilen cevabın beklemesi Live oturumunu düşürmemeli.

## Kısıtlar
- Dil Türkçe. Mevcut kod tabanı Python (FastAPI) + düz JS; yeni bağımlılık eklenmez, HTTP için mevcut `httpx`.
- Model erişimi yalnızca OmniRoute üzerinden: adres `http://localhost:20128/v1`, anahtar `data/omniroute_key.txt`
  (ya da `OMNIROUTE_API_KEY`), model adı çalışan başına ayarlanabilir (varsayılan: OmniRoute'ta Çağan'ın açacağı
  `ofis` combo'su). Combo birden çok ücretsiz sağlayıcıya yedekli yönlendirir; hangi sağlayıcılar olduğu koda girmez.
- OmniRoute şu an boş (sağlayıcı, combo, anahtar yok). Çağan panelden (localhost:20128) ücretsiz sağlayıcıları bağlar,
  `ofis` combo'sunu ve bir API anahtarı oluşturur. Bu yapılmadan motor "model erişimi yok" diye açıkça hata verir.
- Riskli iş kuralları aynen geçerli: silme, push, proje dışına yazma yok.

## Yaklaşımlar
- **A. Kendi ofis motorumuz (seçilen).** Ajan döngüsü ve mesaj kanalı sunucumuzda; model OmniRoute'tan. Kontrol ve
  görünürlük bizde, modeller tek satırla değişir. Bedeli: ajan döngüsünü biz yazıyoruz.
- B. Her çalışan ayrı bir OpenCode süreci + ofis MCP sunucusu. Kodlama araçları hazır, ama 7 ağır süreç ve
  dağınık kontrol; hata ayıklaması zor.
- C. Konuşma ücretsiz modelde, iş Claude'da. Kaliteli ama "Claude yalnızca koç" isteğine ters.
Çağan A'yı, üç fazlı ve Kıdemli için Claude istisnası olmadan seçti.

## Tasarım
**Modüller (yeni):**
- `server/omni.py` — OmniRoute istemcisi: sohbet + araç çağırma, zaman aşımı, 429/limit hatasını anlamlı istisnaya çevirir.
- `server/office_bus.py` — mesaj kanalı: `Message(kimden, kime, metin, zaman, kanal)`; kanallar: birebir, `toplanti`.
  Abonelik ile ofise ve konuşma kaydına yayın. Bellekte tutulur, günlük olarak `data/ofis/YYYY-MM-DD.jsonl`'e yazılır.
- `server/worker.py` — ofis çalışanı: rol prompt'u (`ekip/CALISAN.md` + bölüm yöntemi, mevcut `worker_prompt`),
  gelen kutusu, araç döngüsü. Araçlar: `dosya_oku`, `dosya_yaz` (yalnız proje içi, pazarlama için `pazarlama/` altı),
  `web_ara` (mevcut `search`), `mesaj_at`, `rapor_ver`.
- `server/office_meeting.py` — canlı toplantı: katılımcılar, konu, söz sırası, kayıt; `soz_ver` bir çalışanın tek
  cevabını üretir; `kapat` mevcut `meeting.py` mantığıyla karar/görev çıkarır.

**Değişen:**
- `server/live.py` — yeni araçlar: `ekibe_ver(kim, talimat)`, `toplanti_ac(konu, kisiler)`, `soz_ver(kim, soru)`,
  `toplanti_kapat()`. `ekip/CANLI.md`'ye kullanım kuralları ve "rapor gelmeden geldi deme, birinin adına konuşma".
- `server/prompts.py` — pazarlama rolleri artık terminal eklentisine (`cuba-ekip`) alt ajan olarak yazılmaz.
- `server/app.py` — motoru, kanalı ve toplantıyı kurar; ofise yeni olay tipleri yollar.
- `web/office.js`, `web/app.js` — balon, konuşma sesi (mevcut toplantı oynatma ve sesler) ve masa durumu yeni olaylardan.

**Döngü kuralları (kota ve kısır döngüye karşı):**
- Bir görevde çalışan başına en çok 12 model çağrısı; bir görevde bir çalışan en çok 4 mesaj atar.
- Bir mesaj zincirinde en çok 6 ileti; sonra konuşma Cuba'ya rapor olarak düşer.
- Toplantıda bir söz en çok 2 cümle; Cuba söz vermeden kimse iki kez üst üste konuşmaz.
- Limit/429: çalışan "beklemede" görünür, Cuba'ya bir kez haber gider; combo içi yedekleme OmniRoute'un işi.

**Gecikme:** `soz_ver` Live'a hemen "söz verildi" döner; cevap hazır olunca `[SÖZ — Pazarlamacı] ...` olarak Live'a
iletilir ve ofiste oynatılır, böylece Live araç çağrısı beklemede kalmaz.

## Kurucuya bırakılanlar
- Prompt ifadeleri, olay alan adları, balon görünümü, kayıt biçiminin ayrıntıları.
- Ses: mevcut toplantı seslerini (roster `voice`) kullanır.

## Kararları ben verdim (Çağan'ın onayına)
- Model adresi ve anahtar yeri, `ofis` combo adı.
- Döngü sınırları (12 / 4 / 6 / 2).
- Pazarlama çıktısının `pazarlama/` altında kalması.
- `soz_ver`'in eşzamansız cevap vermesi.
