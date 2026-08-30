# FlashForge AD5X Web Dashboard & Home Assistant Entegrasyonu

<p align="center">
  <img src="hFlashForgeLogo.svg" width="140" alt="FlashForge AD5X Logo"/>
</p>

<p align="center">
  <strong>FlashForge AD5X (Adventurer 5M / 5M Pro)</strong> 3D yazıcıları için modern, responsive <strong>Web Kontrol Paneli (Web Dashboard)</strong> ve tam donanımlı <strong>Home Assistant Özel Bileşeni (Custom Component)</strong>.
</p>

---

Yazıcının **TCP kontrol portu (8899)**, **HTTP detay/sensör portu (8898)** ve **MJPEG kamera portu (8080)** protokolleri çözümlenerek; durum izleme, canlı kamera yayını, donanım sensörleri, IFS filament yönetimi, makro kontroller ve baskı sırasındaki canlı ince ayarlar (Live Tuning) tek bir çatı altında birleştirilmiştir.

---

## 📂 Proje Yapısı

```text
flashforge/
├── hFlashForgeLogo.svg          # Vektörel SVG uygulama ve marka logosu
├── hFlashForgeLogo.png          # PNG formatında uygulama simgesi / favicon
├── flashforge_panel.py          # FastAPI tabanlı Web Sunucu (Backend) & Kamera Proxy Dağıtıcısı
├── config.json                  # Yazıcı bağlantı ve kalıcı ince ayarlar (Otomatik oluşturulur)
├── templates/
│   └── dashboard.html           # Modern, responsive ve premium Web Arayüzü (Frontend)
├── custom_components/
│   └── flashforge_ad5x/         # Home Assistant özel entegrasyonu
│       ├── __init__.py          # Entegrasyon başlangıç ve koordinatör yapılandırması
│       ├── api.py               # HA için asenkron FlashForge API istemcisi
│       ├── const.py             # Sabitler (Domain, scan interval vb.)
│       ├── config_flow.py       # HA arayüzünden kurulum ve bağlantı akışı
│       ├── manifest.json        # HA entegrasyon meta verileri ve bağımlılıkları
│       ├── sensor.py            # Sıcaklıklar, katman, ilerleme, TVOC, disk alanı ve donanım sensörleri
│       ├── light.py             # Kabin aydınlatma kontrolü (HTTP ve TCP tabanlı)
│       ├── button.py            # Home, Duraklat, Devam, Durdur, Oturumu Sıfırla (M602), Yeniden Başlat (M999)
│       ├── camera.py            # Canlı MJPEG kamera ve anlık görüntü yakalama entegrasyonu
│       └── strings.json         # Türkçe/İngilizce dil ve çeviri tanımları
├── homeassistant_guide.md       # Home Assistant detaylı kurulum, Lovelace kartları ve sorun giderme rehberi
└── README.md                    # Proje dokümantasyonu
```

---

## ⚙️ Temel Özellikler ve Çalışma Mantığı

### 1. 📷 3 Farklı Canlı Kamera Akış Modu (Camera Streaming)
Yazıcının dâhili `mjpg-streamer` kamera servisi donanımsal olarak tek bağlantı sınırı (single-client limit) içerebilir. Panel, her türlü ağ koşuluna uyum sağlayacak 3 farklı mod sunar:
* **🌐 Doğrudan Mod (Port 8080) [Varsayılan]:** Tarayıcınız yerel ağdayken doğrudan `http://<YAZICI_IP>:8080/?action=stream` adresine bağlanır. Sunucuya 0% yük bindirir, sıfır gecikmeyle (native 30fps) kristal netliğinde yayın verir.
* **🔄 Sunucu Proxy Modu (`/api/camera/stream`):** Dış ağdan, VPN veya Reverse Proxy arkasından erişen kullanıcılar için yayını `CameraBroadcasterThread` motoru üzerinden proxy'ler ve birden fazla istemciye aynı anda dağıtır.
* **📸 Snapshot Modu (`/api/camera/snapshot`):** Düşük bant genişliği veya stabil olmayan bağlantılarda saniyede 1 kare (1 fps) anlık fotoğraf çeker.
* **Tam Ekran Desteği:** Kamera akışını tek tıkla tam ekran moduna alabilirsiniz.

---

### 2. 🛠️ Sistem & Servis Yönetimi (Settings Modal)
Web arayüzünün sağ üstündeki **⚙️ Ayarlar** penceresi ve **Uçbirim (G-Code Konsolu)** üzerinden kritik operasyonlar tek tıkla yürütülür:
* **🔄 Servisleri Yeniden Başlat (`/api/service/restart`):** Panel arka plan sorgulayıcısını (`watch_loop`), soket havuzunu ve kamera yayıncısını temizleyip baştan başlatır.
* **📷 Kamerayı Sıfırla (`/api/camera/restart`):** Askıda kalan kamera istemci soketlerini kapatır ve yeni bağlantı açar.
* **🔓 Oturumu Serbest Bırak (`/api/printer/unlock` - `~M602`):** FlashForge yazıcısı kilitli bir oturumda takılı kaldığında soket kilidini açar.
* **⚠️ Yazıcıyı Yeniden Başlat (`/api/printer/restart` - `~M999`):** Yazıcı anakartına ve firmware'ine yeniden başlatma sinyali gönderir.

---

### 3. 🎛️ Canlı İnce Ayar (Live Tuning) & Otomatik Sıfırlama
* **Babystepping (Z-Ofset):** Baskı sırasında tablanın ilk katman mesafesini `0.01 mm`, `0.05 mm` veya `0.10 mm` adımlarla canlı olarak ayarlama. `SET_GCODE_OFFSET` ve `M290` komutları ardışık gönderilerek hem Klipper hem Marlin uyumluluğu sağlanır.
* **Baskı Hızı Çarpanı (Feedrate):** `%5` hassasiyetli sürgü ile `M220 S{yüzde}` komutu gönderimi.
* **Kabin Soğutma Fanı:** `%` sürgü değeriyle `M106 S{değer}` komutu üzerinden anlık fan devri ayarı.
* **Baskı Bitiminde Otomatik Sıfırlama:** Baskı tamamlandığında veya iptal edildiğinde (`READY` moduna geçildiğinde); Z-Ofset `0.00 mm`, Hız `%100` ve Fan `%0` değerlerine otomatik olarak çekilir.

---

### 4. 🧵 Etkileşimli IFS (Filament İstasyonu) Yönetimi
* AD5X / Adventurer 5M Pro 4-slotlu Filament İstasyonu durumunu (Slot rengi, malzeme tipi, yüklü slot) görselleştirir.
* Arayüzdeki slot kartına tıklandığında onay istenerek yazıcıya otomatik `T0`, `T1`, `T2`, `T3` filament değiştirme komutu gönderilir.
* "Filamenti Çıkar" butonuyla aktif slot serbest bırakılabilir.

---

### 5. 📊 Zengin Donanım & Sensör Telemetrisi (HTTP 8898 /detail API)
* **Kabin & Hazne Sıcaklığı:** Anlık ve hedef sıcaklık takibi.
* **TVOC Hava Kalitesi:** Hazne içi VOC gazı seviyesi (`ppb`).
* **Fan Hızları:** Sol Fan, Sağ/Ana Soğutma Fanı ve Hazne Fanı devirleri (`%`).
* **Kapı & LED Durumu:** Kapı açık/kapalı algılayıcısı ve kabin aydınlatma durumu.
* **İstatistikler:** Kalan dahili disk alanı (`GB`), Toplam çalışma süresi (`saat`), Toplam tüketilen filament (`metre`), Nozul modeli.

---

### 6. 🏠 Home Assistant Entegrasyonu
Bileşen Home Assistant içerisinde tam teşekküllü bir cihaz olarak tanımlanır:
* **Sensörler (`sensor`):** Nozul, Yatak, Hazne sıcaklıkları, Katman, İlerleme, Baskı durumu, TVOC hava kalitesi, 4 adet IFS slot durumları, Kalan disk alanı vb.
* **Aydınlatma (`light`):** Kasa LED ışığını açıp kapatma.
* **Kamera (`camera`):** `camera.flashforge_ad5x_kamera` varlığı ile doğrudan Lovelace kartlarında canlı MJPEG yayın ve anlık önizleme.
* **Kontrol Butonları (`button`):** Home, Duraklat, Devam, Acil Durdurma, Oturumu Sıfırla (M602), Yazıcıyı Yeniden Başlat (M999).

---

## 🚀 Kurulum ve Çalıştırma

### A. Web Dashboard

1. **Gereksinimleri Yükleyin:**
   Python 3.9+ kurulu ortamda:
   ```bash
   pip install fastapi uvicorn jinja2 pydantic
   ```

2. **Paneli Başlatın:**
   ```bash
   python -m uvicorn flashforge_panel:app --host 0.0.0.0 --port 8000
   ```

3. **Erişim ve Ayarlar:**
   * Tarayıcınızdan `http://localhost:8000` (veya `http://<SUNUCU_IP>:8000`) adresini açın.
   * Sağ üstteki **⚙️ Ayarlar** butonuna tıklayarak Yazıcı IP adresinizi ve LAN şifrenizi (Check Code) girip kaydedin.

---

### B. Home Assistant

1. Projedeki `custom_components/flashforge_ad5x` klasörünü Home Assistant'ın `/config/custom_components/` dizini altına kopyalayın.
2. Home Assistant'ı yeniden başlatın.
3. **Ayarlar ➔ Cihazlar ve Hizmetler ➔ Entegrasyon Ekle** bölümünden **FlashForge AD5X** entegrasyonunu seçin ve IP adresinizi girerek kurulumu tamamlayın.
4. Detaylı Lovelace panelleri ve kart örnekleri için [`homeassistant_guide.md`](homeassistant_guide.md) kılavuzunu inceleyebilirsiniz.

---

## 📜 Desteklenen G-Kod ve Komut Referansı

| İşlem | Komut | Açıklama |
| :--- | :--- | :--- |
| **Login (Kontrol Al)** | `~M601 S1` | TCP port 8899 üzerinde oturum açar |
| **Logout (Serbest Bırak)** | `~M602` | Kilitli oturumu serbest bırakır |
| **Reboot (Yeniden Başlat)** | `~M999` / `~FIRMWARE_RESTART` | Anakart ve firmware yeniden başlatma |
| **Home (Sıfırlama)** | `~G28` | Tüm eksenleri referans konumuna gönderir |
| **Baskı Duraklat** | `~M25` | Devam eden baskıyı duraklatır |
| **Baskı Devam** | `~M24` | Duraklatılan baskıyı sürdürür |
| **Baskı İptal / Durdur** | `~M26` | Baskıyı sonlandırır |
| **Z-Ofset Ayarla** | `SET_GCODE_OFFSET Z_ADJUST={val} MOVE=1` + `M290 Z{val}` | Babystepping mikron düzeyinde Z ayarı |
| **Baskı Hızı Çarpanı** | `~M220 S{yüzde}` | Hızı dinamik olarak ayarlar (örn: `S120`) |
| **Fan Devri** | `~M106 S{0-255}` | Soğutma fanı gücünü ayarlar |
| **Kasa Işığı (LED)** | `~M146 r255 g255 b255 f0` / `~M146 r0 g0 b0 f0` | LED aç / kapat |
| **IFS Slot Seçimi** | `~T0`, `~T1`, `~T2`, `~T3` | İlgili filamente otomatik geçiş |

---

## 📄 Lisans
Bu proje açık kaynaklı olup topluluk kullanımına ve geliştirmelerine açıktır.
