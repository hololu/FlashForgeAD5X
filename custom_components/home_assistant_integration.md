# FlashForge AD5X Home Assistant Entegrasyonu

Bu entegrasyon, FlashForge AD5X (Adventurer 5M / 5M Pro) 3D yazıcınızı Home Assistant sisteminize doğrudan bağlamanıza olanak tanır. Python tabanlı kontrol panelinde (`flashforge_panel.py`) kullanılan tüm TCP soket ve HTTP detay API yapısı, Home Assistant mimarisine uygun (asenkron, verimli ve cihaz bazlı gruplanmış) bir **Custom Component (Özel Entegrasyon)** olarak geliştirilmiştir.

## Öne Çıkan Özellikler

1. **Tamamen Asenkron Çalışma:** Home Assistant'ın ana olay döngüsünü engellemeyecek şekilde `asyncio` ve `aiohttp` kütüphaneleri kullanılmıştır.
2. **Tek Cihaz Altında Gruplama:** Entegrasyon tarafından oluşturulan tüm sensörler, butonlar ve ışık kontrolleri Home Assistant arayüzünde tek bir **FlashForge AD5X** cihazı altında toplanır.
3. **Kullanıcı Dostu Kurulum Arayüzü (Config Flow):** YAML dosyası düzenleme ihtiyacı olmadan, Home Assistant arayüzünden IP adresi, port, seri numarası ve LAN kodunu girerek kolayca kurulum yapabilirsiniz.
4. **Çoklu Dil Desteği:** Türkçe ve İngilizce dilleri için tam çeviri dosyaları eklenmiştir.
5. **Veri Koordinatörü (DataUpdateCoordinator):** Yazıcıdan veri çekme işlemi tek bir koordinatör üzerinden yapılır; böylece tüm sensörler tek bir sorguda güncellenir ve yazıcı gereksiz ağ trafiği ile yorulmaz.

---

## Dosya Yapısı

Entegrasyon için oluşturulan tüm dosyalar [custom_components/flashforge_ad5x/](file:///D:/Calismalar/ai/Pythone/flashforge/custom_components/flashforge_ad5x) dizininde yer almaktadır:

*   [__init__.py](file:///D:/Calismalar/ai/Pythone/flashforge/custom_components/flashforge_ad5x/__init__.py): Entegrasyonun başlatılması, veri koordinatörünün (`DataUpdateCoordinator`) kurulması ve platformların yüklenmesini yönetir.
*   [api.py](file:///D:/Calismalar/ai/Pythone/flashforge/custom_components/flashforge_ad5x/api.py): TCP soket haberleşmesini (`~M119`, `~M27`, `~M105`) ve `/detail` HTTP API isteklerini asenkron gerçekleştiren [FlashForgeAPI](file:///D:/Calismalar/ai/Pythone/flashforge/custom_components/flashforge_ad5x/api.py#L9) sınıfını barındırır.
*   [const.py](file:///D:/Calismalar/ai/Pythone/flashforge/custom_components/flashforge_ad5x/const.py): Entegrasyon genelinde kullanılan sabitleri tanımlar.
*   [config_flow.py](file:///D:/Calismalar/ai/Pythone/flashforge/custom_components/flashforge_ad5x/config_flow.py): HA Entegrasyonlar sayfasındaki kurulum sihirbazını yöneten [FlashForgeConfigFlow](file:///D:/Calismalar/ai/Pythone/flashforge/custom_components/flashforge_ad5x/config_flow.py#L10) sınıfını barındırır. Bağlantıyı otomatik test eder.
*   [sensor.py](file:///D:/Calismalar/ai/Pythone/flashforge/custom_components/flashforge_ad5x/sensor.py): Yazıcı sıcaklıkları, baskı durumu, katman bilgileri ve IFS filament slot bilgilerini sunan sensörleri tanımlar.
*   [button.py](file:///D:/Calismalar/ai/Pythone/flashforge/custom_components/flashforge_ad5x/button.py): Duraklat, Devam Et, Durdur ve Home (Sıfırla) işlemlerini gerçekleştiren butonları tanımlar.
*   [light.py](file:///D:/Calismalar/ai/Pythone/flashforge/custom_components/flashforge_ad5x/light.py): Yazıcı kasa ışığını (LED) kontrol edebilmeniz için ışık varlığını tanımlar.
*   [strings.json](file:///D:/Calismalar/ai/Pythone/flashforge/custom_components/flashforge_ad5x/strings.json): HA sisteminde kullanılacak temel dil şablonu.
*   [translations/tr.json](file:///D:/Calismalar/ai/Pythone/flashforge/custom_components/flashforge_ad5x/translations/tr.json): Türkçe kurulum ve arayüz çevirileri.
*   [translations/en.json](file:///D:/Calismalar/ai/Pythone/flashforge/custom_components/flashforge_ad5x/translations/en.json): İngilizce kurulum ve arayüz çevirileri.
*   [manifest.json](file:///D:/Calismalar/ai/Pythone/flashforge/custom_components/flashforge_ad5x/manifest.json): Home Assistant için entegrasyonun meta verilerini ve gereksinimlerini belirten dosya.

---

## Sunulan Varlıklar (Entities) ve Öznitelikler

Entegrasyon kurulduğunda aşağıdaki varlıklar oluşturulur:

| Varlık Adı | Türü | Açıklama / Öznitelikler |
| :--- | :--- | :--- |
| **Yazıcı Durumu** | Sensor | Yazıcının güncel durumu (Örn: `READY`, `PAUSED`, `BUILDING_FROM_SD`).<br>*Öznitelikler: hareket_modu, durum_bayraklari, endstop_x, endstop_y, endstop_z* |
| **Nozul Sıcaklığı** | Sensor | Nozulun güncel sıcaklığı (°C).<br>*Öznitelikler: hedef_sicaklik* |
| **Yatak Sıcaklığı** | Sensor | Isıtıcı yatağın güncel sıcaklığı (°C).<br>*Öznitelikler: hedef_sicaklik* |
| **Baskı İlerlemesi** | Sensor | Yüzde (%) cinsinden baskı ilerleme durumu. |
| **Aktif Dosya** | Sensor | Baskısı yapılan güncel dosya adı. |
| **Mevcut / Toplam Katman** | Sensor | Baskıdaki katman bilgileri (Örn: 12, 120). |
| **Katman Oranı** | Sensor | String formatında katman bilgisi (Örn: `12/120`). |
| **Filament Slot 1-4** | Sensor | IFS (Filament İstasyonu) slotlarındaki filament adı (Örn: `PLA`, `Empty`).<br>*Öznitelikler: has_filament, renk (hex), aktif_yuklu* |
| **Aktif Filament Slotu** | Sensor | Şu an yüklü ve aktif olan filament slot numarası (Örn: `1`, `2`, `Yok`). |
| **Kasa Işığı** | Light | Yazıcı içi LED ışığını açıp kapatabileceğiniz anahtar. |
| **Home / Pause / Resume / Stop** | Button | Yazıcıyı kontrol etmek için tetikleyici butonlar. |

---

## Kurulum Adımları

Entegrasyonu Home Assistant'a eklemek için şu adımları izleyin:

1.  **Klasörü Kopyalayın:**
    Workspace'de oluşturulan `custom_components/flashforge_ad5x` klasörünü, Home Assistant kurulumunuzun `config/custom_components/` dizini altına kopyalayın (Eğer `custom_components` klasörü yoksa kendiniz oluşturun).
    
    *Klasör yapısı şu şekilde görünmelidir:*
    ```text
    homeassistant/
    └── config/
        └── custom_components/
            └── flashforge_ad5x/
                ├── __init__.py
                ├── api.py
                ├── const.py
                ├── ...
    ```

2.  **Home Assistant'ı Yeniden Başlatın:**
    Yeni özel entegrasyonun algılanması için Home Assistant arayüzünden **Geliştirici Araçları > YAML > Yeniden Başlat** (veya HA sunucusunu tamamen yeniden başlatın) yolunu izleyin.

3.  **Entegrasyonu Arayüzden Ekleyin:**
    *   Home Assistant arayüzünde **Ayarlar > Cihazlar ve Hizmetler** bölümüne gidin.
    *   Sağ alttaki **Entegrasyon Ekle** butonuna tıklayın.
    *   Arama kutusuna **`FlashForge AD5X`** yazın ve seçin.
    *   Açılan kurulum penceresinde:
        *   **IP Adresi:** Yazıcınızın yerel ağdaki IP adresini yazın.
        *   **Port:** Varsayılan `8899` olarak bırakın.
        *   **Seri Numarası (Opsiyonel):** Filament istasyonu (IFS) bilgilerini çekmek istiyorsanız yazıcının seri numarasını girin.
        *   **LAN Modu Şifresi (Opsiyonel):** Filament istasyonu (IFS) bilgilerini çekmek istiyorsanız yazıcının ekranından alacağınız 8 haneli LAN şifresini girin.
    *   **Gönder** butonuna tıkladığınızda entegrasyon yazıcınıza bağlanacak, doğrulayacak ve cihazınızı ekleyecektir.

---

> [!NOTE]
> Seri Numarası ve LAN Kodu girilmezse, entegrasyon sadece TCP komutları ile sıcaklık, ilerleme ve durum bilgilerini çeker. Filament istasyonu (IFS) slot sensörleri ise "Pasif" durumda kalacaktır.
