# FlashForge AD5X Web Dashboard & Home Assistant Entegrasyonu

Bu proje, **FlashForge AD5X (Adventurer 5M / 5M Pro)** 3D yazıcıları için tasarlanmış modern bir **Web Kontrol Paneli (Web Dashboard)** ve **Home Assistant Özel Bileşeni (Custom Component)** içermektedir.

Yazıcının TCP kontrol portu (8899) ve HTTP detay/sensör portu (8898) protokolleri tersine mühendislik yöntemleriyle çözümlenerek; izleme, kontrol ve baskı sırasındaki ince ayarların (Live Tuning) yönetilmesi tek bir çatı altında birleştirilmiştir.

---
![Ana Ekran](https://www.mustafaozkaya.tr/hsensms-ss01.png)
---
## 📂 Proje Yapısı

Proje dosyaları ve klasör mimarisi aşağıdaki şekildedir:

```text
flashforge/
├── flashforge_panel.py      # FastAPI tabanlı Web sunucu (Backend)
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
│       ├── sensor.py        # Sıcaklık, katman, ilerleme ve filament slot sensörleri
│       ├── light.py         # Kabin aydınlatma kontrolü
│       ├── button.py        # Home, Duraklat, Devam Et, Durdur butonları
│       └── strings.json     # Çeviri tanımları
└── README.md                # Bu belgeleme dosyası
```

---

## ⚙️ Çalışma Mantığı ve Özellikler

### 1. Güvenli Kontrol Protokolü (Session Handshake)
FlashForge yazıcıları güvenlik nedeniyle TCP portu (8899) üzerinden gönderilen kontrol komutlarını doğrudan kabul etmez. Kontrol komutu gönderilmeden önce aynı TCP soket oturumunda login (`~M601 S1\r\n`) yapılması, işlem bittikten sonra ise oturumun serbest bırakılması (`~M602\r\n`) gerekir. 
* **Backend Çözümü:** `flashforge_panel.py` içindeki soket yönetim motoru, gönderilen komutun türünü (sorgu veya kontrol) otomatik olarak ayırt eder. Kontrol komutlarında soket açıldıktan hemen sonra arka planda el sıkışması gerçekleştirir ve işi bittiğinde oturumu sonlandırarak diğer ağ istemcilerinin (örneğin slicer yazılımları) yazıcıyı kilitlemesini önler.

### 2. Baskı İnce Ayarları (Live Tuning) Takibi
Yazıcının standart HTTP ve TCP durum sorguları; baskı hızı çarpanı, fan gücü ve nozul Z-ofset (babystepping) gibi anlık ince ayar durumlarını dışarıya raporlamaz.
* **Backend Çözümü:** Panel üzerinden gönderilen ince ayar komutları (`M220`, `M106`, `SET_GCODE_OFFSET`, `M290` ve `G29.1`) sunucu tarafında regex filtreleriyle yakalanır, durum güncellenir ve `config.json` dosyasına kaydedilir. Arayüz sorgu yaptığında bu değerler arayüze senkronize edilerek sayfa yenilense bile son ayarlanan ince ayarların ekranda kalması sağlanır.

### 3. Baskı Bitiminde Otomatik Sıfırlama
Baskı tamamlandığında veya iptal edildiğinde yazıcı donanımsal olarak eski Z-ofset veya hız çarpanı değerlerini koruyabilir, bu da bir sonraki baskıda tablanın nozula çarpmasına veya baskı hatalarına yol açabilir.
* **Backend Çözümü:** Yazıcının durumu `BUILDING_FROM_SD` veya `PAUSED` durumundan `READY` (Boşta) durumuna geçtiğinde; **Z-Ofset** `0.00 mm`, **Hız Çarpanı** `%100` ve **Fan Gücü** `%0` (Kapalı) değerlerine otomatik olarak sıfırlanır ve kalıcı hafızaya kaydedilir.

### 4. Gelişmiş Kamera Arayüzü ve Tam Ekran Desteği
Yazıcının 8080 portundaki canlı kamera akışı arayüzde 16:9 oranında gösterilir. Eklenen HTML5 Fullscreen API desteği sayesinde kullanıcılar **"Tam Ekran"** butonuna basarak kamerayı tam ekran moduna geçirebilirler. Bu modda görüntü ekran çözünürlüğüne göre en yüksek boyutta (`object-fit: contain`) ölçeklenir.

### 5. Akıllı IFS (Filament İstasyonu) Teşhisi
Eğer yazıcı **Adventurer 5M Pro** ise HTTP portu (8898) üzerinden IFS (Integrated Filament System) 4-slot bilgileri çekilir. Yazıcının standart **Adventurer 5M** olması veya LAN modunun kapalı olması durumunda oluşan `Connection refused (Errno 111)` hatası yakalanarak kullanıcıya yönlendirici ve anlaşılır bir hata açıklaması sunulur.

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
   python -m uvicorn flashforge_panel:app --host 0.0.0.0 --port 8000 --reload
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
* **Baskı Hızı Çarpanı (Feedrate):** `M220 S{yüzde}` komutu gönderilir. Sürgü adımları %5 hassasiyetle çalışır.
* **Soğutma Fanı Gücü:** `%` olarak girilen değer `S0` ile `S255` arasına ölçeklenerek `M106 S{değer}` şeklinde gönderilir.
* **Kabin LED Kontrolü:** LED açma için `M146 r255 g255 b255 f0`, kapatma için `M146 r0 g0 b0 f0` komutları kullanılır.
