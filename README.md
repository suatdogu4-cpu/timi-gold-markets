# timi-gold-markets

## Freqtrade bağlantısı

Analiz > Matematik + Quant > Freqtrade görünümünde bot verilerini göstermek için sunucu ortamında şu değişkenleri tanımlayın:

- `FREQTRADE_API_URL`: Freqtrade REST API'nin HTTPS adresi
- `FREQTRADE_API_USERNAME`: Freqtrade API kullanıcı adı
- `FREQTRADE_API_PASSWORD`: Freqtrade API parolası

Kimlik bilgilerini kaynak koda veya tarayıcıya koymayın. Güvenlik için Freqtrade API'sini herkese açık bırakmayın; mümkünse VPN veya özel tünel kullanın. Bu entegrasyon salt okunurdur; emir göndermez ve botu kontrol etmez. Değişkenler tanımlı değilse ekran bağlantı yapılandırması gerektiğini gösterir.