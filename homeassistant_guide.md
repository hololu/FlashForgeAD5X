# Home Assistant & FlashForge AD5X Entegrasyon ve Arayüz Kılavuzu

Bu kılavuz, **CasaOS** (Docker) üzerinde çalışan **Home Assistant 2026.5.4** sisteminizde FlashForge AD5X (Adventurer 5M / 5M Pro) entegrasyonunu nasıl yapılandıracağınızı, arayüze Lovelace kartını nasıl ekleyeceğinizi ve karşılaştığınız **IFS (Port 8898 Connection Refused)** hatasını nasıl çözeceğinizi adım adım açıklamaktadır.

---

## 1. Lovelace Kontrol Paneli Düzenleme (HA 2026.5.4)

CasaOS veya Docker üzerinde çalışan Home Assistant sürümlerinde otomatik oluşturulan varsayılan kontrol paneli düzenlenemez. Paneli düzenlemek ve kart ekleyebilmek için aşağıdaki adımları sırasıyla uygulayın:

### Adım 1: Paneli Özelleştirilebilir Hale Getirme
1. Home Assistant sol menüsünden **Genel Bakış** (Overview) sayfasına gidin.
2. Sağ üst köşedeki **Üç Nokta (⋮)** simgesine tıklayın.
3. Açılan menüden **Paneli Düzenle (Edit Dashboard)** seçeneğine tıklayın.
4. Karşınıza *"Bu panel otomatik olarak güncelleniyor..."* şeklinde bir uyarı çıkacaktır. Burada sağ alttaki **"Denetimi Ele Al" (Take Control)** butonuna tıklayın.
5. Açılan onay penceresinde tekrar **"Denetimi Ele Al"** seçeneğini seçin. Artık paneliniz manuel düzenlemeye açılmıştır ve varsayılan bir "Görünüm (View)" otomatik olarak oluşturulmuştur.

### Adım 2: Özel Lovelace Kartını Ekleme
1. Panel düzenleme modundayken (ekranın üstünde "Kontrol Panelini Düzenle" başlığı ve sağ altta mavi bir **(+)** butonu göründüğünde), sağ alttaki **(+) Kart Ekle** butonuna tıklayın.
2. Açılan kart listesinin en altına kaydırın ve en alttaki **Manuel (Manual)** seçeneğini seçin.
3. Sol taraftaki kod editöründe yer alan tüm varsayılan satırları silin ve yerine aşağıdaki **YAML Kodunu** yapıştırın:

```yaml
type: vertical-stack
cards:
  - type: heading
    heading: FlashForge AD5X
    icon: mdi:printer-3d
  - type: grid
    columns: 2
    square: false
    cards:
      - type: gauge
        entity: sensor.flashforge_nozul_sicakligi
        name: Nozul Sıcaklığı
        min: 0
        max: 300
        needle: true
        severity:
          green: 190
          yellow: 240
          red: 270
      - type: gauge
        entity: sensor.flashforge_yatak_sicakligi
        name: Yatak Sıcaklığı
        min: 0
        max: 110
        needle: true
        severity:
          green: 50
          yellow: 70
          red: 90
  - type: sensor
    entity: sensor.flashforge_baski_ilerlemesi
    name: İlerleme Durumu
    graph: line
  - type: entities
    title: Yazıcı Bilgileri
    show_header_toggle: false
    entities:
      - entity: sensor.flashforge_yazici_durumu
        name: Durum
      - entity: sensor.flashforge_aktif_dosya
        name: Aktif Dosya
      - entity: sensor.flashforge_katman_orani
        name: Katman Oranı
      - entity: light.flashforge_kasa_isigi
        name: Kasa Işığı (LED)
  - type: entities
    title: Filament İstasyonu (IFS)
    show_header_toggle: false
    entities:
      - entity: sensor.flashforge_aktif_filament_slotu
        name: Aktif Yüklü Slot
      - entity: sensor.flashforge_filament_slot_1
      - entity: sensor.flashforge_filament_slot_2
      - entity: sensor.flashforge_filament_slot_3
      - entity: sensor.flashforge_filament_slot_4
  - type: horizontal-stack
    cards:
      - type: button
        entity: button.flashforge_tum_eksenleri_sifirla_home
        name: Home (Sıfırla)
        icon: mdi:home-map-marker
        tap_action:
          action: call-service
          service: button.press
          target:
            entity_id: button.flashforge_tum_eksenleri_sifirla_home
      - type: button
        entity: button.flashforge_baskiyi_duraklat_pause
        name: Duraklat
        icon: mdi:pause
        tap_action:
          action: call-service
          service: button.press
          target:
            entity_id: button.flashforge_baskiyi_duraklat_pause
      - type: button
        entity: button.flashforge_baskiya_devam_et_resume
        name: Devam Et
        icon: mdi:play
        tap_action:
          action: call-service
          service: button.press
          target:
            entity_id: button.flashforge_baskiya_devam_et_resume
      - type: button
        entity: button.flashforge_baskiyi_iptal_et_stop
        name: İptal Et
        icon: mdi:stop
        tap_action:
          action: call-service
          service: button.press
          target:
            entity_id: button.flashforge_baskiyi_iptal_et_stop
```

4. **Kaydet (Save)** butonuna tıklayın. Kart arayüzünüze yerleşecektir. Sağ üstten **Bitti (Done)** seçeneğine tıklayarak düzenleme modundan çıkın.

---

## 2. IFS (Port 8898 Connection Refused) Hatası ve Çözümü

Aldığınız `[Errno 111] Connection refused` hatası, yazıcının **8898 portunun tamamen kapalı olduğunu** ve gelen bağlantı isteklerini reddettiğini gösterir. TCP kontrol portu olan `8899` çalıştığı halde `8898` HTTP portunun reddetmesi ağ engellemesinden ziyade doğrudan yazıcı ayarlarından kaynaklanır.

Bu sorunu çözmek için aşağıdaki adımları uygulayın:

### 1. Adım: Yazıcı Ekranından "LAN Control" Ayarını Kontrol Edin
FlashForge Adventurer 5M serisinde web API'sinin (Port 8898) aktif olabilmesi için yazıcının dokunmatik ekranından LAN Kontrolünün açık olması gerekir:
1. Yazıcınızın dokunmatik ekranından **Ayarlar (Settings)** dişli çark simgesine dokunun.
2. **Ağ (Network / WiFi)** ayarlarına gidin.
3. Burada yer alan **LAN Control (Yerel Ağ Kontrolü)** seçeneğinin **AÇIK (ON)** olduğundan emin olun. 
4. Eğer zaten açıksa, kapatıp tekrar açın. Bu ayar açık olduğunda ekranda size **8 haneli bir şifre (Verification / LAN Code)** gösterecektir. Bu şifre Home Assistant'taki `check_code` ayarınızdır.

> [!IMPORTANT]
> Yazıcı ekranındaki **LAN Control** seçeneği kapalı olduğunda yazıcı sadece FlashPrint gibi uygulamalarla sınırlı iletişim kurar, ancak `http://{IP}:8898/detail` HTTP servisini tamamen kapatarak bağlantıyı reddeder (Connection Refused).

### 2. Adım: Şifre ve Seri Numarasını Doğrulayın
*   Home Assistant entegrasyon ayarlarında girdiğiniz **Seri Numarasının (Serial Number)** yazıcı etiketindekiyle birebir aynı olduğundan (büyük harflere dikkat edin) emin olun.
*   **LAN Modu Şifresinin** yazıcı ekranında görünen 8 haneli kod ile tam olarak uyuştuğundan emin olun.

### 3. Adım: Docker (CasaOS) Ağ Modunu Kontrol Edin (Eğer Sorun Devam Ederse)
Eğer yazıcıda LAN Control açık olduğu halde hala bu hatayı alıyorsanız:
*   CasaOS'ta Home Assistant konteynerinin ağ ayarlarını **Host Mode (Ana Makine Ağ Modu)** olarak yapılandırın. `Bridge` modunda Docker bazı port isteklerini engelleyebilir veya dışarıya yanlış IP ile yönlendirebilir. Ancak 8899 çalıştığı için bu ihtimal oldukça düşüktür; asıl neden büyük olasılıkla yazıcı üzerindeki LAN Control anahtarıdır.
