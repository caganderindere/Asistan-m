---
name: site-analizi
description: Bir web sitesini baştan sona analiz eder: teknik SEO, yapay zekâ aramalarında görünürlük (GEO), içerik, mesaj, dönüşüm ve rakipler; puanlı ve öncelikli düzeltme listesiyle rapor yazar. Çağan bir site, link ya da marka verip "incele, analiz et, denetle, ne eksik" dediğinde kullan.
---

# Site analizi

Amaç: Çağan'ın okuyup hemen iş verebileceği, kanıta dayalı bir rapor. Her bulgu bir sayfaya ya da ölçüme dayanır; görmediğini yazma.

## 1. Tarama (token harcamadan)
Önce teknik veriyi betikle topla, sayfaları tek tek WebFetch ile çekme:

```
{{python}} "{{tara}}" <site adresi> --sayfa 15 --hiz --cikti pazarlama/veri/<alan-adi>-tarama.json
```

Çıktı her sayfa için başlık, açıklama, H1/H2, kelime sayısı, altsız görseller, sosyal etiketler, yapısal veri, izleme kodları ve `sorunlar`; site için robots.txt, yapay zekâ botlarının erişimi, sitemap, llms.txt, hız (PageSpeed) ve `site_sorunlari` verir. `pazarlama/veri/` yoksa önce oluştur. Betik siteyi açamazsa (bot engeli, JavaScript ile çizilen site) Playwright araçlarıyla aç ve aynı bilgileri sayfadan oku.

## 2. Okuma (insan gözüyle)
Betik içeriği değerlendiremez; onu sen yaparsın. Ana sayfayı ve en önemli 3-5 sayfayı (ürün/hizmet, fiyat, hakkında, iletişim) WebFetch ile oku; görünüm önemliyse Playwright ile masaüstü ve mobil ekran görüntüsü al. Bak:
- **Mesaj:** İlk 5 saniyede ne sattığı, kime sattığı ve neden bu marka olduğu anlaşılıyor mu? Değer önerisini tek cümleyle yaz.
- **Dönüşüm:** Ana harekete geçirici çağrı (ara, satın al, teklif al, WhatsApp) belirgin mi, her sayfada var mı? Form kaç alan?
- **Güven:** Yorum, referans, logo, sertifika, gerçek fotoğraf, adres, telefon, KVKK.
- **Ton ve dil:** Hedef kitleye uygun mu, yazım hatası var mı?
- **İçerik:** Blog ya da rehber var mı, güncel mi, aranan sorulara cevap veriyor mu?

## 3. Pazar ve rakipler
WebSearch ile markanın adını (hakkında ne yazılmış, yorumlar, Google işletme profili), sektörün ana aramalarını ve en az üç rakibi bul. Her rakibin ana sayfasını oku; gerekirse aynı betiği `--sayfa 3` ile rakip için de çalıştır. Rakiplerin yapıp bu sitenin yapmadığı şeyleri yaz.

## 4. Yapay zekâ aramaları (GEO)
ChatGPT, Claude, Perplexity ve Google'ın yapay zekâ cevaplarında görünmek için: botlar robots.txt'te açık mı, llms.txt var mı, yapısal veri (Organization, LocalBusiness, Product, FAQ) var mı, sayfalar soru-cevap biçiminde net bilgi veriyor mu? WebSearch'te "<sektör> <şehir> en iyi" gibi bir soruda marka geçiyor mu, bak.

## 5. Puanlama
Her alana 0-10 puan ver, gerekçesini bir cümleyle yaz:
Teknik SEO · İçerik ve SEO · Yapay zekâ görünürlüğü · Mesaj ve değer önerisi · Dönüşüm · Güven · Hız ve mobil · Rakiplere göre konum.
Genel puan bunların ortalamasıdır; uydurma hassasiyet verme.

## 6. Rapor
`pazarlama/site-analizi-<alan-adi>-<YYYY-AA-GG>.md` dosyasına yaz:

```
# <Site> analizi — <tarih>
<3 cümlelik özet: genel puan, en büyük güç, en büyük sorun>

## Puan tablosu
| Alan | Puan | Neden |

## Öncelikli düzeltmeler
| # | Ne yapılmalı | Neden (kanıt: sayfa/ölçüm) | Etki (yüksek/orta/düşük) | Efor (saat/gün) | Kim (yazılım/içerik/sosyal) |
Önce yüksek etki + düşük efor. En fazla 15 madde.

## Bulgular
### Teknik SEO   ### İçerik   ### Yapay zekâ görünürlüğü   ### Mesaj ve dönüşüm   ### Güven   ### Hız ve mobil

## Rakipler
| Rakip | Güçlü yanı | Bizden iyi yaptığı |

## Hızlı kazanımlar
Bu hafta yapılabilecek 3-5 iş.

## Kaynaklar
Okunan sayfalar ve arama sonuçları, adresleriyle. Tarama verisi: pazarlama/veri/<alan-adi>-tarama.json
```

Sitenin kodu bu projedeyse "Kim" sütununda yazılım işi olanları Cuba ekibine verebilsin diye dosya yolunu da yaz. Raporun son mesajında genel puanı, en önemli üç düzeltmeyi ve dosya yolunu ver.
