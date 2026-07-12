# FlashForge AD5X Web Dashboard & Home Assistant Entegrasyonu

Bu proje, **FlashForge AD5X (Adventurer 5M / 5M Pro)** 3D yazıcıları için tasarlanmış modern bir **Web Kontrol Paneli (Web Dashboard)** ve **Home Assistant Özel Bileşeni (Custom Component)** içermektedir.

Yazıcının TCP kontrol portu (8899) ve HTTP detay/sensör portu (8898) protokolleri tersine mühendislik yöntemleriyle çözümlenerek; izleme, kontrol ve baskı sırasındaki ince ayarların (Live Tuning) yönetilmesi tek bir çatı altında birleştirilmiştir.

---
![Ana Ekran](https://git.mustafaozkaya.tr/hololu/FlashForgeAD5X/raw/commit/313899c7246f95a50b7f6c768c6b9e531ceb58f4/ad5x/flashforge_ad5x.jpg)
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

### A. Web Dashboard Paket Kurulumu (PEP 668 Çözümü)

Modern Linux dağıtımlarında (Debian, Ubuntu, Raspberry Pi OS) sistem kararlılığını korumak için doğrudan global paket yükleme sınırlandırılmıştır. Projeyi ayağa kaldırmak için aşağıdaki iki yöntemden birini seçebilirsiniz:

#### Yöntem 1: Sanal Ortam (Virtual Environment) Oluşturma *(Önerilen & En Güvenli)*
Sanal ortam oluşturarak bağımlılıkları sistemden izole eder ve güvenli bir çalışma alanı sağlarsınız:

1. **Sanal ortamı oluşturun:**
   ```bash
   python3 -m venv venv
   ```
   *(Eğer venv paketi eksikse: `sudo apt install python3-venv`)*

2. **Sanal ortamı aktif hale getirin:**
   ```bash
   source venv/bin/activate
   ```

3. **Gerekli paketleri kurun:**
   ```bash
   pip install fastapi uvicorn jinja2 pydantic
   ```

#### Yöntem 2: Global Kurulum (Hızlı Yol)
Paketleri sanal ortam kullanmadan doğrudan sisteme yüklemek istiyorsanız `--break-system-packages` bayrağını kullanabilirsiniz:
```bash
pip install fastapi uvicorn jinja2 pydantic --break-system-packages
```

---

### B. Web Dashboard Sunucusunu Başlatma

1. **Sunucuyu Çalıştırın:**
   * Sanal ortam kullanıyorsanız ortamın aktif olduğundan emin olun (`source venv/bin/activate`).
   * Ardından sunucuyu başlatın:
     ```bash
     python3 -m uvicorn flashforge_panel:app --host 0.0.0.0 --port 8000 --reload
     ```
2. **Arayüze Erişim:**
   Tarayıcınızdan `http://localhost:8000` (veya ağdaki cihazlar için `http://<cihaz_ip>:8000`) adresine girerek kontrol paneline erişebilirsiniz.

---

### C. Sistem Servisi (Systemd) Olarak Yapılandırma (Linux / Raspberry Pi)

Uygulamanın cihaz her açıldığında arka planda otomatik olarak bir servis olarak başlamasını istiyorsanız:

1. **Servis Yapılandırma Dosyasını Açın:**
   ```bash
   sudo nano /etc/systemd/system/flashforge.service
   ```

2. **Aşağıdaki Kodları Yapıştırın ve Kaydedin:**
   *(Kullanıcı adınızı ve klasör yollarını kendi sisteminize göre güncellemeyi unutmayın)*
   ```ini
   [Unit]
   Description=FlashForge AD5X Web Dashboard Servisi
   After=network.target

   [Service]
   Type=simple
   User=ololu
   WorkingDirectory=/home/ololu/calismalar/ai/Python/flashforge
   ExecStart=/home/ololu/calismalar/ai/Python/flashforge/venv/bin/python -m uvicorn flashforge_panel:app --host 0.0.0.0 --port 8000
   Restart=always
   RestartSec=5

   [Install]
   WantedBy=multi-user.target
   ```

3. **Servisi Aktifleştirin ve Başlatın:**
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable flashforge.service
   sudo systemctl start flashforge.service
   ```

4. **Durum ve Günlük Takibi:**
   * Durum sorgulama: `sudo systemctl status flashforge.service`
   * Canlı log takibi: `journalctl -u flashforge.service -f`

---

### D. Home Assistant Entegrasyonu Kurulumu

1. `custom_components/flashforge_ad5x` klasörünü Home Assistant kurulumunuzun içindeki `/config/custom_components/` dizinine kopyalayın.
2. Home Assistant sunucunuzu yeniden başlatın.
3. HA arayüzünden **Ayarlar -> Cihazlar & Hizmetler -> Entegrasyon Ekle** kısmından **FlashForge AD5X** entegrasyonunu arayıp ekleyin.
4. Yazıcınızın IP adresini, Portunu (8899), Seri Numarasını ve LAN modundaki şifresini (Check Code) girerek kurulumu tamamlayın.

---

## 🛠️ İnce Ayar (Tuning) Komut Referansları
Dashboard üzerinden gönderilen ve arka planda desteklenen G-kod karşılıkları:

* **Z-Ofset Babystepping:** `SET_GCODE_OFFSET Z_ADJUST={değer} MOVE=1` ve `M290 Z{değer}` komutları ardışık gönderilerek hem Klipper hem Marlin uyumluluğu sağlanır.
* **Baskı Hızı Çarpanı (Feedrate):** `M220 S{yüzde}` komutu gönderilir. Sürgü adımları %5 hassasiyetle çalışır.
* **Soğutma Fanı Gücü:** `%` olarak girilen değer `S0` ile `S255` arasına ölçeklenerek `M106 S{değer}` şeklinde gönderilir.
* **Kabin LED Kontrolü:** LED açma için `M146 r255 g255 b255 f0`, kapatma için `M146 r0 g0 b0 f0` komutları kullanılır.
