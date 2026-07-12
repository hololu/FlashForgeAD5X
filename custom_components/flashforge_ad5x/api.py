import asyncio
import logging
import json
import socket
import aiohttp
from datetime import datetime

_LOGGER = logging.getLogger(__name__)

class FlashForgeAPI:
    """FlashForge AD5X 3D Yazıcı API İstemcisi"""

    def __init__(self, host: str, port: int, serial: str = "", check_code: str = "", session: aiohttp.ClientSession = None):
        self.host = host
        self.port = port
        self.serial = serial
        self.check_code = check_code
        self.session = session

    async def async_send_command(self, cmd: str, timeout: float = 5.0) -> str:
        """Yazıcıya TCP soket üzerinden komut gönderir ve cevabı döndürür."""
        try:
            # Satır sonu karakterlerini kontrol et
            if not cmd.endswith("\r\n"):
                cmd += "\r\n"
                
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port), timeout=timeout
            )
        except Exception as e:
            _LOGGER.debug("TCP Bağlantı Hatası %s:%s - %s", self.host, self.port, str(e))
            return f"ERR:{e}"

        try:
            writer.write(cmd.encode("utf-8"))
            await writer.drain()

            data = bytearray()
            start_time = asyncio.get_event_loop().time()
            while True:
                elapsed = asyncio.get_event_loop().time() - start_time
                remaining = max(0.1, timeout - elapsed)
                if elapsed >= timeout:
                    break
                
                try:
                    chunk = await asyncio.wait_for(reader.read(4096), timeout=remaining)
                except asyncio.TimeoutError:
                    break
                
                if not chunk:
                    break
                data += chunk
                
                # ok\r\n veya CMD ERR gelince okumayı sonlandır
                if b"ok\r\n" in data or b"ERR:" in data or b"CMD ERR" in data:
                    break
                if len(data) > 65536:  # Güvenlik sınırı
                    break
            
            return data.decode("utf-8", errors="ignore")
        except Exception as e:
            _LOGGER.debug("TCP İletişim Hatası: %s", str(e))
            return f"ERR:{e}"
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def async_fetch_detail(self, timeout: float = 3.0) -> dict:
        """Yazıcının HTTP API (Port 8898) üzerinden detaylı filament bilgilerini çeker."""
        if not self.serial or not self.check_code:
            return {"error": "Seri Numarası veya LAN Kodu eksik"}

        url = f"http://{self.host}:8898/detail"
        headers = {
            "serialNumber": self.serial,
            "checkCode": self.check_code,
            "Content-Type": "application/json"
        }
        
        try:
            if self.session:
                async with self.session.post(url, data="{}", headers=headers, timeout=timeout) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    else:
                        return {"error": f"HTTP status {resp.status}"}
            else:
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, data="{}", headers=headers, timeout=timeout) as resp:
                        if resp.status == 200:
                            return await resp.json()
                        else:
                            return {"error": f"HTTP status {resp.status}"}
        except Exception as e:
            _LOGGER.debug("HTTP Detay API Hatası: %s", str(e))
            return {"error": str(e)}

    def parse_m119(self, text: str) -> dict:
        """~M119 komutunun çıktısını ayrıştırır."""
        out = {
            "machine_status": "UNKNOWN",
            "move_mode": "UNKNOWN",
            "current_file": "",
            "led": "?",
            "endstop_x": "?",
            "endstop_y": "?",
            "endstop_z": "?",
            "status_flags": "S:? L:? J:? F:?",
        }
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for line in lines:
            if line.startswith("MachineStatus:"):
                out["machine_status"] = line.split(":", 1)[1].strip()
            elif line.startswith("MoveMode:"):
                out["move_mode"] = line.split(":", 1)[1].strip()
            elif line.startswith("CurrentFile:"):
                out["current_file"] = line.split(":", 1)[1].strip()
            elif line.startswith("Status:"):
                out["status_flags"] = line.split(":", 1)[1].strip()
            elif "X-max:" in line:
                out["endstop_x"] = line.split("X-max:")[-1].strip()
            elif "Y-max:" in line:
                out["endstop_y"] = line.split("Y-max:")[-1].strip()
            elif "Z-min:" in line:
                out["endstop_z"] = line.split("Z-min:")[-1].strip()
            elif line.startswith("LED:"):
                out["led"] = line.replace("LED:", "").strip()
        return out

    def parse_m27(self, text: str) -> dict:
        """~M27 komutunun çıktısını ayrıştırır."""
        result = {"progress": 0, "layer": "0/0", "current_layer": 0, "total_layers": 0}
        try:
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            pct_line = next((line for line in lines if line.startswith("SD printing byte ")), "")
            layer_line = next((line for line in lines if line.startswith("Layer: ")), "")
            
            if pct_line:
                pct = pct_line.replace("SD printing byte ", "").replace("/100", "").strip()
                result["progress"] = int(pct) if pct.isdigit() else 0
            if layer_line:
                val = layer_line.replace("Layer: ", "").strip()
                result["layer"] = val
                if "/" in val:
                    parts = val.split("/")
                    if len(parts) == 2:
                        result["current_layer"] = int(parts[0]) if parts[0].isdigit() else 0
                        result["total_layers"] = int(parts[1]) if parts[1].isdigit() else 0
        except Exception:
            pass
        return result

    def parse_temperatures(self, text: str) -> dict:
        """~M105 komutunun çıktısını ayrıştırır (T0 ve Bed sıcaklıkları)."""
        out = {
            "t0_current": 0.0, "t0_target": 0.0,
            "bed_current": 0.0, "bed_target": 0.0
        }
        parts = text.split()
        for part in parts:
            if part.startswith("T0:"):
                temp_vals = part[3:].split("/")
                if len(temp_vals) == 2:
                    try:
                        out["t0_current"] = float(temp_vals[0])
                        out["t0_target"] = float(temp_vals[1])
                    except ValueError:
                        pass
            elif part.startswith("B:"):
                temp_vals = part[2:].split("/")
                if len(temp_vals) == 2:
                    try:
                        out["bed_current"] = float(temp_vals[0])
                        out["bed_target"] = float(temp_vals[1])
                    except ValueError:
                        pass
        return out

    async def async_get_data(self) -> dict:
        """Tüm yazıcı bilgilerini çeker ve tek bir sözlük yapısında birleştirir."""
        raw_m119 = await self.async_send_command("~M119\r\n")
        
        # Eğer ilk TCP komutu başarısızsa printer offline kabul edilir.
        if "ERR:" in raw_m119:
            return {
                "online": False,
                "machine_status": "OFFLINE",
                "move_mode": "UNKNOWN",
                "current_file": "",
                "led": "?",
                "endstop_x": "?",
                "endstop_y": "?",
                "endstop_z": "?",
                "status_flags": "S:? L:? J:? F:?",
                "progress": 0,
                "layer": "0/0",
                "current_layer": 0,
                "total_layers": 0,
                "t0_current": 0.0,
                "t0_target": 0.0,
                "bed_current": 0.0,
                "bed_target": 0.0,
                "filament_info": None,
                "updated_at": datetime.now().isoformat()
            }

        raw_m27 = await self.async_send_command("~M27\r\n")
        raw_m105 = await self.async_send_command("~M105\r\n")

        m119_data = self.parse_m119(raw_m119)
        m27_data = self.parse_m27(raw_m27)
        m105_data = self.parse_temperatures(raw_m105)

        detail_data = {}
        if self.serial and self.check_code:
            detail_data = await self.async_fetch_detail()

        filament_info = detail_data.get("matlStationInfo") if isinstance(detail_data, dict) else None

        data = {
            "online": True,
            "machine_status": m119_data["machine_status"],
            "move_mode": m119_data["move_mode"],
            "current_file": m119_data["current_file"],
            "led": m119_data["led"],
            "endstop_x": m119_data["endstop_x"],
            "endstop_y": m119_data["endstop_y"],
            "endstop_z": m119_data["endstop_z"],
            "status_flags": m119_data["status_flags"],
            "progress": m27_data["progress"],
            "layer": m27_data["layer"],
            "current_layer": m27_data["current_layer"],
            "total_layers": m27_data["total_layers"],
            "t0_current": m105_data["t0_current"],
            "t0_target": m105_data["t0_target"],
            "bed_current": m105_data["bed_current"],
            "bed_target": m105_data["bed_target"],
            "filament_info": filament_info,
            "updated_at": datetime.now().isoformat()
        }
        return data
