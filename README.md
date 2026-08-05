# FlashForge AD5X Web Dashboard & Home Assistant Entegrasyonu

Bu proje, **FlashForge AD5X (Adventurer 5M / 5M Pro)** 3D yazıcıları için tasarlanmış modern bir **Web Kontrol Paneli (Web Dashboard)** ve **Home Assistant Özel Bileşeni (Custom Component)** içermektedir.

Yazıcının TCP kontrol portu (8899) ve HTTP detay/sensör portu (8898) protokolleri tersine mühendislik yöntemleriyle çözümlenerek; izleme, kontrol ve baskı sırasındaki ince ayarların (Live Tuning) yönetilmesi tek bir çatı altında birleştirilmiştir.

---
![Ana Ekran](https://git.mustafaozkaya.tr/hololu/FlashForgeAD5X/raw/branch/main/ad5x/flashforge_ad5x.jpg)
---
## 📂 Proje Yapısı

Proje dosyaları ve klasör mimarisi aşağıdaki şekildedir:

```text
flashforge/
├── flashforge_panel.py      # FastAPI tabanlı Web sunucu (Backend) & Kamera Proxy Dağıtıcısı
├── config.json              # Yazıcı bağlantı ve kalıcı ince ayarlar (Otomatik oluşturulur)
├── templates/
│   └── dashboard.html       # Modern, responsive ve premium Web Arayüzü (Frontend)
├── custom_components/
│   └── flashforge_ad5x/     # Home Assistant özel entegrasyonu
│       ├── __init__.py      # Entegrasyon başlangıç ve koordinatör yapılandırması
│       ├── api.py           # HA için özel FlashForge API istemcisi
│       ├── const.py         # Sabitler (Domain, scan interval vb.)
│       ├── config_flow.py   # HA Arayüzünden kurulum akışı (IP, port, LAN şifresi vb.)
│       ├── manifest.json    # HA entegrasyon özellikleri ve bağımlılıkları
│       ├── sensor.py        # Sıcaklık (nozul, yatak, hazne), katman, ilerleme, filament slotları, TVOC, disk alanı ve donanım sensörleri
│       ├── light.py         # Kabin aydınlatma kontrolü (HTTP ve TCP tabanlı)
│       ├── button.py        # Home, Duraklat, Devam Et, Durdur butonları
│       └── strings.json     # Çeviri tanımları
└── README.md                # Bu belgeleme dosyası
```

---

## ⚙️ Çalışma Mantığı ve Özellikler

### 1. Güvenli Kontrol Protokolü (Session Handshake)
FlashForge yazıcıları güvenlik nedeniyle TCP portu (8899) üzerinden gönderilen kontrol komutlarını doğrudan kabul etmez. Kontrol komutu gönderilmeden önce aynı TCP soket oturumunda login (`~M601 S1\r\n`) yapılması, işlem bittikten sonra ise oturumun serbest bırakılması (`~M602\r\n`) gerekir. 
* **Backend Çözümü:** `flashforge_panel.py` içindeki soket yönetim motoru, gönderilen komutun türünü (sorgu veya kontrol) otomatik olarak ayırt eder. Kontrol komutlarında soket açıldıktan hemen sonra arka planda el sıkışması gerçekleştirir ve işi bittiğinde oturumu sonlandırarak diğer ağ istemcilerinin (örneğin slicer yazılımları) yazıcıyı kilitlemesini önler.

### 2. Sunucu Üzerinden Canlı Kamera Proxy ve Eş Zamanlı Yayın (`CameraBroadcaster`)
Yazıcının dâhili `mjpg-streamer` kamera sunucusu donanımsal olarak aynı anda yalnızca 1 istemci bağlantısını kabul eder. Ayrıca dış ağdan veya HTTPS arkasından erişimde cihazın yerel IP'sine (port 8080) bağlanma zorunluluğu yayın hatalarına sebep olabilmektedir.
* **Sunucu Proxy (`/api/camera/stream`):** Kamera yayını sunucu üzerinden iletilir. Dış ağdan, VPN veya reverse proxy üzerinden bağlanan kullanıcılar yerel yazıcı IP'sine ihtiyaç duymadan yayını izler.
* **Eş Zamanlı Yayıncı (Multi-Client Fan-Out):** Arka planda çalışan `CameraBroadcaster` sınıfı yazıcı ile **tek bir aktif kamera bağlantısı** sürdürür ve gelen MJPEG karelerini bağlı tüm istemcilere (telefon, bilgisayar, tablet) aynı anda yayınlar.
* **Sıfır Ekstra Bağımlılık (Standard Library):** Kamera proxy ve snapshot (`/api/camera/snapshot`) mekanizması Python'ın standart kütüphanesi (`urllib.request`) ile hazırlanmıştır, ekstra üçüncü taraf bağımlılığı gerektirmez.

### 3. Etkileşimli IFS (Filament İstasyonu) Slot Seçimi & Değişimi
Adventurer 5M Pro / AD5X modellerindeki 4-slotlu Filament İstasyonu (IFS) arayüzde etkileşimli hale getirilmiştir.
* **Filament Değiştirme:** Kart üzerindeki Slot 1, 2, 3 veya 4 butonlarına tıklandığında onay verilerek yazıcıya ilgili slot değişim G-kodları (`T0`, `T1`, `T2`, `T3`) gönderilir ve aktif filament otomatik olarak değiştirilir.

### 4. Baskı İnce Ayarları (Live Tuning) Takibi
Yazıcının standart HTTP ve TCP durum sorguları; baskı hızı çarpanı, fan gücü ve nozul Z-ofset (babystepping) gibi anlık ince ayar durumlarını dışarıya raporlamaz.
* **Backend Çözümü:** Panel üzerinden gönderilen ince ayar komutları (`M220`, `M106`, `SET_GCODE_OFFSET`, `M290` ve `G29.1`) sunucu tarafında regex filtreleriyle yakalanır, durum güncellenir ve `config.json` dosyasına kaydedilir. Arayüz sorgu yaptığında bu değerler arayüze senkronize edilerek sayfa yenilense bile son ayarlanan ince ayarların ekranda kalması sağlanır.

### 5. Baskı Bitiminde Otomatik Sıfırlama
Baskı tamamlandığında veya iptal edildiğinde yazıcı donanımsal olarak eski Z-ofset veya hız çarpanı değerlerini koruyabilir, bu da bir sonraki baskıda tablanın nozula çarpmasına veya baskı hatalarına yol açabilir.
* **Backend Çözümü:** Yazıcının durumu `BUILDING_FROM_SD` veya `PAUSED` durumundan `READY` (Boşta) durumuna geçtiğinde; **Z-Ofset** `0.00 mm`, **Hız Çarpanı** `%100` ve **Fan Gücü** `%0` (Kapalı) değerlerine otomatik olarak sıfırlanır ve kalıcı hafızaya kaydedilir.

### 6. Detaylı Donanım ve Çevre Durumu Takibi (HTTP 8898 /detail API)
Yazıcının `/detail` REST API'sinden gelen tüm zengin donanım ve çevre verileri çözümlenmiştir:
* **Backend & Panel Çözümü:** Web arayüzüne **Sistem & Donanım Bilgileri** kartı eklenerek; Hazne Sıcaklığı (anlık/hedef), TVOC Hava Kalitesi, Sol/Sağ Soğutma Fanları, Odacık Fanı, Kapı/Kasa Işığı durumları, Disk Alanı, Toplam Çalışma Süresi, Toplam Filament Tüketimi, Nozul Çapı ve IP/MAC bilgileri gerçek zamanlı olarak izlenebilir hale getirilmiştir.
* **Home Assistant Çözümü:** Entegrasyona **14 adet yeni sensör** eklenerek bu veriler akıllı ev otomasyonlarında kullanılabilir hale getirilmiştir (örneğin hava kalitesi TVOC yükseldiğinde havalandırmanın çalıştırılması veya hazne sıcaklığına göre bildirim gönderilmesi). Kasa LED ışığının açık/kapalı durumu da HTTP API `light_status` ile senkronize edilmiştir.

---

## 🚀 Devreye Alma ve Çalıştırma

### A. Web Dashboard Kurulumu ve Başlatılması

1. **Bağımlılıkların Kurulması:**
   Sisteminizde Python 3.9+ kurulu olduğundan emin olun. Gerekli kütüphaneleri yükleyin:
   ```bash
   pip install fastapi uvicorn jinja2 pydantic
   ```

2. **Çevre Değişkenleri (Opsiyonel):**
   Uygulama varsayılan olarak `config.json` dosyasını arar. Eğer bu dosya yoksa, yazıcı bağlantı bilgilerini çevre değişkenlerinden alabilir:
   - `FLASHFORGE_HOST`: Yazıcının IP Adresi (Örn: `192.168.1.12`)
   - `FLASHFORGE_PORT`: Yazıcı Kontrol Portu (Varsayılan: `8899`)
   - `FLASHFORGE_SERIAL`: Yazıcı Seri No (IFS filament bilgisi için gerekli)
   - `FLASHFORGE_CHECK_CODE`: Yazıcı LAN Şifresi (IFS filament bilgisi için gerekli)

3. **Sunucunun Başlatılması:**
   Terminal veya PowerShell üzerinden proje kök dizininde şu komutu çalıştırın:
   ```bash
   python3 -m uvicorn flashforge_panel:app --host 0.0.0.0 --port 8000
   ```

4. **Kullanıcı Arayüzüne Erişim:**
   Tarayıcınızdan `http://localhost:8000` (veya sunucu IP'si üzerinden `http://<sunucu_ip>:8000`) adresine giderek kontrol paneline erişebilirsiniz. Sağ üst köşedeki **Ayarlar** (çark) simgesinden yazıcı IP adresi ve LAN kimlik bilgilerini canlı olarak güncelleyebilirsiniz.

---

### B. Home Assistant Entegrasyonu Kurulumu

1. Proje içindeki `custom_components/flashforge_ad5x` klasörünü Home Assistant kurulumunuzun içindeki `/config/custom_components/` dizinine kopyalayın.
2. Klasör yapısının `/config/custom_components/flashforge_ad5x/manifest.json` şeklinde olduğundan emin olun.
3. Home Assistant sunucunuzu yeniden başlatın.
4. HA arayüzünden **Ayarlar -> Cihazlar & Hizmetler -> Entegrasyon Ekle** adımlarını izleyin.
5. Listeden **FlashForge AD5X** entegrasyonunu arayın ve seçin.
6. Gelen yapılandırma penceresinde yazıcınızın IP adresini, Portunu (8899), Seri Numarasını ve LAN modundaki şifresini (Check Code) girerek kurulumu tamamlayın.

---

## 🛠️ İnce Ayar (Tuning) Komut Referansları
Dashboard üzerinden gönderilen ve arka planda desteklenen G-kod karşılıkları:

* **Z-Ofset Babystepping:** `SET_GCODE_OFFSET Z_ADJUST={değer} MOVE=1` ve `M290 Z{değer}` komutları ardışık gönderilerek hem Klipper hem Marlin uyumluluğu sağlanır.
* **IFS Slot Değişimi:** `T0`, `T1`, `T2`, `T3` komutları ile ilgili filament slotuna otomatik geçiş yapılır.
* **Baskı Hızı Çarpanı (Feedrate):** `M220 S{yüzde}` komutu gönderilir. Sürgü adımları %5 hassasiyetle çalışır.
* **Soğutma Fanı Gücü:** `%` olarak girilen değer `S0` ile `S255` arasına ölçeklenerek `M106 S{değer}` şeklinde gönderilir.
* **Kabin LED Kontrolü:** LED açma için `M146 r255 g255 b255 f0`, kapatma için `M146 r0 g0 b0 f0` komutları kullanılır.

