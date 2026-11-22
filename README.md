# timi-gold-markets

## Freqtrade bağlantısı

Analiz > Matematik + Quant > Freqtrade sekmesindeki bot durumu, portföy, işlem geçmişi, Freqtrade mumları ve strateji sinyal analizini açmak için Render Environment bölümünde şu değişkenleri tanımlayın:

- `FREQTRADE_API_URL`: Freqtrade REST API'nin HTTPS adresi
- `FREQTRADE_API_USERNAME`: Freqtrade API kullanıcı adı
- `FREQTRADE_API_PASSWORD`: Freqtrade API parolası
- `FREQTRADE_UI_PASSWORD`: En az 16 karakterli, API parolasından farklı panel parolası

Kimlik bilgilerini kaynak koda veya tarayıcıya koymayın. Freqtrade API'sini internete herkese açık bırakmayın; mümkünse VPN veya özel tünel kullanın. Panel parolası ile açılan oturum HTTP-only, SameSite çerezi kullanır. Başlat/duraklat/durdur/yeni girişleri durdur/ayarları yeniden yükle kontrolleri ayrıca onay ister. Canlı modda botu başlatmak gerçek işlemlere yol açabilir. Panel manuel alış/satış emri göndermez.

Strateji analizi Freqtrade'in `/pair_history` çıktısını, mum görünümü `/pair_candles` verisini kullanır. Bu API uçları analiz ve sinyal verisi sağlar; Freqtrade REST API üzerinden yeni backtest çalıştırıldığı anlamına gelmez. Bağlantı değişkenleri yoksa panel bunu açıkça bildirir.

## XGBoost araştırma işi

XGBoost eğitimi bellek/CPU tüketimi nedeniyle web isteği içinde çalıştırılmaz; araştırma bağımlılıkları ve zaman sıralı doğrulama `.github/workflows/gold-ml-daily.yml` içinde yürütülür, web uygulaması yayımlanan JSON raporunu okur. Eğitim bağımlılığı bulunmadığında model kodu artık traceback yerine `DEPENDENCY_UNAVAILABLE` durumu döndürür.