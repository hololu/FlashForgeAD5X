"""
FlashForge AD5X Web Dashboard & Camera Proxy Backend
Author: Mustafa Özkaya (hOLOlu)
Repository: https://git.mustafaozkaya.tr/hololu/FlashForgeAD5X
Copyright (c) 2026 Mustafa Özkaya. All rights reserved.
License: MIT
"""

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import Optional
import asyncio
import socket
import os
import json
import urllib.request
import urllib.parse
import stat
import threading
from collections import deque
from datetime import datetime
import zipfile
import io
import re
import xml.etree.ElementTree as ET
import shutil
import subprocess
import time
from PIL import Image

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")

PRINTER_HOST = "192.168.1.19"
PRINTER_PORT = 8899
RECONNECT_DELAY = 3.0
WATCH_INTERVAL = 2.0
PRINTER_SERIAL = "SNMQQF9301246"
PRINTER_CHECK_CODE = "dd89422a"

def load_config():
    global PRINTER_HOST, PRINTER_PORT, PRINTER_SERIAL, PRINTER_CHECK_CODE, RECONNECT_DELAY, WATCH_INTERVAL
    PRINTER_HOST = os.getenv("FLASHFORGE_HOST", "192.168.1.19")
    PRINTER_PORT = int(os.getenv("FLASHFORGE_PORT", "8899"))
    RECONNECT_DELAY = float(os.getenv("FLASHFORGE_RECONNECT_DELAY", "3"))
    WATCH_INTERVAL = float(os.getenv("FLASHFORGE_WATCH_INTERVAL", "2"))
    PRINTER_SERIAL = os.getenv("FLASHFORGE_SERIAL", "SNMQQF9301246")
    PRINTER_CHECK_CODE = os.getenv("FLASHFORGE_CHECK_CODE", "dd89422a")

    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                data = json.load(f)
                PRINTER_HOST = data.get("host", PRINTER_HOST)
                PRINTER_PORT = int(data.get("port", PRINTER_PORT))
                PRINTER_SERIAL = data.get("serial", PRINTER_SERIAL)
                PRINTER_CHECK_CODE = data.get("check_code", PRINTER_CHECK_CODE)
                # Load persistent live tuning variables if present
                if "speed_factor" in data:
                    last_status["speed_factor"] = data["speed_factor"]
                if "fan_speed" in data:
                    last_status["fan_speed"] = data["fan_speed"]
                if "z_offset" in data:
                    last_status["z_offset"] = data["z_offset"]
                # Load persistent timelapse preferences
                if "timelapse_mode" in data:
                    last_status["timelapse_mode"] = data["timelapse_mode"]
                if "timelapse_interval" in data:
                    last_status["timelapse_interval"] = int(data["timelapse_interval"])
        except Exception as e:
            print(f"Error loading config.json: {e}")

def save_config(host, port, serial, check_code, timelapse_mode=None, timelapse_interval=None):
    global PRINTER_HOST, PRINTER_PORT, PRINTER_SERIAL, PRINTER_CHECK_CODE
    PRINTER_HOST = host
    PRINTER_PORT = int(port)
    PRINTER_SERIAL = serial
    PRINTER_CHECK_CODE = check_code
    
    existing_data = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                existing_data = json.load(f)
        except Exception:
            pass
            
    existing_data.update({
        "host": host,
        "port": port,
        "serial": serial,
        "check_code": check_code,
        "speed_factor": last_status.get("speed_factor", 100),
        "fan_speed": last_status.get("fan_speed", 0),
        "z_offset": last_status.get("z_offset", 0.0),
        "timelapse_mode": timelapse_mode if timelapse_mode is not None else existing_data.get("timelapse_mode", "hybrid"),
        "timelapse_interval": int(timelapse_interval) if timelapse_interval is not None else int(existing_data.get("timelapse_interval", 10))
    })
    
    if timelapse_mode and 'timelapse_manager' in globals():
        timelapse_manager.capture_mode = timelapse_mode
    if timelapse_interval and 'timelapse_manager' in globals():
        timelapse_manager.capture_interval = int(timelapse_interval)
    
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(existing_data, f, indent=4)
    except Exception as e:
        print(f"Error saving config.json: {e}")

def save_tuning_config():
    existing_data = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                existing_data = json.load(f)
        except Exception:
            pass
            
    existing_data.update({
        "speed_factor": last_status.get("speed_factor", 100),
        "fan_speed": last_status.get("fan_speed", 0),
        "z_offset": last_status.get("z_offset", 0.0)
    })
    
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(existing_data, f, indent=4)
    except Exception as e:
        print(f"Error saving tuning config to config.json: {e}")


def format_bytes(size: int) -> str:
    """Formats file size into human-readable string (KB, MB)."""
    if not size or size <= 0:
        return "0 B"
    num = float(size)
    for unit in ["B", "KB", "MB", "GB"]:
        if num < 1024.0:
            return f"{num:.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} TB"


def get_local_ip_subnets() -> list:
    """Detects active IPv4 subnets from system network interfaces."""
    subnets = set()
    try:
        hostname = socket.gethostname()
        for ip in socket.gethostbyname_ex(hostname)[2]:
            if not ip.startswith("127.") and not ip.startswith("169.254."):
                parts = ip.split(".")
                if len(parts) == 4:
                    subnets.add(f"{parts[0]}.{parts[1]}.{parts[2]}")
    except Exception:
        pass

    # Also include the subnet of configured PRINTER_HOST
    if PRINTER_HOST:
        parts = PRINTER_HOST.split(".")
        if len(parts) == 4 and not PRINTER_HOST.startswith("127."):
            subnets.add(f"{parts[0]}.{parts[1]}.{parts[2]}")

    if not subnets:
        subnets.add("192.168.1")
    return sorted(list(subnets))


async def probe_printer_ip(ip: str, timeout: float = 0.8) -> Optional[dict]:
    """Probes an IP for FlashForge printer service (port 8899)."""
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, PRINTER_PORT),
            timeout=timeout
        )
    except Exception:
        return None

    info = {
        "ip": ip,
        "port": PRINTER_PORT,
        "machine_type": "FlashForge 3D Printer",
        "machine_name": "",
        "serial": "",
        "firmware": "",
        "status": "ONLINE",
        "current_file": "",
        "mac": ""
    }

    try:
        # Query M115 (Machine info)
        writer.write(b"~M115\r\n")
        await writer.drain()
        data_m115 = await asyncio.wait_for(reader.read(2048), timeout=1.2)
        text_m115 = data_m115.decode("utf-8", errors="ignore")
        for line in text_m115.splitlines():
            line = line.strip()
            if line.startswith("Machine Type:"):
                info["machine_type"] = line.split(":", 1)[1].strip()
            elif line.startswith("Machine Name:"):
                info["machine_name"] = line.split(":", 1)[1].strip()
            elif line.startswith("Firmware:"):
                info["firmware"] = line.split(":", 1)[1].strip()
            elif line.startswith("SN:"):
                info["serial"] = line.split(":", 1)[1].strip()
            elif line.startswith("Mac Address:"):
                info["mac"] = line.split(":", 1)[1].strip()

        # Query M119 (Status & file)
        writer.write(b"~M119\r\n")
        await writer.drain()
        data_m119 = await asyncio.wait_for(reader.read(2048), timeout=1.2)
        text_m119 = data_m119.decode("utf-8", errors="ignore")
        for line in text_m119.splitlines():
            line = line.strip()
            if line.startswith("MachineStatus:"):
                info["status"] = line.split(":", 1)[1].strip()
            elif line.startswith("CurrentFile:"):
                info["current_file"] = line.split(":", 1)[1].strip()
    except Exception:
        pass
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass

    return info


async def discover_printers_on_network(custom_subnet: Optional[str] = None) -> list:
    """Scans local subnet(s) concurrently to discover FlashForge printers."""
    subnets = [custom_subnet] if custom_subnet else get_local_ip_subnets()
    candidates = []
    for sub in subnets:
        for i in range(1, 255):
            candidates.append(f"{sub}.{i}")

    sem = asyncio.Semaphore(75)

    async def _worker(ip):
        async with sem:
            return await probe_printer_ip(ip, timeout=0.8)

    tasks = [_worker(ip) for ip in candidates]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    found = [r for r in results if isinstance(r, dict) and r.get("ip")]
    return found


LOCAL_TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
TEMPLATES_DIR = LOCAL_TEMPLATES_DIR if os.path.exists(LOCAL_TEMPLATES_DIR) else "/tmp/flashforge-panel/templates"

app = FastAPI(title="FlashForge AD5X Panel")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

status_history = deque(maxlen=200)
last_status = {
    "machine_status": "UNKNOWN",
    "move_mode": "UNKNOWN",
    "current_file": "",
    "progress": 0,
    "layer": "0/0",
    "temperatures": {"t0": "0/0", "t1": "0/0", "bed": "0/0"},
    "endstop": {"x": "?", "y": "?", "z": "?"},
    "led": "?",
    "status_flags": "S:? L:? J:? F:?",
    "updated_at": None,
    "error": None,
    "is_paused": False,
    "is_error": False,
    "is_completed": False,
    "platform_clean_needed": False,
    "pause_reason": None,
    "printer_error": None,
    "filament_info": None,
    # Live Tuning variables
    "speed_factor": 100,
    "fan_speed": 0,
    "z_offset": 0.0,
    # HTTP detail API values
    "chamber_temp": 0.0,
    "chamber_target_temp": 0.0,
    "chamber_fan_speed": 0,
    "cooling_fan_speed": 0,
    "cooling_fan_left_speed": 0,
    "door_status": "unknown",
    "light_status": "unknown",
    "firmware_version": "",
    "cumulative_print_time": 0,
    "cumulative_filament": 0.0,
    "remaining_disk_space": 0.0,
    "estimated_time": 0.0,
    "print_duration": 0,
    "nozzle_model": "",
    "tvoc": 0,
    "z_axis_compensation": 0.0,
    "ip_addr": "",
    "mac_addr": "",
    "detail_raw": {},
}

# Load configuration on module import (called after last_status is defined)
load_config()

watch_task = None
lock = asyncio.Lock()


def socket_recv_until(sock: socket.socket, markers: tuple[bytes, ...], timeout: float = 8):
    sock.settimeout(timeout)
    data = bytearray()
    start = __import__("time").time()
    while True:
        try:
            chunk = sock.recv(4096)
        except socket.timeout:
            break
        if not chunk:
            break
        data += chunk
        if any(m in data for m in markers):
            break
        if __import__("time").time() - start > timeout:
            break
    return bytes(data)


async def send_command(cmd: bytes, markers=(b"ok\r\n",)) -> bytes:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _send_command_sync, cmd, markers)


def _send_command_sync(cmd: bytes, markers=(b"ok\r\n",)) -> bytes:
    try:
        with socket.create_connection((PRINTER_HOST, PRINTER_PORT), timeout=8) as s:
            s.settimeout(8)
            
            # FlashForge requires ~M601 S1 to take control before sending control commands.
            # Queries (M119, M27, M105) or session commands don't need it.
            cmd_str = cmd.decode("utf-8", errors="ignore").strip()
            first_line = next((line.strip() for line in cmd_str.splitlines() if line.strip()), "")
            is_query = any(q in first_line for q in ["M119", "M27", "M105", "M601", "M602"])
            
            if not is_query:
                # Login/take control
                s.sendall(b"~M601 S1\r\n")
                socket_recv_until(s, markers=(b"ok\r\n", b"Control", b"CMD"), timeout=2)
                
            s.sendall(cmd)
            res = socket_recv_until(s, markers=markers, timeout=8)
            
            if not is_query:
                # Logout/release control
                s.sendall(b"~M602\r\n")
                socket_recv_until(s, markers=(b"ok\r\n",), timeout=1)
                
            return res
    except Exception as e:
        return f"ERR:{e}".encode()


def parse_m119(text: str):
    out = {
        "machine_status": "UNKNOWN",
        "move_mode": "UNKNOWN",
        "current_file": "",
        "progress": 0,
        "layer": "0/0",
        "endstop": {"x": "?", "y": "?", "z": "?"},
        "led": "?",
        "status_flags": "S:? L:? J:? F:?",
        "temperatures": {"t0": "0/0", "1": "0/0", "bed": "0/0"},
        "extra_messages": [],
        "detected_error": None
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
        elif line.endswith("ok"):
            pass
        elif any(line.upper().startswith(k) for k in ["ERROR:", "ERR:", "ERRORCODE:", "ERRORMSG:", "FAULT:"]):
            out["detected_error"] = line.split(":", 1)[1].strip() if ":" in line else line
        elif any(line.upper().startswith(k) for k in ["WARNING:", "WARN:", "ALARM:", "REASON:"]):
            out["extra_messages"].append(line.split(":", 1)[1].strip() if ":" in line else line)
        elif ":" in line and any(k in line for k in ["X-max", "Y-max", "Z-min", "LED"]):
            if "X-max:" in line:
                out["endstop"]["x"] = line.split("X-max:")[-1].strip()
            if "Y-max:" in line:
                out["endstop"]["y"] = line.split("Y-max:")[-1].strip()
            if "Z-min:" in line:
                out["endstop"]["z"] = line.split("Z-min:")[-1].strip()
            if line.startswith("LED:"):
                out["led"] = line.replace("LED:", "").strip()

    if out["machine_status"] in ["ERROR", "STOPPED"] and not out["detected_error"]:
        out["detected_error"] = f"Yazıcı durumu: {out['machine_status']}"

    return out


def parse_m27(text: str):
    result = {"progress": 0, "layer": "0/0"}
    try:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        pct_line = next((line for line in lines if line.startswith("SD printing byte ")), "")
        layer_line = next((line for line in lines if line.startswith("Layer: ")), "")
        if pct_line:
            pct = pct_line.replace("SD printing byte ", "").replace("/100", "").strip()
            result["progress"] = int(pct) if pct.isdigit() else 0
        if layer_line:
            result["layer"] = layer_line.replace("Layer: ", "").strip()
    except Exception:
        pass
    return result


def parse_temperatures(text: str):
    out = {"t0": "0/0", "t1": "0/0", "bed": "0/0"}
    for part in text.split():
        if part.startswith("T0:"):
            out["t0"] = part[3:]
        elif part.startswith("T1:"):
            out["t1"] = part[3:]
        elif part.startswith("B:"):
            out["bed"] = part[2:]
    return out


def _fetch_http_detail_sync(host, serial, check_code):
    import urllib.request
    import json

    serial = (serial or "").strip()
    check_code = (check_code or "").strip()

    url = f"http://{host}:8898/detail"

    headers = {
        "serialNumber": serial,
        "serialNo": serial,
        "checkCode": check_code,
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) FlashForge-Panel/1.0"
    }

    payload = json.dumps({
        "serialNumber": serial,
        "serialNo": serial,
        "checkCode": check_code
    }).encode("utf-8")

    # Strategy 1: Try POST request
    try:
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=4) as response:
            resp_text = response.read().decode("utf-8", errors="ignore").strip()
            if resp_text.startswith("{") or resp_text.startswith("["):
                return json.loads(resp_text)
            elif "orcaServer" in resp_text or "debug" in resp_text:
                print(f"orcaServer C++ debug response: {resp_text}")
    except Exception as e:
        print(f"POST /detail failed: {e}")

    # Strategy 2: Fallback to GET request with query params & headers
    try:
        get_url = f"http://{host}:8898/detail?serialNo={serial}&checkCode={check_code}"
        req_get = urllib.request.Request(get_url, headers=headers, method="GET")
        with urllib.request.urlopen(req_get, timeout=4) as response:
            resp_text = response.read().decode("utf-8", errors="ignore").strip()
            if resp_text.startswith("{") or resp_text.startswith("["):
                return json.loads(resp_text)
            else:
                return {"error": f"Yazıcı Web Sunucusu (orcaServer.cpp) Hata Yanıtı: {resp_text}"}
    except Exception as e:
        print(f"GET /detail failed: {e}")

    return {"error": "Yazıcı detay API (8898) geçersiz yanıt döndürdü. Seri No ve LAN kodunu kontrol edin."}


async def refresh_once():
    raw_m119 = await send_command(b"~M119\r\n")
    raw_m27 = await send_command(b"~M27\r\n")
    raw_m105 = await send_command(b"~M105\r\n")
    m119_text = raw_m119.decode("utf-8", errors="ignore") if isinstance(raw_m119, bytes) else str(raw_m119)
    m27_text = raw_m27.decode("utf-8", errors="ignore") if isinstance(raw_m27, bytes) else str(raw_m27)
    m105_text = raw_m105.decode("utf-8", errors="ignore") if isinstance(raw_m105, bytes) else str(raw_m105)

    parsed_m119 = parse_m119(m119_text)
    parsed_m27 = parse_m27(m27_text)
    parsed_m105 = parse_temperatures(m105_text)

    filament_info = None
    filament_info_error = None
    detail_dict = {}
    if not PRINTER_SERIAL or not PRINTER_CHECK_CODE:
        filament_info_error = "Çevre değişkenleri eksik. Lütfen FLASHFORGE_SERIAL ve FLASHFORGE_CHECK_CODE değişkenlerini tanımlayın."
    else:
        try:
            loop = asyncio.get_event_loop()
            detail_data = await loop.run_in_executor(
                None, _fetch_http_detail_sync, PRINTER_HOST, PRINTER_SERIAL, PRINTER_CHECK_CODE
            )

            if isinstance(detail_data, dict):
                if "detail" in detail_data and isinstance(detail_data["detail"], dict):
                    detail_dict = detail_data["detail"]
                else:
                    detail_dict = detail_data

            filament_info = detail_dict.get("matlStationInfo")

            # Save raw payload to detail_debug.json for inspection
            debug_file = os.path.join(BASE_DIR, "detail_debug.json")
            try:
                with open(debug_file, "w", encoding="utf-8") as df:
                    json.dump(detail_data, df, indent=4)
            except Exception as e:
                print(f"Error saving detail_debug.json: {e}")

            if not filament_info:
                if isinstance(detail_data, dict) and "error" in detail_data:
                    filament_info_error = detail_data["error"]
                else:
                    code_val = detail_data.get("code") if isinstance(detail_data, dict) else None
                    msg_val = detail_data.get("message") if isinstance(detail_data, dict) else None
                    keys_found = list(detail_data.keys()) if isinstance(detail_data, dict) else []

                    if isinstance(detail_data, dict) and ("code" in detail_data or "message" in detail_data):
                        is_auth_error = (
                            code_val in [401, -1] or 
                            (isinstance(msg_val, str) and any(x in msg_val.lower() for x in ["auth", "parameter"]))
                        )
                        if is_auth_error:
                            filament_info_error = f"Kimlik Doğrulama Hatası (Kod: {code_val}, Mesaj: {msg_val}). Lütfen Seri Numarasını ve LAN Kodunu (Ayarlar -> LAN Şifresi) kontrol edin."
                        elif code_val in [0, 200] or (isinstance(msg_val, str) and msg_val.lower() in ["ok", "success"]):
                            filament_info_error = f"Bağlantı başarılı fakat filament istasyonu bilgisi (matlStationInfo) bulunamadı. Yazıcınız standart Adventurer 5M (non-Pro) olabilir veya filament istasyonu (IFS) bağlı/etkin olmayabilir."
                        else:
                            filament_info_error = f"Yazıcı Hata Döndürdü - Kod: {code_val}, Mesaj: {msg_val}"
                    else:
                        filament_info_error = f"HTTP bağlantısı başarılı fakat 'matlStationInfo' bulunamadı. Mevcut anahtarlar: {keys_found}"
        except Exception as e:
            err_str = str(e)
            if "111" in err_str or "connection refused" in err_str.lower():
                filament_info_error = "Bağlantı Reddedildi (Port 8898 Kapalı). Yazıcı ayarlarından LAN modunun açık olduğunu doğrulayın. Eğer yazıcınız standart Adventurer 5M ise bu portu ve IFS özelliğini donanımsal olarak desteklemiyor olabilir."
            elif "timeout" in err_str.lower():
                filament_info_error = "Zaman Aşımı (Port 8898 yanıt vermiyor). IP adresini ve yazıcının ağ durumunu kontrol edin."
            else:
                filament_info_error = f"HTTP Bağlantı Hatası: {err_str}"
            print(f"HTTP Detail API Error: {e}")

    # Determine active printing file from M119 or HTTP detail API
    http_file = ""
    if isinstance(detail_dict, dict):
        http_file = (
            detail_dict.get("printFileName") or 
            detail_dict.get("fileName") or 
            detail_dict.get("curFileName") or 
            detail_dict.get("filename") or 
            detail_dict.get("curFile") or 
            detail_dict.get("jobName") or ""
        )
    active_current_file = parsed_m119.get("current_file", "") or http_file

    # Determine pause / error state and underlying reason
    machine_status_upper = (parsed_m119.get("machine_status") or "UNKNOWN").strip().upper()
    is_paused_state = machine_status_upper in ["PAUSED", "PAUSE", "PAUSING"]
    is_error_state = machine_status_upper in ["ERROR", "STOPPED", "ABORTED"]
    
    detected_reason = None
    detected_error = parsed_m119.get("detected_error")
    
    # 1. Door open check
    door_status = detail_dict.get("doorStatus", "unknown")
    if door_status == "open" and (is_paused_state or is_error_state):
        detected_reason = "Ön / Üst Kapak Açık! Yazıcı güvenlik sensörü nedeniyle duraklatıldı. Kapağı kapatıp 'Devam Et' butonuna basabilirsiniz."
        
    # 2. Filament lack / runout check
    filament_lack = detail_dict.get("filamentLack") or detail_dict.get("isFilamentLack")
    if filament_lack in [True, 1, "1", "true", "True"]:
        detected_reason = "Filament Bitti veya Algılanmadı! Ekstrüderde filament tespit edilemedi. Yeni filament yükledikten sonra 'Devam Et' butonuna basabilirsiniz."
        
    # 3. HTTP detail error or pause reason
    http_error_code = detail_dict.get("errorCode") or detail_dict.get("errCode")
    http_error_msg = (
        detail_dict.get("errorMsg") or 
        detail_dict.get("errMsg") or 
        detail_dict.get("pauseReason") or 
        detail_dict.get("pauseMsg") or
        detail_dict.get("reason")
    )
    if http_error_code or http_error_msg:
        err_text = f"Hata Kodu: {http_error_code} ({http_error_msg})" if http_error_code and http_error_msg else str(http_error_code or http_error_msg)
        if is_error_state:
            detected_error = err_text
        elif not detected_reason:
            detected_reason = err_text

    # 4. Status flags filament check (Status: S:1 L:1 J:0 F:0)
    status_flags = parsed_m119.get("status_flags", "")
    if is_paused_state and not detected_reason:
        if "F:1" in status_flags:
            detected_reason = "Filament Sensörü Tetiklendi (Filament bitti veya besleme kesildi). Lütfen filamenti kontrol edin."
        elif "J:1" in status_flags:
            detected_reason = "Baskı Duraklatıldı (Sıkışma veya duraklatma sinyali algılandı)."
        elif parsed_m119.get("extra_messages"):
            detected_reason = " / ".join(parsed_m119["extra_messages"])
        else:
            layer_val = parsed_m27.get("layer", "0/0")
            cur_l = layer_val.split("/")[0].strip() if "/" in layer_val else ""
            if cur_l and cur_l != "0":
                detected_reason = f"Baskı {cur_l}. katmanda duraklatıldı. Devam etmek için 'Devam Et' butonuna basabilirsiniz."
            else:
                detected_reason = "Baskı duraklatıldı. Devam etmek için 'Devam Et' butonuna basabilirsiniz."
            
    if is_error_state and not detected_error:
        detected_error = f"Yazıcı arıza/hata moduna geçti (Durum: {machine_status_upper})."

    # Determine finished/completed print & platform clean state ("Yazdırma tamamlandı, platformu temizleyin!")
    progress_val = parsed_m27.get("progress", 0)
    layer_val = parsed_m27.get("layer", "0/0")
    cur_layer, total_layer = (0, 0)
    if "/" in layer_val:
        try:
            parts = layer_val.split("/")
            cur_layer = int(parts[0].strip())
            total_layer = int(parts[1].strip())
        except Exception:
            pass

    # Check detail_dict (HTTP 8898 /detail) if M27 didn't report layer info
    if cur_layer == 0 and detail_dict.get("printLayer"):
        try:
            cur_layer = int(detail_dict.get("printLayer"))
            total_layer = int(detail_dict.get("targetPrintLayer") or total_layer)
        except Exception:
            pass

    unified_layer = f"{cur_layer}/{total_layer}"

    if progress_val == 0 and detail_dict.get("printProgress"):
        try:
            progress_val = int(float(detail_dict.get("printProgress")))
        except Exception:
            pass

    prev_clean_needed = last_status.get("platform_clean_needed", False)
    is_completed_state = False
    
    is_completed_status = machine_status_upper in [
        "COMPLETED", "FINISHED", "BUILD_COMPLETED", "PRINT_COMPLETE", "PRINT_COMPLETED", "BUILDING_COMPLETED", "FINISH"
    ]
    detail_status = str(detail_dict.get("status", "") or detail_dict.get("printStatus", "")).strip().lower()
    detail_clean_plate = detail_dict.get("cleanPlate")
    is_active_printing = (
        machine_status_upper in ["BUILDING", "BUILDING_FROM_SD", "PRINTING"] or
        detail_status in ["building", "printing"]
    )
    
    if is_completed_status:
        is_completed_state = True
    elif detail_status in ["completed", "finish", "finished"]:
        is_completed_state = True
    elif detail_clean_plate is False or detail_dict.get("isCleanPlate") is False:
        if not (is_active_printing or is_paused_state):
            is_completed_state = True
    elif progress_val == 100 and active_current_file and active_current_file not in ["-", "Boşta", "UNKNOWN"]:
        if not (is_active_printing or is_paused_state):
            is_completed_state = True
    elif cur_layer > 0 and total_layer > 0 and cur_layer >= total_layer and active_current_file not in ["-", "Boşta", "UNKNOWN"]:
        if not (is_active_printing or is_paused_state):
            is_completed_state = True

    platform_clean_needed = is_completed_state or (prev_clean_needed and not is_active_printing)

    status = {
        "machine_status": parsed_m119.get("machine_status", "UNKNOWN"),
        "move_mode": parsed_m119.get("move_mode", "UNKNOWN"),
        "is_printing": is_active_printing,
        "current_file": active_current_file,
        "progress": progress_val,
        "layer": unified_layer,
        "current_layer": cur_layer,
        "total_layers": total_layer,
        "temperatures": parsed_m105,
        "endstop": parsed_m119.get("endstop", {}),
        "led": parsed_m119.get("led", "?"),
        "status_flags": parsed_m119.get("status_flags", "S:? L:? J:? F:?"),
        "updated_at": datetime.now().strftime("%H:%M:%S"),
        "is_paused": is_paused_state,
        "is_error": is_error_state,
        "is_completed": is_completed_state,
        "platform_clean_needed": platform_clean_needed,
        "pause_reason": detected_reason,
        "printer_error": detected_error,
        "error": detected_error if detected_error else (None if "ERR:" not in m119_text and "ERR:" not in m27_text else m119_text),
        "filament_info": filament_info,
        "filament_info_error": filament_info_error,
        # HTTP detail API values
        "chamber_temp": detail_dict.get("chamberTemp", 0.0),
        "chamber_target_temp": detail_dict.get("chamberTargetTemp", 0.0),
        "chamber_fan_speed": detail_dict.get("chamberFanSpeed", 0),
        "cooling_fan_speed": detail_dict.get("coolingFanSpeed", 0),
        "cooling_fan_left_speed": detail_dict.get("coolingFanLeftSpeed", 0),
        "door_status": detail_dict.get("doorStatus", "unknown"),
        "light_status": detail_dict.get("lightStatus", "unknown"),
        "firmware_version": detail_dict.get("firmwareVersion", ""),
        "cumulative_print_time": detail_dict.get("cumulativePrintTime", 0),
        "cumulative_filament": detail_dict.get("cumulativeFilament", 0.0),
        "remaining_disk_space": detail_dict.get("remainingDiskSpace", 0.0),
        "estimated_time": detail_dict.get("estimatedTime", 0.0),
        "print_duration": detail_dict.get("printDuration", 0) or 0,
        "nozzle_model": detail_dict.get("nozzleModel", ""),
        "tvoc": detail_dict.get("tvoc", 0),
        "z_axis_compensation": detail_dict.get("zAxisCompensation", 0.0),
        "ip_addr": detail_dict.get("ipAddr", ""),
        "mac_addr": detail_dict.get("macAddr", ""),
        "detail_raw": detail_dict,
        "debug_env": {
            "serial_set": bool(PRINTER_SERIAL),
            "check_code_set": bool(PRINTER_CHECK_CODE),
            "host": PRINTER_HOST
        }
    }

    async with lock:
        previous_status = last_status.get("machine_status", "UNKNOWN").strip().upper()
        current_status = status.get("machine_status", "UNKNOWN").strip().upper()
        
        is_prev_printing = previous_status in ["BUILDING_FROM_SD", "BUILDING", "PRINTING", "PAUSED", "PAUSE", "PAUSING"]
        is_curr_idle = current_status in ["READY", "IDLE", "OFFLINE"]
        
        if is_prev_printing and is_curr_idle:
            last_status["speed_factor"] = 100
            last_status["fan_speed"] = 0
            last_status["z_offset"] = 0.0
            save_tuning_config()
            
        last_status.update(status)
        status_history.append(status)

        # Drive automated timelapse frame capture
        try:
            if 'timelapse_manager' in globals():
                timelapse_manager.process_status(status)
        except Exception as tle:
            print(f"TimeLapse process error: {tle}")


failed_consecutive_polls = 0
last_auto_discover_time = 0.0


async def watch_loop():
    global failed_consecutive_polls, last_auto_discover_time
    while True:
        try:
            await refresh_once()
            failed_consecutive_polls = 0
        except Exception as e:
            async with lock:
                last_status["error"] = str(e)
            failed_consecutive_polls += 1
            now = time.time()
            if failed_consecutive_polls >= 4 and (now - last_auto_discover_time) > 20.0:
                last_auto_discover_time = now
                try:
                    print(f"Auto-Recovery: Lost connection to {PRINTER_HOST}. Scanning network for printer...")
                    found_printers = await discover_printers_on_network()
                    matched = None
                    for p in found_printers:
                        if PRINTER_SERIAL and p.get("serial") == PRINTER_SERIAL:
                            matched = p
                            break
                    if not matched and len(found_printers) == 1:
                        matched = found_printers[0]
                    if matched and matched["ip"] != PRINTER_HOST:
                        new_ip = matched["ip"]
                        print(f"Auto-Recovery: Discovered printer at new IP {new_ip}! Updating config automatically.")
                        save_config(new_ip, PRINTER_PORT, matched.get("serial") or PRINTER_SERIAL, PRINTER_CHECK_CODE)
                        if 'camera_broadcaster' in globals() and camera_broadcaster:
                            camera_broadcaster.reset()
                        failed_consecutive_polls = 0
                except Exception as de:
                    print(f"Auto-Recovery error: {de}")
        await asyncio.sleep(WATCH_INTERVAL)


@app.on_event("startup")
async def startup():
    global watch_task
    watch_task = asyncio.create_task(watch_loop())


@app.get("/hFlashForgeLogo.svg")
async def get_logo_svg():
    svg_path = os.path.join(BASE_DIR, "hFlashForgeLogo.svg")
    if os.path.exists(svg_path):
        return FileResponse(svg_path, media_type="image/svg+xml")
    return Response(status_code=404)


@app.get("/hFlashForgeLogo.png")
@app.get("/favicon.ico")
async def get_logo_png():
    png_path = os.path.join(BASE_DIR, "hFlashForgeLogo.png")
    if os.path.exists(png_path):
        return FileResponse(png_path, media_type="image/png")
    svg_path = os.path.join(BASE_DIR, "hFlashForgeLogo.svg")
    if os.path.exists(svg_path):
        return FileResponse(svg_path, media_type="image/svg+xml")
    return Response(status_code=404)


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    path = os.path.join(TEMPLATES_DIR, "dashboard.html")
    try:
        with open(path, "r", encoding="utf-8") as f:
            html = f.read().replace("{{ printer }}", PRINTER_HOST)
        return HTMLResponse(html)
    except Exception as e:
        return HTMLResponse(f"<h1>Panel hatası</h1><pre>{e}</pre>", status_code=500)


@app.get("/api/status")
async def api_status():
    async with lock:
        st = dict(last_status)
    try:
        st["panel_build"] = "20261012_v2"
        if 'timelapse_manager' in globals():
            st["timelapse_base_dir"] = timelapse_manager.base_dir
            active = timelapse_manager.get_active_session_info()
            st["timelapse_active"] = active is not None
            if active:
                st["timelapse_frames"] = active.get("captured_frames", 0)
    except Exception:
        pass
    return JSONResponse(st)


@app.post("/api/command")
async def api_command(command: dict):
    cmd_map = {
        "pause": b"~M25\r\n",
        "resume": b"~M24\r\n",
        "stop": b"~M26\r\n",
        "home": b"~G28\r\n",
        "led_on": b"~M146 r255 g255 b255 f0\r\n",
        "led_off": b"~M146 r0 g0 b0 f0\r\n",
        "reboot": b"~M999\r\n",
        "unlock": b"~M602\r\n",
    }
    c = command.get("command")
    
    if c == "custom":
        gcode = command.get("gcode", "").strip()
        if not gcode:
            return JSONResponse({"ok": False, "error": "Boş G-kod gönderilemez"}, status_code=400)
        
        # Parse live tuning commands in backend to update state
        import re
        lines = []
        for line in gcode.splitlines():
            line_str = line.strip()
            if not line_str:
                continue
                
            # Parse speed factor: M220 S<val>
            m220_match = re.search(r"M220\s+S(\d+)", line_str, re.IGNORECASE)
            if m220_match:
                try:
                    last_status["speed_factor"] = int(m220_match.group(1))
                except Exception:
                    pass
                    
            # Parse fan speed: M106 S<val>
            m106_match = re.search(r"M106\s+S(\d+)", line_str, re.IGNORECASE)
            if m106_match:
                try:
                    speed_val = int(m106_match.group(1))
                    last_status["fan_speed"] = int(round(speed_val / 2.55))
                except Exception:
                    pass
                    
            # Parse Z-offset / Babystepping
            z_adjust_match = re.search(r"Z_ADJUST=([+-]?\d*(?:\.\d+)?)", line_str, re.IGNORECASE)
            if z_adjust_match:
                try:
                    adjust_val = float(z_adjust_match.group(1))
                    last_status["z_offset"] = round(last_status.get("z_offset", 0.0) + adjust_val, 3)
                except Exception:
                    pass
            else:
                m290_match = re.search(r"(?:M290|G29\.1)\s+Z([+-]?\d*(?:\.\d+)?)", line_str, re.IGNORECASE)
                if m290_match:
                    try:
                        adjust_val = float(m290_match.group(1))
                        if "M290" in line_str.upper():
                            last_status["z_offset"] = round(last_status.get("z_offset", 0.0) + adjust_val, 3)
                        else:
                            last_status["z_offset"] = round(adjust_val, 3)
                    except Exception:
                        pass
                else:
                    z_set_match = re.search(r"SET_GCODE_OFFSET\s+Z=([+-]?\d*(?:\.\d+)?)", line_str, re.IGNORECASE)
                    if z_set_match:
                        try:
                            last_status["z_offset"] = round(float(z_set_match.group(1)), 3)
                        except Exception:
                            pass
            
            # Format line for FlashForge protocol
            if not line_str.startswith("~"):
                line_str = "~" + line_str
            if not line_str.endswith("\r\n"):
                line_str += "\r\n"
            lines.append(line_str)
            
        if not lines:
            return JSONResponse({"ok": False, "error": "Geçersiz G-kod formatı"}, status_code=400)
            
        # Save updated tuning values to config file
        save_tuning_config()
            
        gcode_payload = "".join(lines)
        raw = await send_command(gcode_payload.encode("utf-8"))
    elif c == "clear_platform":
        loop = asyncio.get_event_loop()
        res = await loop.run_in_executor(
            None, _clear_platform_sync, PRINTER_HOST, PRINTER_PORT, PRINTER_SERIAL, PRINTER_CHECK_CODE
        )
        async with lock:
            last_status["platform_clean_needed"] = False
            last_status["is_completed"] = False
            last_status["current_file"] = ""
            last_status["progress"] = 0
            last_status["layer"] = "0/0"
        return JSONResponse(res)
    elif c in cmd_map:
        raw = await send_command(cmd_map[c])
    else:
        return JSONResponse({"ok": False, "error": "Desteklenmeyen komut"}, status_code=400)
        
    text = raw.decode("utf-8", errors="ignore") if isinstance(raw, bytes) else str(raw)
    return JSONResponse({"ok": True, "response": text.strip()})


def _clear_platform_sync(host, port, serial, check_code):
    """Sends setClearPlatform commands via HTTP port 8898 and resets TCP control session (~M26) to dismiss 'Platformu Temizleyin!'."""
    http_res = []
    if serial and check_code:
        import urllib.request
        url = f"http://{host}:8898/control"
        headers = {
            "serialNumber": serial,
            "serialNo": serial,
            "checkCode": check_code,
            "Content-Type": "application/json"
        }
        cmds = [
            {"cmd": "stateCtrl_cmd", "args": {"action": "setClearPlatform"}},
            {"cmd": "stateCtrl_cmd", "args": {"action": "cleanPlate"}},
            {"cmd": "stateCtrl_cmd", "args": {"action": "clearError"}},
            {"cmd": "plateDetectControl_cmd", "args": {"action": "setClearPlatform"}}
        ]
        for cmd_payload in cmds:
            payload = {
                "serialNumber": serial,
                "checkCode": check_code,
                "payload": cmd_payload
            }
            try:
                req = urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode('utf-8'),
                    headers=headers,
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=3) as resp:
                    http_res.append(resp.read().decode('utf-8', errors='ignore'))
            except Exception as he:
                http_res.append(f"HTTP ERR ({cmd_payload['cmd']}): {he}")

    # Also send TCP M26 to ensure print job state is cleared in Marlin/Klipper layer
    tcp_res = ""
    try:
        with socket.create_connection((host, port), timeout=3) as s:
            s.sendall(b"~M601 S1\r\n")
            socket_recv_until(s, markers=(b"ok\r\n", b"Control", b"CMD"), timeout=2)
            s.sendall(b"~M26\r\n")
            res = socket_recv_until(s, markers=(b"ok\r\n",), timeout=2)
            tcp_res = res.decode('utf-8', errors='ignore').strip()
            s.sendall(b"~M602\r\n")
            socket_recv_until(s, markers=(b"ok\r\n",), timeout=1)
    except Exception as e:
        tcp_res = f"TCP ERR: {e}"

    return {
        "ok": True,
        "message": "Platform temizleme onayı yazıcıya iletildi. Ekran uyarısı kapatıldı ve yazıcı yeni baskı için hazır.",
        "http_response": "; ".join(http_res) if isinstance(http_res, list) else str(http_res),
        "tcp": tcp_res
    }


@app.post("/api/clear_platform")
async def api_clear_platform():
    """Clears the completed print modal on printer and resets platform clean state."""
    loop = asyncio.get_event_loop()
    res = await loop.run_in_executor(
        None, _clear_platform_sync, PRINTER_HOST, PRINTER_PORT, PRINTER_SERIAL, PRINTER_CHECK_CODE
    )
    async with lock:
        last_status["platform_clean_needed"] = False
        last_status["is_completed"] = False
        last_status["current_file"] = ""
        last_status["progress"] = 0
        last_status["layer"] = "0/0"
    asyncio.create_task(refresh_once())
    return JSONResponse(res)


def extract_model_tools(filename: str, file_bytes: bytes) -> list:
    """Extracts all tool IDs, material names, and colors from a .3mf or .gcode file,
    checking 3MF metadata, XML filament tags, and tail/head slicer configurations.
    """
    if not file_bytes:
        return [{"toolId": 0, "materialName": "PLA", "toolMaterialColor": "#161616"}]

    tools = []
    clean_name = os.path.basename(filename.replace("\\", "/")).strip()
    is_zip = file_bytes.startswith(b"PK\x03\x04") or clean_name.lower().endswith(".3mf")

    def normalize_color(col: str) -> str:
        if not col:
            return "#161616"
        c = col.strip()
        if not c.startswith("#"):
            c = "#" + c
        # If 8 hex characters after # (e.g. #FFFFFFFE or #000000FF RGBA), trim to 6-char RGB
        if len(c) == 9:
            c = c[:7]
        return c

    # Helper to parse text for filament metadata (both head and tail)
    def parse_gcode_text_for_tools(text: str) -> list:
        found_tools = []
        # 1. XML filament tags (common in OrcaSlicer, BambuStudio, Flash Studio G-code)
        for m in re.finditer(r'<filament\s+([^>]+)/>', text):
            attribs = dict(re.findall(r'(\w+)=["\']([^"\']+)["\']', m.group(1)))
            f_id = attribs.get("id", "")
            f_type = attribs.get("type", "PLA")
            f_color = attribs.get("color", "")
            if f_id.isdigit():
                t_id = int(f_id) - 1
                found_tools.append({
                    "toolId": max(0, t_id),
                    "materialName": f_type or "PLA",
                    "toolMaterialColor": normalize_color(f_color)
                })
        if found_tools:
            return found_tools

        # 2. Key-value comments: filament_colour / extruder_colour / filament_type
        colors = []
        types = []
        c_match = re.search(r';\s*(?:filament_colour|extruder_colour|filament_multi_colour)\s*[:=]\s*([^\r\n]+)', text, re.IGNORECASE)
        if c_match:
            raw_c = c_match.group(1).replace(';', ',')
            c_list = [c.strip() for c in raw_c.split(',') if c.strip()]
            colors = [normalize_color(c) for c in c_list]

        t_match = re.search(r';\s*filament_type\s*[:=]\s*([^\r\n]+)', text, re.IGNORECASE)
        if t_match:
            raw_t = t_match.group(1).replace(';', ',')
            types = [t.strip() for t in raw_t.split(',') if t.strip()]

        if colors:
            for idx, col in enumerate(colors):
                m_type = types[idx] if idx < len(types) else "PLA"
                found_tools.append({
                    "toolId": idx,
                    "materialName": m_type or "PLA",
                    "toolMaterialColor": col
                })
            return found_tools

        # 3. Check for ; filament: 1,2 or ; filament_density: 1.24,1.24
        fil_cnt_match = re.search(r';\s*filament\s*[:=]\s*([0-9,\s]+)', text, re.IGNORECASE)
        if fil_cnt_match:
            fil_nums = [n.strip() for n in fil_cnt_match.group(1).split(',') if n.strip().isdigit()]
            if len(fil_nums) > 1:
                default_palette = ["#161616", "#FFFFFF", "#F330F9", "#00AAFF"]
                for idx in range(len(fil_nums)):
                    found_tools.append({
                        "toolId": idx,
                        "materialName": "PLA",
                        "toolMaterialColor": default_palette[idx % len(default_palette)]
                    })
                return found_tools

        return found_tools

    # Helper to check G-code tool changes (T0, T1, T2, T3)
    def scan_gcode_tool_changes(text: str) -> set:
        tools_seen = set()
        for t in re.findall(r'^[Tt](\d+)', text, re.MULTILINE):
            tools_seen.add(int(t))
        return tools_seen

    # 1. If 3MF / ZIP
    if is_zip:
        try:
            with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
                # A. Metadata/slice_info.config
                for name in z.namelist():
                    if name.lower().endswith("slice_info.config"):
                        content = z.read(name).decode("utf-8", errors="ignore")
                        try:
                            root = ET.fromstring(content)
                            for fil in root.findall(".//filament"):
                                fil_id = fil.attrib.get("id", "")
                                fil_type = fil.attrib.get("type", "PLA")
                                fil_color = fil.attrib.get("color", "")
                                if fil_id.isdigit():
                                    t_id = int(fil_id) - 1
                                    tools.append({
                                        "toolId": max(0, t_id),
                                        "materialName": fil_type or "PLA",
                                        "toolMaterialColor": normalize_color(fil_color)
                                    })
                        except Exception:
                            pass
                        if tools:
                            break

                # B. Metadata/project_settings.config
                if not tools:
                    for name in z.namelist():
                        if name.lower().endswith("project_settings.config"):
                            try:
                                cfg = json.loads(z.read(name).decode("utf-8", errors="ignore"))
                                colours = cfg.get("filament_colour", [])
                                types = cfg.get("filament_type", [])
                                if colours:
                                    for idx, col in enumerate(colours):
                                        m_type = types[idx] if idx < len(types) else "PLA"
                                        tools.append({
                                            "toolId": idx,
                                            "materialName": m_type or "PLA",
                                            "toolMaterialColor": normalize_color(col)
                                        })
                            except Exception:
                                pass
                            if tools:
                                break

                # C. Check embedded G-code in 3MF
                if not tools:
                    g_cands = [n for n in z.namelist() if n.lower().endswith(".gcode")]
                    if g_cands:
                        chosen = max(g_cands, key=lambda n: z.getinfo(n).file_size)
                        raw_g = z.read(chosen)
                        head = raw_g[:131072].decode("utf-8", errors="ignore")
                        tail = raw_g[-262144:].decode("utf-8", errors="ignore") if len(raw_g) > 262144 else head
                        tools = parse_gcode_text_for_tools(tail) or parse_gcode_text_for_tools(head)
        except Exception as ze:
            print(f"3MF parse error: {ze}")

    # 2. Standalone G-code
    if not tools:
        head = file_bytes[:131072].decode("utf-8", errors="ignore")
        tail = file_bytes[-262144:].decode("utf-8", errors="ignore") if len(file_bytes) > 262144 else head
        tools = parse_gcode_text_for_tools(tail) or parse_gcode_text_for_tools(head)

    # 3. Check tool change commands T0, T1, ... to ensure all active tools exist
    try:
        sample_text = ""
        if is_zip:
            with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
                g_cands = [n for n in z.namelist() if n.lower().endswith(".gcode")]
                if g_cands:
                    chosen = max(g_cands, key=lambda n: z.getinfo(n).file_size)
                    sample_text = z.read(chosen).decode("utf-8", errors="ignore")
        else:
            sample_text = file_bytes.decode("utf-8", errors="ignore")

        if sample_text:
            active_tools = scan_gcode_tool_changes(sample_text)
            if active_tools:
                max_t = max(active_tools)
                existing_tool_ids = {t["toolId"] for t in tools}
                default_palette = ["#161616", "#FFFFFF", "#F330F9", "#00AAFF"]
                for t_num in range(max_t + 1):
                    if t_num in active_tools and t_num not in existing_tool_ids:
                        tools.append({
                            "toolId": t_num,
                            "materialName": "PLA",
                            "toolMaterialColor": default_palette[t_num % len(default_palette)]
                        })
    except Exception:
        pass

    # Sort tools by toolId
    tools.sort(key=lambda x: x["toolId"])

    # Fallback if empty: at least 1 tool
    if not tools:
        tools = [{
            "toolId": 0,
            "materialName": "PLA",
            "toolMaterialColor": "#161616"
        }]

    return tools


@app.post("/api/model/parse")
async def api_model_parse(request: Request, filename: str):
    """Extracts tool & filament color requirements from a 3MF or G-code file and returns current IFS slot info."""
    body = await request.body()
    if not body:
        return JSONResponse({"ok": False, "error": "Boş dosya."}, status_code=400)
    tools = extract_model_tools(filename, body)
    async with lock:
        filament_info = last_status.get("filament_info")
        clean_needed = last_status.get("platform_clean_needed", False) or last_status.get("is_completed", False)
    return {
        "ok": True,
        "filename": filename,
        "tools": tools,
        "filament_info": filament_info,
        "clean_needed": clean_needed
    }


def _get_printer_gcode_list_sync(host: str, serial: str, check_code: str) -> dict:
    """Queries /gcodeList from FlashForge port 8898."""
    import urllib.request
    url = f"http://{host}:8898/gcodeList"
    payload = {"serialNumber": serial, "checkCode": check_code}
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=8) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _start_print_job_sync(
    host: str,
    serial: str,
    check_code: str,
    filename: str,
    leveling_before_print: bool = True,
    time_lapse_video: bool = True,
    use_matl_station: bool = True,
    flow_calibration: bool = False,
    first_layer_inspection: bool = False,
    material_mappings: list = None
) -> dict:
    """Sends /printGcode POST request to FlashForge port 8898 to start printing the specified file."""
    import urllib.request
    url = f"http://{host}:8898/printGcode"
    clean_filename = os.path.basename(filename.replace("\\", "/"))

    mappings_clean = []
    if material_mappings and use_matl_station:
        if isinstance(material_mappings, str):
            try:
                material_mappings = json.loads(material_mappings)
            except Exception:
                material_mappings = []
        if isinstance(material_mappings, list):
            for m in material_mappings:
                if isinstance(m, dict):
                    mappings_clean.append({
                        "toolId": int(m.get("toolId", 0)),
                        "slotId": int(m.get("slotId", 1)),
                        "materialName": str(m.get("materialName", "PLA")),
                        "toolMaterialColor": str(m.get("toolMaterialColor", "#161616")),
                        "slotMaterialColor": str(m.get("slotMaterialColor", m.get("toolMaterialColor", "#161616")))
                    })

    # If materialMappings was not provided, auto-read from printer's parsed gcodeListDetail
    if use_matl_station and not mappings_clean:
        try:
            glist = _get_printer_gcode_list_sync(host, serial, check_code)
            for item in glist.get("gcodeListDetail", []):
                if item.get("gcodeFileName") == clean_filename:
                    for td in item.get("gcodeToolDatas", []):
                        color = str(td.get("materialColor", "#161616"))
                        mappings_clean.append({
                            "toolId": int(td.get("toolId", 0)),
                            "slotId": int(td.get("slotId", 1)),
                            "materialName": str(td.get("materialName", "PLA")),
                            "toolMaterialColor": color,
                            "slotMaterialColor": color
                        })
                    break
        except Exception as ge:
            print(f"Auto-extracting tools from printer gcodeList failed: {ge}")

    # Fallback to default single tool if still empty but IFS requested
    if use_matl_station and not mappings_clean:
        mappings_clean.append({
            "toolId": 0,
            "slotId": 1,
            "materialName": "PLA",
            "toolMaterialColor": "#161616",
            "slotMaterialColor": "#161616"
        })

    payload = {
        "serialNumber": serial,
        "checkCode": check_code,
        "fileName": clean_filename,
        "levelingBeforePrint": bool(leveling_before_print),
        "flowCalibration": bool(flow_calibration),
        "firstLayerInspection": bool(first_layer_inspection),
        "timeLapseVideo": bool(time_lapse_video),
        "useMatlStation": bool(use_matl_station),
        "gcodeToolCnt": len(mappings_clean) if use_matl_station else 0,
        "materialMappings": mappings_clean if use_matl_station else []
    }

    req_data = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "serialNumber": serial,
        "serialNo": serial,
        "checkCode": check_code,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) FlashForge-Panel/1.0"
    }
    req = urllib.request.Request(
        url,
        data=req_data,
        headers=headers,
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _upload_gcode_sync(
    host, serial, check_code, filename, file_bytes,
    print_now=False,
    leveling_before_print=True,
    time_lapse_video=True,
    use_matl_station=True,
    flow_calibration=False,
    first_layer_inspection=False,
    material_mappings=None
):
    import urllib.request
    url = f"http://{host}:8898/uploadGcode"

    boundary = "----WebKitFormBoundaryFlashForgeAD5X"
    body = bytearray()
    body.extend(f"--{boundary}\r\n".encode('utf-8'))
    body.extend(f'Content-Disposition: form-data; name="gcodeFile"; filename="{filename}"\r\n'.encode('utf-8'))
    body.extend(b"Content-Type: application/octet-stream\r\n\r\n")
    body.extend(file_bytes)
    body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode('utf-8'))

    content_type = f"multipart/form-data; boundary={boundary}"

    # Process material mappings
    mappings_list = []
    if material_mappings:
        if isinstance(material_mappings, str):
            try:
                mappings_list = json.loads(material_mappings)
            except Exception:
                mappings_list = []
        elif isinstance(material_mappings, list):
            mappings_list = material_mappings

    if not mappings_list:
        # Auto extract tools from file
        detected_tools = extract_model_tools(filename, file_bytes)
        for t in detected_tools:
            t_id = t.get("toolId", 0)
            mappings_list.append({
                "toolId": t_id,
                "slotId": (t_id + 1) if t_id < 4 else 1,
                "materialName": t.get("materialName", "PLA"),
                "toolMaterialColor": t.get("toolMaterialColor", "#161616"),
                "slotMaterialColor": t.get("toolMaterialColor", "#161616")
            })

    tool_cnt = len(mappings_list) if mappings_list else 1
    mappings_json_str = json.dumps(mappings_list)

    headers = {
        "serialNumber": serial,
        "serialNo": serial,
        "checkCode": check_code,
        "fileSize": str(len(file_bytes)),
        "printNow": "0",  # Sadece dosya yukle; baski baslatma ardindan retry mekanizmali /printGcode ile yapilir
        "levelingBeforePrint": "1" if leveling_before_print else "0",
        "flowCalibration": "1" if flow_calibration else "0",
        "firstLayerInspection": "1" if first_layer_inspection else "0",
        "timeLapseVideo": "1" if time_lapse_video else "0",
        "useMatlStation": "1" if use_matl_station else "0",
        "gcodeToolCnt": str(tool_cnt),
        "materialMappings": mappings_json_str,
        "Content-Type": content_type
    }

    req = urllib.request.Request(
        url,
        data=bytes(body),
        headers=headers,
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=90) as response:
        return json.loads(response.read().decode())


@app.post("/api/upload")
async def api_upload(
    request: Request,
    filename: str,
    print_now: bool = False,
    force_clean: bool = False,
    leveling_before_print: bool = True,
    time_lapse_video: bool = True,
    use_matl_station: bool = True,
    flow_calibration: bool = False,
    first_layer_inspection: bool = False,
    material_mappings: str = None,
    time_lapse_mode: Optional[str] = "hybrid",
    time_lapse_interval: Optional[int] = 10
):
    if not PRINTER_SERIAL or not PRINTER_CHECK_CODE:
        return JSONResponse({"ok": False, "error": "Seri Numarası veya LAN Kodu ayarlanmamış"}, status_code=400)

    try:
        file_bytes = await request.body()
        if not file_bytes:
            return JSONResponse({"ok": False, "error": "Dosya içeriği boş"}, status_code=400)

        loop = asyncio.get_event_loop()
        # Save to local cache for 3D preview
        try:
            save_to_gcode_cache(filename, file_bytes)
        except Exception as ce:
            print(f"Error caching G-code file: {ce}")

        # Proactively clear previous print session if requested or platform cleaning was needed
        async with lock:
            clean_needed = last_status.get("platform_clean_needed", False) or last_status.get("is_completed", False)

        if force_clean or clean_needed:
            print("Upload: Clearing previous print session / platform modal before sending file...")
            await loop.run_in_executor(
                None, _clear_platform_sync, PRINTER_HOST, PRINTER_PORT, PRINTER_SERIAL, PRINTER_CHECK_CODE
            )
            await asyncio.sleep(1.0)

        try:
            res = await loop.run_in_executor(
                None,
                _upload_gcode_sync,
                PRINTER_HOST,
                PRINTER_SERIAL,
                PRINTER_CHECK_CODE,
                filename,
                file_bytes,
                print_now,
                leveling_before_print,
                time_lapse_video,
                use_matl_station,
                flow_calibration,
                first_layer_inspection,
                material_mappings
            )
        except Exception as upload_err:
            err_msg = str(upload_err)
            # Detect FlashForge rejection caused by uncleared platform modal (Broken pipe / Connection reset)
            is_pipe_error = any(k in err_msg for k in ["Broken pipe", "Errno 32", "10054", "ConnectionResetError", "RemoteDisconnected"])
            if is_pipe_error:
                print("Upload encountered Broken pipe! Attempting auto-clear setClearPlatform sequence and retry upload...")
                await loop.run_in_executor(
                    None, _clear_platform_sync, PRINTER_HOST, PRINTER_PORT, PRINTER_SERIAL, PRINTER_CHECK_CODE
                )
                await asyncio.sleep(1.5)
                try:
                    res = await loop.run_in_executor(
                        None,
                        _upload_gcode_sync,
                        PRINTER_HOST,
                        PRINTER_SERIAL,
                        PRINTER_CHECK_CODE,
                        filename,
                        file_bytes,
                        print_now,
                        leveling_before_print,
                        time_lapse_video,
                        use_matl_station,
                        flow_calibration,
                        first_layer_inspection,
                        material_mappings
                    )
                except Exception as retry_err:
                    async with lock:
                        last_status["platform_clean_needed"] = True
                    return JSONResponse({
                        "ok": False,
                        "error": "Yazıcı yeni baskıyı reddetti (Bağlantı koptu). Önceki baskı tamamlandığı için yazıcı 'Platformu Temizleyin' onayı bekliyor. Lütfen tablayı boşaltıp 'Platformu Temizle' butonuna basarak tekrar deneyin.",
                        "need_clear_platform": True
                    }, status_code=409)
            else:
                raise upload_err

        code_val = res.get("code")
        msg_val = res.get("message")
        if code_val == 0 or code_val == 200 or msg_val == "success":
            async with lock:
                last_status["platform_clean_needed"] = False
                last_status["is_completed"] = False

            clean_name = os.path.basename(filename.replace("\\", "/"))
            if print_now:
                if 'timelapse_manager' in globals():
                    timelapse_manager.pending_filename = clean_name
                    if time_lapse_mode:
                        timelapse_manager.capture_mode = time_lapse_mode
                    if time_lapse_interval:
                        timelapse_manager.capture_interval = int(time_lapse_interval)
                try:
                    camera_broadcaster.ensure_started()
                except Exception:
                    pass

                # Yazıcı dahili depolamasına (eMMC) dosya yazımının ve önizleme çıkarımının tamamlanması için bekle
                await asyncio.sleep(1.5)
                start_success = False
                start_err_msg = ""
                start_res = None

                # HTTP /printGcode için retry döngüsü (FlashForge eMMC yazım süresi ve busy durumunu karşılar)
                max_retries = 6
                for attempt in range(max_retries):
                    try:
                        start_res = await loop.run_in_executor(
                            None,
                            _start_print_job_sync,
                            PRINTER_HOST,
                            PRINTER_SERIAL,
                            PRINTER_CHECK_CODE,
                            clean_name,
                            leveling_before_print,
                            time_lapse_video,
                            use_matl_station,
                            flow_calibration,
                            first_layer_inspection,
                            material_mappings
                        )
                        print(f"Print start attempt {attempt+1}/{max_retries} response from /printGcode: {start_res}")
                        start_code = start_res.get("code") if isinstance(start_res, dict) else -1
                        msg = str(start_res.get("message", ""))
                        if start_code in (0, 200) or msg.lower() == "success":
                            start_success = True
                            break

                        start_err_msg = msg or f"Yazıcı hata kodu: {start_code}"
                        # Yazıcı meşgulse (dosya diske işleniyor veya önceki durum bekleniyor)
                        if any(k in msg.lower() for k in ["busy", "wait", "meşgul"]):
                            if attempt == 1:
                                # 2. denemede yazıcı halen busy ise ekran kilidini proaktif olarak temizle
                                print("Upload print start: Yazıcı busy döndü, proaktif clear_platform çalıştırılıyor...")
                                await loop.run_in_executor(
                                    None, _clear_platform_sync, PRINTER_HOST, PRINTER_PORT, PRINTER_SERIAL, PRINTER_CHECK_CODE
                                )
                            await asyncio.sleep(2.0)
                            continue
                        else:
                            await asyncio.sleep(1.5)
                    except Exception as start_e:
                        print(f"Error calling /printGcode (attempt {attempt+1}): {start_e}")
                        start_err_msg = str(start_e)
                        await asyncio.sleep(1.5)

                # HTTP /printGcode başarısız olduysa TCP port 8899 M23/M24 ile doğrudan başlatmayı dene
                if not start_success:
                    print(f"/printGcode başarısız ({start_err_msg}), TCP ~M23 / ~M24 fallback deneniyor...")
                    try:
                        m23_cmd = f"~M23 0:/user/{clean_name}\r\n".encode("utf-8")
                        tcp_res = await send_command(m23_cmd)
                        print(f"TCP M23 fallback response: {tcp_res}")
                        if b"File selected" in tcp_res or b"File opened" in tcp_res:
                            m24_res = await send_command(b"~M24\r\n")
                            print(f"TCP M24 fallback response: {m24_res}")
                            if b"ok" in m24_res or b"CMD" in m24_res:
                                start_success = True
                    except Exception as tcp_e:
                        print(f"TCP M23/M24 fallback error: {tcp_e}")

                asyncio.create_task(refresh_once())
                if start_success:
                    return {"ok": True, "message": f"Dosya '{clean_name}' yazıcıya yüklendi ve baskı başlatıldı."}
                else:
                    return JSONResponse({
                        "ok": False,
                        "error": f"Dosya yazıcıya yüklendi fakat baskı başlatılamadı: {start_err_msg}",
                        "filename": clean_name,
                        "can_start_stored": True
                    }, status_code=500)

            asyncio.create_task(refresh_once())
            return {"ok": True, "message": f"Dosya '{clean_name}' başarıyla yüklendi."}
        else:
            is_clean_err = any(k in str(msg_val).lower() for k in ["clean", "platform", "busy", "printing"])
            return JSONResponse({
                "ok": False,
                "error": f"Yazıcı hata döndürdü - Kod: {code_val}, Mesaj: {msg_val}",
                "need_clear_platform": is_clean_err
            }, status_code=500)

    except Exception as e:
        err_str = str(e)
        is_pipe_err = any(k in err_str for k in ["Broken pipe", "Errno 32", "10054"])
        if is_pipe_err:
            return JSONResponse({
                "ok": False,
                "error": "Bağlantı koptu (Broken pipe). Yazıcıda önceki baskı tamamlanmış ve 'Platformu Temizleyin' uyarısı aktif olabilir. Lütfen platformu temizleyip 'Platformu Temizle' butonuna basarak tekrar deneyin.",
                "need_clear_platform": True
            }, status_code=409)
        return JSONResponse({"ok": False, "error": f"Bağlantı hatası: {err_str}"}, status_code=500)


class StartPrintModel(BaseModel):
    filename: str
    leveling_before_print: bool = True
    time_lapse_video: bool = True
    use_matl_station: bool = True
    flow_calibration: bool = False
    first_layer_inspection: bool = False
    material_mappings: list = None
    time_lapse_mode: Optional[str] = "hybrid"
    time_lapse_interval: Optional[int] = 10


@app.get("/api/printer/files")
async def api_printer_files():
    """Returns the list of stored files and print metadata directly from printer flash memory."""
    if not PRINTER_SERIAL or not PRINTER_CHECK_CODE:
        return JSONResponse({"ok": False, "error": "Seri Numarası veya LAN Kodu ayarlanmamış"}, status_code=400)
    loop = asyncio.get_event_loop()
    try:
        res = await loop.run_in_executor(
            None, _get_printer_gcode_list_sync, PRINTER_HOST, PRINTER_SERIAL, PRINTER_CHECK_CODE
        )
        return JSONResponse({"ok": True, "data": res})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/api/print/start")
async def api_print_start(params: StartPrintModel):
    """Starts printing an existing file stored on the printer's storage."""
    if not PRINTER_SERIAL or not PRINTER_CHECK_CODE:
        return JSONResponse({"ok": False, "error": "Seri Numarası veya LAN Kodu ayarlanmamış"}, status_code=400)
    
    clean_name = os.path.basename(params.filename.replace("\\", "/")).strip()
    if not clean_name:
        return JSONResponse({"ok": False, "error": "Dosya adı belirtilmedi"}, status_code=400)
        
    if 'timelapse_manager' in globals():
        timelapse_manager.pending_filename = clean_name
        if params.time_lapse_mode:
            timelapse_manager.capture_mode = params.time_lapse_mode
        if params.time_lapse_interval:
            timelapse_manager.capture_interval = int(params.time_lapse_interval)
    try:
        camera_broadcaster.ensure_started()
    except Exception:
        pass
        
    loop = asyncio.get_event_loop()
    start_success = False
    start_err_msg = ""
    start_res = None

    max_retries = 5
    for attempt in range(max_retries):
        try:
            start_res = await loop.run_in_executor(
                None,
                _start_print_job_sync,
                PRINTER_HOST,
                PRINTER_SERIAL,
                PRINTER_CHECK_CODE,
                clean_name,
                params.leveling_before_print,
                params.time_lapse_video,
                params.use_matl_station,
                params.flow_calibration,
                params.first_layer_inspection,
                params.material_mappings
            )
            print(f"api_print_start attempt {attempt+1}/{max_retries} response: {start_res}")
            start_code = start_res.get("code") if isinstance(start_res, dict) else -1
            msg = str(start_res.get("message", ""))
            if start_code in (0, 200) or msg.lower() == "success":
                start_success = True
                break

            start_err_msg = msg or f"Yazıcı hata kodu: {start_code}"
            if any(k in msg.lower() for k in ["busy", "wait", "meşgul"]):
                if attempt == 1:
                    print("api_print_start: Yazıcı busy döndü, proaktif clear_platform çalıştırılıyor...")
                    await loop.run_in_executor(
                        None, _clear_platform_sync, PRINTER_HOST, PRINTER_PORT, PRINTER_SERIAL, PRINTER_CHECK_CODE
                    )
                await asyncio.sleep(2.0)
                continue
            else:
                await asyncio.sleep(1.0)
        except Exception as e:
            start_err_msg = str(e)
            await asyncio.sleep(1.0)

    # HTTP /printGcode başarısız olduysa TCP port 8899 M23/M24 fallback dene
    if not start_success:
        print(f"api_print_start: /printGcode başlatamadı ({start_err_msg}), TCP ~M23 / ~M24 fallback deneniyor...")
        try:
            m23_cmd = f"~M23 0:/user/{clean_name}\r\n".encode("utf-8")
            tcp_res = await send_command(m23_cmd)
            print(f"TCP M23 fallback response: {tcp_res}")
            if b"File selected" in tcp_res or b"File opened" in tcp_res:
                m24_res = await send_command(b"~M24\r\n")
                print(f"TCP M24 fallback response: {m24_res}")
                if b"ok" in m24_res or b"CMD" in m24_res:
                    start_success = True
        except Exception as tcp_e:
            print(f"api_print_start TCP fallback error: {tcp_e}")

    if start_success:
        async with lock:
            last_status["platform_clean_needed"] = False
            last_status["is_completed"] = False
            last_status["current_file"] = clean_name
        asyncio.create_task(refresh_once())
        return {"ok": True, "message": f"'{clean_name}' baskısı başarıyla başlatıldı."}
    else:
        return JSONResponse({"ok": False, "error": f"Baskı başlatılamadı: {start_err_msg}"}, status_code=500)


GCODE_CACHE_DIR = os.path.join(BASE_DIR, "gcode_cache")
os.makedirs(GCODE_CACHE_DIR, exist_ok=True)


def strip_all_gcode_extensions(filename: str) -> str:
    """Strips compound extensions like .gcode.3mf, .gcode, .3mf, .gx, etc."""
    s = os.path.basename(filename).strip()
    for ext in [".gcode.3mf", ".gcode", ".3mf", ".gx", ".gco", ".g"]:
        if s.lower().endswith(ext):
            s = s[:-len(ext)]
            break
    return s


def save_to_gcode_cache(filename: str, file_bytes: bytes) -> str:
    """Saves uploaded or downloaded file to local cache. If it's a .3mf or .gx, extracts and saves the internal pure .gcode too."""
    clean_name = os.path.basename(filename).strip()
    if not clean_name or not file_bytes:
        return ""
    main_path = os.path.join(GCODE_CACHE_DIR, clean_name)
    with open(main_path, "wb") as f:
        f.write(file_bytes)
        
    base_stem = strip_all_gcode_extensions(clean_name)
    gcode_extracted_name = None

    # 1. Check if it's a .3mf or ZIP archive (by magic bytes PK\x03\x04 or extension)
    is_zip = file_bytes.startswith(b"PK\x03\x04") or clean_name.lower().endswith(".3mf")
    if is_zip:
        try:
            with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
                gcode_candidates = [n for n in z.namelist() if n.lower().endswith(".gcode") or n.lower().endswith(".g")]
                if gcode_candidates:
                    chosen = max(gcode_candidates, key=lambda n: z.getinfo(n).file_size)
                    gcode_data = z.read(chosen)
                    gcode_extracted_name = base_stem + ".gcode"
                    with open(os.path.join(GCODE_CACHE_DIR, gcode_extracted_name), "wb") as gf:
                        gf.write(gcode_data)
        except Exception as ze:
            print(f"Error extracting G-code from .3mf: {ze}")

    # 2. Check if it's a FlashPrint .gx file
    elif clean_name.lower().endswith(".gx") or file_bytes.startswith(b"fff\x00") or file_bytes.startswith(b"gx\x00"):
        try:
            markers = [b"\n;", b"\nG90", b"\nG91", b"\nM82", b"\nM83", b"\nM118", b"\nG28"]
            best_pos = -1
            for m in markers:
                idx = file_bytes.find(m)
                if idx != -1:
                    pos = idx + 1
                    if best_pos == -1 or pos < best_pos:
                        best_pos = pos
            if best_pos != -1:
                gcode_data = file_bytes[best_pos:]
                gcode_extracted_name = base_stem + ".gcode"
                with open(os.path.join(GCODE_CACHE_DIR, gcode_extracted_name), "wb") as gf:
                    gf.write(gcode_data)
        except Exception as gxe:
            print(f"Error extracting G-code from .gx: {gxe}")
            
    return gcode_extracted_name or clean_name


def find_cached_gcode(filename: str) -> str:
    """Finds matching cached gcode file, prioritizing extracted pure .gcode over container formats."""
    if not filename:
        return ""
    clean = os.path.basename(filename).strip()
    if not clean:
        return ""
        
    base_stem = strip_all_gcode_extensions(clean)
    candidates = [
        base_stem + ".gcode",
        clean if clean.lower().endswith(".gcode") else "",
        clean,
        clean + ".gcode",
        clean + ".3mf",
        base_stem + ".3mf",
        base_stem + ".gcode.3mf",
        clean + ".gx",
        base_stem + ".gx"
    ]
    candidates = [c for c in candidates if c]
    
    # 1. Exact match
    for cand in candidates:
        p = os.path.join(GCODE_CACHE_DIR, cand)
        if os.path.isfile(p) and os.path.getsize(p) > 0:
            return p
            
    # 2. Case-insensitive match in GCODE_CACHE_DIR
    try:
        existing = os.listdir(GCODE_CACHE_DIR)
        for cand in candidates:
            cand_lower = cand.lower()
            for f in existing:
                if f.lower() == cand_lower:
                    p = os.path.join(GCODE_CACHE_DIR, f)
                    if os.path.isfile(p) and os.path.getsize(p) > 0:
                        return p

        # 3. Fuzzy normalized match (ignoring spaces, underscores, dashes, extensions)
        def _norm(name):
            s = strip_all_gcode_extensions(name).lower()
            return re.sub(r'[\s\-_\.]+', '', s)

        target_norm = _norm(clean)
        if target_norm:
            for f in existing:
                if _norm(f) == target_norm:
                    p = os.path.join(GCODE_CACHE_DIR, f)
                    if os.path.isfile(p) and os.path.getsize(p) > 0:
                        return p

            # 4. Prefix match (e.g. filename without timestamp or plate suffix)
            for f in existing:
                f_norm = _norm(f)
                if (target_norm.startswith(f_norm) or f_norm.startswith(target_norm)) and len(min(target_norm, f_norm)) >= 6:
                    p = os.path.join(GCODE_CACHE_DIR, f)
                    if os.path.isfile(p) and os.path.getsize(p) > 0:
                        return p
    except Exception:
        pass
        
    return ""


def _download_from_printer_sync(host: str, filename: str, serial: str = "", check_code: str = "") -> bytes:
    """Attempts to fetch the G-code/3MF file directly from printer via FTP (port 21) or HTTP (port 8898)."""
    import urllib.request
    import urllib.parse
    
    # Normalize filename, stripping any drive prefix (e.g. 0:/data/...)
    clean_name = filename.replace("\\", "/").split("/")[-1].strip()
    if not clean_name:
        return None

    name_without_ext = os.path.splitext(clean_name)[0].lower()

    # 1. Try FTP on port 21 (FlashForge default internal storage)
    try:
        from ftplib import FTP
        import io

        # Build candidate authentication pairs
        auth_pairs = [("admin", ""), ("anonymous", "")]
        if check_code:
            auth_pairs.insert(0, ("admin", check_code))
            auth_pairs.append(("root", check_code))
        auth_pairs.append(("", ""))

        for user, pw in auth_pairs:
            try:
                ftp = FTP(timeout=3)
                ftp.connect(host, 21, timeout=3)
                ftp.login(user, pw)
                
                candidate_paths = [
                    f"/data/{clean_name}",
                    f"/{clean_name}",
                    f"/data/gcode/{clean_name}",
                    f"/data/user/{clean_name}",
                    f"/data/{name_without_ext}.gcode",
                    f"/data/{name_without_ext}.3mf",
                    f"/data/{name_without_ext}.gx"
                ]

                # Scan remote directories to locate the file dynamically
                for scan_dir in ["/data", "/data/user", "/"]:
                    try:
                        remote_files = ftp.nlst(scan_dir)
                        for r_file in remote_files:
                            base_entry = r_file.replace("\\", "/").split("/")[-1]
                            if (base_entry.lower() == clean_name.lower() or 
                                base_entry.lower().startswith(name_without_ext)):
                                full_p = r_file if r_file.startswith('/') else f"{scan_dir}/{r_file}"
                                if full_p not in candidate_paths:
                                    candidate_paths.insert(0, full_p)
                    except Exception:
                        pass

                for c_path in candidate_paths:
                    buf = io.BytesIO()
                    try:
                        ftp.retrbinary(f"RETR {c_path}", buf.write)
                        val = buf.getvalue()
                        if val and len(val) > 10:
                            ftp.quit()
                            return val
                    except Exception:
                        pass
                ftp.quit()
            except Exception:
                pass
    except Exception as e:
        print(f"FTP download attempt error: {e}")

    # 2. Try HTTP endpoints on port 8898 (orcaServer)
    encoded_name = urllib.parse.quote(clean_name)
    endpoints = [
        f"http://{host}:8898/downloadGcode?filename={encoded_name}&serialNo={serial}&checkCode={check_code}",
        f"http://{host}:8898/download?filename={encoded_name}",
        f"http://{host}:8898/getFile?filename={encoded_name}",
        f"http://{host}:8898/gcode/{encoded_name}",
        f"http://{host}:8898/{encoded_name}"
    ]
    for url in endpoints:
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "serialNumber": serial,
                    "serialNo": serial,
                    "checkCode": check_code,
                    "User-Agent": "Mozilla/5.0 FlashForge-Panel/1.0"
                }
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = resp.read()
                if data and len(data) > 50 and not data.startswith(b"<!DOCTYPE") and not data.startswith(b"{\"code\":-"):
                    return data
        except Exception:
            pass

    return None


@app.get("/api/gcode/current")
async def api_gcode_current():
    """Returns the cached G-code file content for the currently printing file, or fetches from printer."""
    async with lock:
        current_file = last_status.get("current_file", "")
        
    # If not present in last_status, perform a live M119 check directly
    if not current_file or current_file in ["-", "Boşta", "UNKNOWN"]:
        try:
            raw_m119 = await send_command(b"~M119\r\n")
            m119_text = raw_m119.decode("utf-8", errors="ignore") if isinstance(raw_m119, bytes) else str(raw_m119)
            p119 = parse_m119(m119_text)
            if p119.get("current_file"):
                current_file = p119["current_file"]
                async with lock:
                    last_status["current_file"] = current_file
        except Exception:
            pass

    clean_name = current_file.replace("\\", "/").split("/")[-1].strip()
    if not clean_name or clean_name in ["-", "Boşta", "UNKNOWN"]:
        return JSONResponse({"ok": False, "error": "Şu an yazıcıda aktif bir baskı dosyası yok."}, status_code=404)
        
    cached_path = find_cached_gcode(clean_name)
    
    # If not in cache, try downloading directly from printer
    if not cached_path:
        loop = asyncio.get_event_loop()
        downloaded_bytes = await loop.run_in_executor(
            None, _download_from_printer_sync, PRINTER_HOST, clean_name, PRINTER_SERIAL, PRINTER_CHECK_CODE
        )
        if downloaded_bytes:
            save_to_gcode_cache(clean_name, downloaded_bytes)
            cached_path = find_cached_gcode(clean_name)

    if not cached_path:
        return JSONResponse({
            "ok": False, 
            "error": f"'{clean_name}' dosyası yazıcıdan veya sunucu önbelleğinden otomatik çekilemedi.",
            "current_file": clean_name,
            "prompt_upload": True
        }, status_code=404)
        
    # Ensure that if cached_path is a container (.3mf or .gx), we extract and serve the pure .gcode
    base_stem = os.path.splitext(cached_path)[0]
    gcode_equiv = base_stem + ".gcode"
    if os.path.isfile(gcode_equiv) and os.path.getsize(gcode_equiv) > 0:
        cached_path = gcode_equiv
    elif cached_path.lower().endswith(".3mf") or cached_path.lower().endswith(".gx"):
        try:
            with open(cached_path, "rb") as f:
                data = f.read()
            extracted = save_to_gcode_cache(os.path.basename(cached_path), data)
            if extracted and os.path.isfile(os.path.join(GCODE_CACHE_DIR, extracted)):
                cached_path = os.path.join(GCODE_CACHE_DIR, extracted)
        except Exception as e:
            print(f"Error auto-extracting gcode on serve: {e}")
                
    return FileResponse(
        cached_path, 
        media_type="text/plain; charset=utf-8", 
        filename=os.path.basename(cached_path),
        headers={"X-Gcode-Filename": os.path.basename(cached_path)}
    )


@app.get("/api/gcode/file/{filename}")
async def api_gcode_file(filename: str):
    """Returns a specific cached G-code file, auto-extracting pure .gcode if given a container."""
    cached_path = find_cached_gcode(filename)
    if not cached_path:
        return JSONResponse({"ok": False, "error": "Dosya bulunamadı."}, status_code=404)
        
    base_stem = os.path.splitext(cached_path)[0]
    gcode_equiv = base_stem + ".gcode"
    if os.path.isfile(gcode_equiv) and os.path.getsize(gcode_equiv) > 0:
        cached_path = gcode_equiv
    elif cached_path.lower().endswith(".3mf") or cached_path.lower().endswith(".gx"):
        try:
            with open(cached_path, "rb") as f:
                data = f.read()
            extracted = save_to_gcode_cache(os.path.basename(cached_path), data)
            if extracted and os.path.isfile(os.path.join(GCODE_CACHE_DIR, extracted)):
                cached_path = os.path.join(GCODE_CACHE_DIR, extracted)
        except Exception:
            pass

    return FileResponse(
        cached_path, 
        media_type="text/plain; charset=utf-8", 
        filename=os.path.basename(cached_path),
        headers={"X-Gcode-Filename": os.path.basename(cached_path)}
    )


@app.get("/api/gcode/list")
async def api_gcode_list():
    """Lists cached G-code files."""
    files = []
    try:
        for f in os.listdir(GCODE_CACHE_DIR):
            p = os.path.join(GCODE_CACHE_DIR, f)
            if os.path.isfile(p) and (f.lower().endswith(".gcode") or f.lower().endswith(".3mf")):
                stat = os.stat(p)
                files.append({
                    "name": f,
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                })
        files.sort(key=lambda x: x["modified"], reverse=True)
    except Exception as e:
        print(f"Error listing gcode cache: {e}")
    return {"ok": True, "files": files}


@app.post("/api/gcode/cache")
async def api_gcode_cache(request: Request, filename: str):
    """Saves a G-code or 3MF file to local cache for 3D viewing without printing."""
    try:
        body = await request.body()
        if not body:
            return JSONResponse({"ok": False, "error": "Boş dosya."}, status_code=400)
        saved_name = save_to_gcode_cache(filename, body)
        return {"ok": True, "filename": saved_name}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


class SettingsModel(BaseModel):
    host: str
    port: int
    serial: str
    check_code: str
    timelapse_mode: Optional[str] = "hybrid"
    timelapse_interval: Optional[int] = 10


@app.get("/api/settings")
async def get_settings():
    async with lock:
        tl_mode = last_status.get("timelapse_mode", "hybrid")
        tl_interval = last_status.get("timelapse_interval", 10)
        if 'timelapse_manager' in globals():
            tl_mode = timelapse_manager.capture_mode or tl_mode
            tl_interval = timelapse_manager.capture_interval or tl_interval
        return {
            "host": PRINTER_HOST,
            "port": PRINTER_PORT,
            "serial": PRINTER_SERIAL,
            "check_code": PRINTER_CHECK_CODE,
            "timelapse_mode": tl_mode,
            "timelapse_interval": tl_interval,
            "tcp_error": last_status.get("error"),
            "ifs_error": last_status.get("filament_info_error")
        }


@app.post("/api/settings")
async def post_settings(settings: SettingsModel):
    save_config(
        settings.host,
        settings.port,
        settings.serial,
        settings.check_code,
        timelapse_mode=settings.timelapse_mode,
        timelapse_interval=settings.timelapse_interval
    )
    if 'camera_broadcaster' in globals() and camera_broadcaster:
        camera_broadcaster.reset()
    try:
        await refresh_once()
    except Exception:
        pass
    return {"ok": True, "message": "Ayarlar kaydedildi."}


@app.get("/api/printer/discover")
async def api_printer_discover(subnet: Optional[str] = None):
    """Scans local network and returns list of discovered FlashForge printers."""
    try:
        printers = await discover_printers_on_network(custom_subnet=subnet)
        return {
            "ok": True,
            "count": len(printers),
            "printers": printers,
            "current_host": PRINTER_HOST,
            "detected_subnets": get_local_ip_subnets()
        }
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"Ağ taraması sırasında hata oluştu: {e}"}, status_code=500)


class SelectIpModel(BaseModel):
    ip: str
    port: Optional[int] = 8899
    serial: Optional[str] = None
    check_code: Optional[str] = None


@app.post("/api/printer/select_ip")
async def api_printer_select_ip(payload: SelectIpModel):
    """Updates the active printer host IP and re-establishes connections."""
    global PRINTER_HOST, PRINTER_PORT, PRINTER_SERIAL, PRINTER_CHECK_CODE
    new_ip = payload.ip.strip()
    new_port = payload.port or 8899
    new_serial = payload.serial or PRINTER_SERIAL
    new_check = payload.check_code or PRINTER_CHECK_CODE

    if not new_ip:
        return JSONResponse({"ok": False, "error": "Geçerli bir IP adresi girilmedi."}, status_code=400)

    save_config(new_ip, new_port, new_serial, new_check)
    if 'camera_broadcaster' in globals() and camera_broadcaster:
        camera_broadcaster.reset()

    # Trigger immediate status refresh
    try:
        await refresh_once()
    except Exception as e:
        print(f"Post-switch refresh error: {e}")

    return {
        "ok": True,
        "message": f"Yazıcı IP adresi '{new_ip}' olarak güncellendi ve bağlantı kuruldu.",
        "host": PRINTER_HOST,
        "port": PRINTER_PORT,
        "serial": PRINTER_SERIAL
    }
    if 'timelapse_manager' in globals():
        timelapse_manager.capture_mode = settings.timelapse_mode or "hybrid"
        timelapse_manager.capture_interval = int(settings.timelapse_interval or 10)
    try:
        camera_broadcaster.reset()
    except Exception:
        pass
    # Trigger an immediate background check to reflect new settings
    asyncio.create_task(refresh_once())
    return {"ok": True}


@app.post("/api/service/restart")
async def api_service_restart(full_reload: bool = False):
    """Restarts background polling tasks, resets camera broadcaster, releases sockets and forces an immediate reconnect."""
    global watch_task
    try:
        # Reset camera broadcaster
        try:
            camera_broadcaster.reset()
        except Exception:
            pass
        
        # Release printer session if locked
        try:
            await send_command(b"~M602\r\n")
        except Exception:
            pass
            
        # Cancel and recreate watch task
        if watch_task and not watch_task.done():
            watch_task.cancel()
        watch_task = asyncio.create_task(watch_loop())
        
        # Trigger immediate refresh
        asyncio.create_task(refresh_once())
        
        if full_reload:
            def _delayed_exit():
                time.sleep(0.6)
                os._exit(0)
            threading.Thread(target=_delayed_exit, daemon=True).start()
            return {"ok": True, "message": "Panel servisi tamamen yeniden başlatılıyor (Sistem Süreci)..."}

        return {"ok": True, "message": "Panel arka plan servisleri ve kamera yayıncısı başarıyla yeniden başlatıldı."}
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"Servisler yeniden başlatılamadı: {e}"}, status_code=500)


@app.post("/api/printer/restart")
async def api_printer_restart():
    """Sends firmware / machine restart command (~M999 / FIRMWARE_RESTART) to the printer."""
    try:
        # Send M999 with login/logout
        raw = await send_command(b"~M999\r\n")
        try:
            await send_command(b"~FIRMWARE_RESTART\r\n")
        except Exception:
            pass
        
        # Reset backend state & camera
        try:
            camera_broadcaster.reset()
        except Exception:
            pass
        asyncio.create_task(refresh_once())
        
        return {"ok": True, "message": "Yazıcı yeniden başlatma komutu (~M999) gönderildi."}
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"Yazıcıya komut gönderilemedi: {e}"}, status_code=500)


@app.post("/api/printer/unlock")
async def api_printer_unlock():
    """Releases active TCP control session (~M602) to unblock the printer."""
    try:
        raw = await send_command(b"~M602\r\n")
        res_str = raw.decode("utf-8", errors="ignore") if isinstance(raw, bytes) else str(raw)
        return {"ok": True, "message": "Yazıcı kontrol oturumu serbest bırakıldı (~M602).", "response": res_str.strip()}
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"Oturum serbest bırakılamadı: {e}"}, status_code=500)


@app.post("/api/camera/restart")
async def api_camera_restart():
    """Resets the camera broadcaster and forces re-establishing stream to printer."""
    try:
        camera_broadcaster.reset()
        return {"ok": True, "message": "Kamera proxy servisi sıfırlandı ve yeniden başlatıldı."}
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"Kamera servisi sıfırlanamadı: {e}"}, status_code=500)


class CameraBroadcaster:
    def __init__(self):
        self.subscribers = set()
        self.thread = None
        self.stop_event = threading.Event()
        self.lock = asyncio.Lock()
        self.latest_frame = None
        self.latest_frame_time = None
        self.is_connected = False
        self.last_error = None
        self.loop = None

    def reset(self):
        """Reset connection on host change or manual reconnect."""
        self.stop_event.set()
        self.thread = None
        self.is_connected = False
        self.latest_frame = None

    def _worker(self, host, loop):
        camera_url = f"http://{host}:8080/?action=stream"
        
        while not self.stop_event.is_set():
            resp = None
            try:
                req = urllib.request.Request(
                    camera_url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) FlashForge-Panel/1.0",
                        "Accept": "*/*"
                    }
                )
                resp = urllib.request.urlopen(req, timeout=6)
                self.is_connected = True
                self.last_error = None
                
                buffer = bytearray()
                while not self.stop_event.is_set():
                    chunk = resp.read(8192)
                    if not chunk:
                        break
                    buffer.extend(chunk)
                    
                    while True:
                        start = buffer.find(b"\xff\xd8")
                        if start == -1:
                            if len(buffer) > 131072:
                                buffer = buffer[-8192:]
                            break
                        end = buffer.find(b"\xff\xd9", start + 2)
                        if end == -1:
                            if start > 0:
                                buffer = buffer[start:]
                            break
                        jpg = bytes(buffer[start:end+2])
                        buffer = buffer[end+2:]
                        
                        self.latest_frame = jpg
                        self.latest_frame_time = datetime.now()
                        
                        # Deliver frame to async subscribers
                        frame_payload = (
                            b"--frame\r\n"
                            b"Content-Type: image/jpeg\r\n"
                            b"Content-Length: " + str(len(jpg)).encode("ascii") + b"\r\n\r\n"
                            + jpg + b"\r\n"
                        )
                        if loop and not loop.is_closed():
                            try:
                                loop.call_soon_threadsafe(self._dispatch_frame, frame_payload)
                            except Exception:
                                pass
                        
            except Exception as e:
                self.last_error = str(e)
                self.is_connected = False
            finally:
                if resp:
                    try:
                        resp.close()
                    except Exception:
                        pass
                        
            # If stopped, exit worker
            if self.stop_event.is_set():
                break
            # Backoff before reconnect
            self.stop_event.wait(2.0)
            
        self.is_connected = False
        if loop and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(self._notify_closed)
            except Exception:
                pass

    def _dispatch_frame(self, frame_payload):
        dead = set()
        for q in list(self.subscribers):
            try:
                if q.full():
                    try:
                        q.get_nowait()
                    except Exception:
                        pass
                q.put_nowait(frame_payload)
            except Exception:
                dead.add(q)
        self.subscribers -= dead

    def _notify_closed(self):
        for q in list(self.subscribers):
            try:
                q.put_nowait(None)
            except Exception:
                pass

    async def subscribe(self):
        q = asyncio.Queue(maxsize=5)
        self.loop = asyncio.get_running_loop()
        
        async with self.lock:
            # If we have a cached frame, send it immediately
            if self.latest_frame:
                frame_payload = (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Content-Length: " + str(len(self.latest_frame)).encode("ascii") + b"\r\n\r\n"
                    + self.latest_frame + b"\r\n"
                )
                try:
                    q.put_nowait(frame_payload)
                except Exception:
                    pass

            self.subscribers.add(q)
            if self.thread is None or not self.thread.is_alive():
                self.stop_event.clear()
                self.thread = threading.Thread(
                    target=self._worker,
                    args=(PRINTER_HOST, self.loop),
                    daemon=True,
                    name="CameraBroadcasterThread"
                )
                self.thread.start()
        return q

    def ensure_started(self):
        """Ensures the background stream worker is actively receiving frames."""
        if self.thread is None or not self.thread.is_alive():
            self.stop_event.clear()
            loop = None
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = self.loop
            self.thread = threading.Thread(
                target=self._worker,
                args=(PRINTER_HOST, loop),
                daemon=True,
                name="CameraBroadcasterThread"
            )
            self.thread.start()

    async def unsubscribe(self, q):
        async with self.lock:
            self.subscribers.discard(q)
            is_timelapse_active = bool('timelapse_manager' in globals() and timelapse_manager and timelapse_manager.active_session)
            if not self.subscribers and not is_timelapse_active:
                self.stop_event.set()
                self.thread = None


camera_broadcaster = CameraBroadcaster()


def fetch_camera_snapshot_sync(timeout: float = 3.5) -> bytes:
    """Fetches a single JPEG frame snapshot from camera broadcaster cache or direct printer stream."""
    global camera_broadcaster
    # 1. Use cached broadcaster frame if recent (within 3.0 seconds)
    if camera_broadcaster and camera_broadcaster.latest_frame and camera_broadcaster.latest_frame_time:
        age = (datetime.now() - camera_broadcaster.latest_frame_time).total_seconds()
        if age < 3.0:
            return camera_broadcaster.latest_frame

    # 2. Try direct ?action=snapshot
    try:
        url = f"http://{PRINTER_HOST}:8080/?action=snapshot"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) FlashForge-Panel/1.0", "Accept": "*/*"}
        )
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            data = resp.read()
            if data and len(data) > 1000 and data.startswith(b"\xff\xd8"):
                if camera_broadcaster:
                    camera_broadcaster.latest_frame = data
                    camera_broadcaster.latest_frame_time = datetime.now()
                return data
    except Exception:
        pass

    # 3. Stream 1 frame from ?action=stream
    try:
        stream_url = f"http://{PRINTER_HOST}:8080/?action=stream"
        req = urllib.request.Request(
            stream_url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) FlashForge-Panel/1.0", "Accept": "*/*"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            buf = bytearray()
            for _ in range(80):
                c = resp.read(8192)
                if not c:
                    break
                buf.extend(c)
                start = buf.find(b"\xff\xd8")
                if start != -1:
                    end = buf.find(b"\xff\xd9", start + 2)
                    if end != -1:
                        jpg = bytes(buf[start:end+2])
                        if camera_broadcaster:
                            camera_broadcaster.latest_frame = jpg
                            camera_broadcaster.latest_frame_time = datetime.now()
                        return jpg
    except Exception as e:
        print(f"fetch_camera_snapshot_sync fallback error: {e}")
    return None


@app.get("/api/camera/status")
async def api_camera_status():
    """Returns the current camera proxy status and direct URL."""
    return {
        "ok": True,
        "connected": camera_broadcaster.is_connected,
        "printer_host": PRINTER_HOST,
        "direct_stream_url": f"http://{PRINTER_HOST}:8080/?action=stream",
        "direct_snapshot_url": f"http://{PRINTER_HOST}:8080/?action=snapshot",
        "last_error": camera_broadcaster.last_error,
        "has_frame": camera_broadcaster.latest_frame is not None
    }


@app.get("/api/camera/stream")
async def api_camera_stream():
    """Proxy the MJPEG camera stream from the printer through a multi-client broadcaster."""
    try:
        q = await camera_broadcaster.subscribe()
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"Kamera yayını başlatılamadı: {e}"}, status_code=502)

    async def client_generator():
        try:
            while True:
                chunk = await q.get()
                if chunk is None:
                    break
                yield chunk
        except asyncio.CancelledError:
            pass
        finally:
            await camera_broadcaster.unsubscribe(q)

    headers = {
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
    }
    return StreamingResponse(
        client_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers=headers
    )


@app.get("/api/camera/snapshot")
async def api_camera_snapshot():
    """Proxy a single camera frame snapshot from the printer or latest broadcaster cache."""
    loop = asyncio.get_running_loop()
    img_bytes = await loop.run_in_executor(None, fetch_camera_snapshot_sync)
    if img_bytes:
        return Response(
            content=img_bytes,
            media_type="image/jpeg",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
        )
    return JSONResponse({"ok": False, "error": "Kamera görüntüsü alınamadı"}, status_code=502)


# ---------------------------------------------------------
# TIME-LAPSE RECORDING & MANAGEMENT ENGINE
# ---------------------------------------------------------

TIMELAPSE_DIR = os.path.join(BASE_DIR, "timelapse_recordings")
os.makedirs(TIMELAPSE_DIR, exist_ok=True)


class TimeLapseManager:
    """Automated Time-Lapse frame capture, compilation, and gallery management engine."""
    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)
        self.active_session = None
        self.lock = threading.Lock()
        self.last_captured_layer = -1
        self.last_captured_time = 0
        self.recording_enabled = True
        self.capture_mode = "hybrid"   # "hybrid", "time", "layer"
        self.capture_interval = 10     # seconds between frames (time/hybrid)
        self.pending_filename = None
        self.consecutive_idle_count = 0
        self._recover_stale_sessions()

    def _recover_stale_sessions(self):
        """Finalize any sessions that were left in 'recording' state if server crashed/restarted, and clean trash."""
        try:
            for item in os.listdir(self.base_dir):
                item_path = os.path.join(self.base_dir, item)
                if item.startswith('.') or item.startswith('_trash'):
                    try:
                        shutil.rmtree(item_path, ignore_errors=True)
                    except Exception:
                        pass
                    continue
                if os.path.isdir(item_path):
                    meta_path = os.path.join(item_path, "metadata.json")
                    if os.path.exists(meta_path):
                        try:
                            with open(meta_path, "r", encoding="utf-8") as f:
                                meta = json.load(f)
                            if meta.get("status") == "recording":
                                frames_dir = os.path.join(item_path, "frames")
                                if os.path.exists(frames_dir) and len(os.listdir(frames_dir)) >= 1:
                                    print(f"TimeLapse: Recovering unfinalized session {item}...")
                                    threading.Thread(target=self._compile_worker, args=(meta,), daemon=True).start()
                                else:
                                    meta["status"] = "cancelled"
                                    self._save_metadata(meta)
                        except Exception:
                            pass
        except Exception as e:
            print(f"Error recovering stale timelapse sessions: {e}")

    def _get_deleted_sessions(self) -> set:
        f_path = os.path.join(self.base_dir, ".deleted_sessions.json")
        if os.path.exists(f_path):
            try:
                with open(f_path, "r", encoding="utf-8") as f:
                    return set(json.load(f))
            except Exception:
                pass
        return set()

    def _mark_session_deleted(self, session_id: str):
        try:
            s_set = self._get_deleted_sessions()
            s_set.add(session_id)
            f_path = os.path.join(self.base_dir, ".deleted_sessions.json")
            with open(f_path, "w", encoding="utf-8") as f:
                json.dump(list(s_set), f)
        except Exception as e:
            print(f"TimeLapse: Error saving deleted session marker: {e}")

    def get_recordings(self) -> list:
        recordings = []
        deleted_set = self._get_deleted_sessions()
        try:
            for item in os.listdir(self.base_dir):
                if item.startswith('.') or item.startswith('_trash') or item in deleted_set:
                    continue
                item_path = os.path.join(self.base_dir, item)
                if os.path.isdir(item_path):
                    meta_file = os.path.join(item_path, "metadata.json")
                    if os.path.exists(meta_file):
                        try:
                            with open(meta_file, "r", encoding="utf-8") as mf:
                                meta = json.load(mf)
                            meta["id"] = item
                            v_file = meta.get("video_file", "timelapse.webp")
                            v_path = os.path.join(item_path, v_file)
                            has_video = os.path.exists(v_path) and os.path.getsize(v_path) > 100
                            
                            frames_dir = os.path.join(item_path, "frames")
                            frame_count = meta.get("frame_count") or meta.get("captured_frames") or 0
                            if os.path.exists(frames_dir):
                                disk_frames = len([f for f in os.listdir(frames_dir) if f.lower().endswith(".jpg")])
                                if disk_frames > frame_count:
                                    frame_count = disk_frames

                            meta["frame_count"] = frame_count
                            meta["captured_frames"] = frame_count

                            f_size = os.path.getsize(v_path) if os.path.exists(v_path) else meta.get("file_size", 0)
                            meta["file_size"] = f_size
                            meta["file_size_human"] = meta.get("file_size_human") or format_bytes(f_size)
                            meta["has_video"] = has_video

                            # Unified date field
                            end_t = meta.get("end_time")
                            start_t = meta.get("start_time")
                            if isinstance(end_t, (int, float)):
                                meta["date"] = datetime.fromtimestamp(end_t).strftime("%d.%m.%Y %H:%M")
                            elif isinstance(start_t, (int, float)):
                                meta["date"] = datetime.fromtimestamp(start_t).strftime("%d.%m.%Y %H:%M")
                            else:
                                meta["date"] = meta.get("date") or meta.get("start_time_str") or ""

                            recordings.append(meta)
                        except Exception:
                            pass
                    else:
                        frames_dir = os.path.join(item_path, "frames")
                        if os.path.exists(frames_dir):
                            disk_frames = len([f for f in os.listdir(frames_dir) if f.lower().endswith(".jpg")])
                            if disk_frames > 0:
                                v_path = os.path.join(item_path, "timelapse.webp")
                                has_video = os.path.exists(v_path) and os.path.getsize(v_path) > 100
                                f_size = os.path.getsize(v_path) if has_video else 0
                                recordings.append({
                                    "id": item,
                                    "filename": item,
                                    "frame_count": disk_frames,
                                    "captured_frames": disk_frames,
                                    "date": "",
                                    "has_video": has_video,
                                    "file_size": f_size,
                                    "file_size_human": format_bytes(f_size),
                                    "status": "completed" if has_video else "stopped"
                                })
            recordings.sort(key=lambda x: str(x.get("start_time", "") or x.get("date", "") or x.get("id", "")), reverse=True)
        except Exception as e:
            print(f"Error listing timelapses: {e}")
        return recordings

    def get_active_session_info(self) -> dict:
        with self.lock:
            if self.active_session:
                now_t = time.time()
                start_t = self.active_session.get("start_time")
                elapsed = int(now_t - start_t) if isinstance(start_t, (int, float)) else 0
                return {
                    "id": self.active_session.get("id"),
                    "filename": self.active_session.get("filename"),
                    "start_time": self.active_session.get("start_time"),
                    "start_time_str": self.active_session.get("start_time_str"),
                    "captured_frames": self.active_session.get("captured_frames", 0),
                    "frame_count": self.active_session.get("captured_frames", 0),
                    "current_layer": self.last_captured_layer,
                    "total_layers": self.active_session.get("total_layers", 0),
                    "mode": self.active_session.get("mode", self.capture_mode),
                    "interval": self.active_session.get("interval", self.capture_interval),
                    "status": "recording",
                    "is_recording": True,
                    "elapsed_seconds": elapsed
                }
            return None

    def start_session(self, filename: str, total_layers: int = 0, mode: str = None, interval: int = None):
        with self.lock:
            # If already recording this exact session, don't restart
            if self.active_session and self.active_session.get("filename") == filename:
                return

            clean_name = os.path.splitext(os.path.basename(filename.replace("\\", "/")))[0]
            clean_name = re.sub(r'[^\w\-_\.]', '_', clean_name).strip("._") or "print"
            now_dt = datetime.now()
            now_str = now_dt.strftime("%Y%m%d_%H%M%S")
            now_epoch = time.time()
            session_id = f"{now_str}_{clean_name}"
            session_path = os.path.join(self.base_dir, session_id)
            frames_path = os.path.join(session_path, "frames")
            try:
                os.makedirs(frames_path, exist_ok=True)
                if os.name != 'nt':
                    try:
                        os.chmod(session_path, 0o777)
                        os.chmod(frames_path, 0o777)
                    except Exception:
                        pass
            except Exception as e:
                print(f"TimeLapse: Error creating directory '{frames_path}': {e}")

            chosen_mode = mode or self.capture_mode or "hybrid"
            try:
                chosen_interval = int(interval) if interval is not None else int(self.capture_interval or 10)
            except Exception:
                chosen_interval = 10

            try:
                tot_l = int(total_layers or 0)
            except Exception:
                tot_l = 0

            self.active_session = {
                "id": session_id,
                "filename": filename,
                "start_time": now_epoch,
                "start_time_str": now_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "end_time": None,
                "end_time_str": None,
                "date": now_dt.strftime("%d.%m.%Y %H:%M"),
                "total_layers": tot_l,
                "captured_frames": 0,
                "frame_count": 0,
                "status": "recording",
                "mode": chosen_mode,
                "interval": chosen_interval,
                "duration_seconds": 0,
                "thumbnail": "thumbnail.jpg",
                "video_file": "timelapse.webp",
                "file_size": 0,
                "file_size_human": "0 B",
                "session_dir": session_path,
                "frames_dir": frames_path
            }
            self.last_captured_layer = -1
            self.last_captured_time = now_epoch
            self.consecutive_idle_count = 0
            self._save_metadata(self.active_session)
            print(f"TimeLapse: Started new session '{session_id}' for file '{filename}' (Mode: {chosen_mode}, Interval: {chosen_interval}s).")
            try:
                if 'camera_broadcaster' in globals() and camera_broadcaster:
                    camera_broadcaster.ensure_started()
            except Exception:
                pass

    def capture_frame(self, frame_bytes: bytes, layer_num: int = 0):
        if not frame_bytes or not self.active_session:
            return
        with self.lock:
            frames_dir = self.active_session.get("frames_dir")
            if not frames_dir or not os.path.exists(frames_dir):
                return
            frame_idx = int(self.active_session.get("captured_frames") or 0) + 1
            frame_filename = f"frame_{frame_idx:06d}.jpg"
            frame_path = os.path.join(frames_dir, frame_filename)
            try:
                with open(frame_path, "wb") as f:
                    f.write(frame_bytes)

                thumb_path = os.path.join(self.active_session["session_dir"], "thumbnail.jpg")
                if frame_idx == 1 or frame_idx % 10 == 0 or not os.path.exists(thumb_path):
                    with open(thumb_path, "wb") as tf:
                        tf.write(frame_bytes)

                self.active_session["captured_frames"] = frame_idx
                self.active_session["frame_count"] = frame_idx

                try:
                    cur_l = int(layer_num or 0)
                    tot_l = int(self.active_session.get("total_layers") or 0)
                    if cur_l > tot_l:
                        self.active_session["total_layers"] = cur_l
                    self.last_captured_layer = cur_l
                except Exception:
                    pass

                self.last_captured_time = time.time()
                self._save_metadata(self.active_session)
            except Exception as e:
                print(f"TimeLapse: Error saving frame {frame_idx}: {e}")

    def finalize_session(self):
        with self.lock:
            session = self.active_session
            self.active_session = None

        if not session:
            return

        now_epoch = time.time()
        session["end_time"] = now_epoch
        session["end_time_str"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        session["date"] = datetime.now().strftime("%d.%m.%Y %H:%M")
        try:
            start_t = session.get("start_time")
            if isinstance(start_t, (int, float)):
                session["duration_seconds"] = int(now_epoch - start_t)
            else:
                session["duration_seconds"] = 0
        except Exception:
            session["duration_seconds"] = 0

        self._save_metadata(session)
        threading.Thread(target=self._compile_worker, args=(session,), daemon=True).start()

    def _compile_worker(self, session: dict):
        session_dir = session["session_dir"]
        frames_dir = session["frames_dir"]
        if not os.path.exists(frames_dir):
            session["status"] = "skipped"
            self._save_metadata(session)
            return

        frame_files = sorted([f for f in os.listdir(frames_dir) if f.lower().endswith(".jpg")])
        if len(frame_files) == 0:
            print(f"TimeLapse: Session '{session['id']}' has 0 frames, skipping compilation.")
            session["status"] = "skipped"
            self._save_metadata(session)
            return

        print(f"TimeLapse: Compiling {len(frame_files)} frames for session '{session['id']}'...")
        out_webp = os.path.join(session_dir, "timelapse.webp")
        out_mp4 = os.path.join(session_dir, "timelapse.mp4")

        # 1. Try ffmpeg if available
        ffmpeg_bin = shutil.which("ffmpeg")
        compiled_mp4 = False
        if ffmpeg_bin:
            try:
                cmd = [
                    ffmpeg_bin, "-y",
                    "-framerate", "10",
                    "-i", os.path.join(frames_dir, "frame_%06d.jpg"),
                    "-c:v", "libx264",
                    "-pix_fmt", "yuv420p",
                    "-preset", "fast",
                    "-crf", "23",
                    out_mp4
                ]
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
                if os.path.exists(out_mp4) and os.path.getsize(out_mp4) > 100:
                    session["video_file"] = "timelapse.mp4"
                    session["file_size"] = os.path.getsize(out_mp4)
                    session["file_size_human"] = format_bytes(session["file_size"])
                    session["status"] = "completed"
                    compiled_mp4 = True
                    print(f"TimeLapse: ffmpeg MP4 compiled successfully! Size: {session['file_size']} bytes.")
            except Exception as fe:
                print(f"TimeLapse: ffmpeg compilation warning: {fe}")

        # 2. Always generate animated WebP for 100% browser native preview
        try:
            images = []
            for f in frame_files:
                f_path = os.path.join(frames_dir, f)
                try:
                    with Image.open(f_path) as opened_img:
                        img = opened_img.copy()
                    if img.width > 1280:
                        ratio = 1280.0 / img.width
                        img = img.resize((1280, int(img.height * ratio)), Image.LANCZOS)
                    images.append(img.convert("RGB"))
                except Exception as ie:
                    print(f"TimeLapse: Error reading frame {f}: {ie}")

            if images:
                images[0].save(
                    out_webp,
                    format="WEBP",
                    save_all=True,
                    append_images=images[1:],
                    duration=100,  # 10 fps
                    loop=0,
                    quality=80
                )
                if not compiled_mp4:
                    session["video_file"] = "timelapse.webp"
                    session["file_size"] = os.path.getsize(out_webp)
                    session["file_size_human"] = format_bytes(session["file_size"])
                    session["status"] = "completed"
                print(f"TimeLapse: WebP animation compiled successfully! Size: {os.path.getsize(out_webp)} bytes.")
        except Exception as we:
            print(f"TimeLapse: WebP compilation error: {we}")
            if not compiled_mp4:
                session["status"] = "error"

        session["frame_count"] = len(frame_files)
        session["captured_frames"] = len(frame_files)
        self._save_metadata(session)

    def _save_metadata(self, session: dict):
        try:
            meta_path = os.path.join(session["session_dir"], "metadata.json")
            session["frame_count"] = session.get("captured_frames", 0)
            if "file_size" in session and session["file_size"] > 0:
                session["file_size_human"] = format_bytes(session["file_size"])
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(session, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving timelapse metadata: {e}")

    def delete_session(self, session_id: str) -> bool:
        """Robustly delete a timelapse recording session on Windows and Linux."""
        clean_id = urllib.parse.unquote(str(session_id or "")).strip()
        clean_id = clean_id.replace("\\", "/").split("/")[-1].strip()
        if not clean_id or clean_id in [".", ".."]:
            return False

        with self.lock:
            if self.active_session and self.active_session.get("id") == clean_id:
                print(f"TimeLapse: Terminating active session '{clean_id}' due to deletion request.")
                self.active_session = None

        # Always mark deleted so it instantly vanishes from UI
        self._mark_session_deleted(clean_id)

        session_path = os.path.join(self.base_dir, clean_id)
        if not os.path.exists(session_path):
            return True

        import gc
        gc.collect()

        # POSIX rapid delete
        if os.name != 'nt':
            try:
                subprocess.run(["chmod", "-R", "777", session_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            except Exception:
                pass
            try:
                subprocess.run(["rm", "-rf", session_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            except Exception:
                pass
            if not os.path.exists(session_path):
                return True
            try:
                subprocess.run(["sudo", "-n", "rm", "-rf", session_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            except Exception:
                pass
            if not os.path.exists(session_path):
                return True

        def _remove_readonly(func, path, excinfo):
            try:
                os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
                func(path)
            except Exception:
                pass

        # Try up to 3 passes to unprotect and delete files
        for attempt in range(3):
            try:
                for root, dirs, files in os.walk(session_path, topdown=False):
                    for name in files:
                        p = os.path.join(root, name)
                        try:
                            os.chmod(p, stat.S_IWRITE | stat.S_IREAD)
                            os.remove(p)
                        except Exception:
                            pass
                    for name in dirs:
                        p = os.path.join(root, name)
                        try:
                            os.chmod(p, 0o777 if os.name != 'nt' else (stat.S_IWRITE | stat.S_IREAD))
                            os.rmdir(p)
                        except Exception:
                            pass

                if os.path.exists(session_path):
                    shutil.rmtree(session_path, onerror=_remove_readonly)
            except Exception as e:
                print(f"TimeLapse: Attempt {attempt + 1} deleting '{clean_id}' warning: {e}")

            if not os.path.exists(session_path):
                break
            time.sleep(0.1)
            gc.collect()

        # If directory is still lingering due to delayed OS file release, rename to hidden trash
        if os.path.exists(session_path):
            try:
                trash_dir = os.path.join(self.base_dir, f".trash_{clean_id}_{int(time.time())}")
                os.rename(session_path, trash_dir)
                shutil.rmtree(trash_dir, ignore_errors=True)
                print(f"TimeLapse: Session folder moved to trash '{trash_dir}'.")
            except Exception as te:
                print(f"TimeLapse: Fallback trash rename error: {te}")

        success = not os.path.exists(session_path)
        print(f"TimeLapse: delete_session('{clean_id}') disk result: {success}")
        return True

    def _fetch_direct_snapshot(self) -> bytes:
        """Fallback direct snapshot fetch via fetch_camera_snapshot_sync."""
        try:
            return fetch_camera_snapshot_sync(timeout=3.5)
        except Exception:
            return None

    def process_status(self, status: dict):
        """Called upon every status poll update to drive automated frame capture."""
        if not self.recording_enabled:
            return

        m_status = (status.get("machine_status") or "").strip().upper()
        s_flags = (status.get("status_flags") or "").strip().upper()
        detail_raw = status.get("detail_raw") or {}
        detail_status = str(detail_raw.get("status", "") or detail_raw.get("printStatus", "")).strip().lower()

        layer_val = str(status.get("layer") or "0/0")
        cur_layer, total_layer = (0, 0)
        if "/" in layer_val:
            try:
                parts = layer_val.split("/")
                cur_layer = int(parts[0].strip())
                total_layer = int(parts[1].strip())
            except Exception:
                pass

        if cur_layer == 0 and detail_raw.get("printLayer"):
            try:
                cur_layer = int(detail_raw.get("printLayer"))
                total_layer = int(detail_raw.get("targetPrintLayer") or total_layer)
            except Exception:
                pass

        try:
            progress_val = int(float(status.get("progress") or 0))
        except Exception:
            progress_val = 0

        is_printing_flag = bool(status.get("is_printing"))

        is_active_printing = (
            is_printing_flag or
            m_status in ["BUILDING", "BUILDING_FROM_SD", "BUILDING_ON_SD", "PRINTING", "HOMING", "PREHEAT", "HEATING", "BED_LEVELING", "CALIBRATING", "BUSY"] or
            detail_status in ["building", "printing"] or
            "S:1" in s_flags or
            (0 < progress_val < 100) or
            (cur_layer > 0)
        )
        is_completed = (
            status.get("is_completed", False) or 
            (m_status in ["BUILDING_COMPLETED", "COMPLETED", "FINISHED"]) or
            detail_status in ["completed", "finish", "finished"]
        )
        current_file = (status.get("current_file") or detail_raw.get("printFileName") or detail_raw.get("fileName") or "").strip()

        # 1. Start or maintain active session
        if is_active_printing:
            self.consecutive_idle_count = 0
            file_to_record = current_file
            if not file_to_record or file_to_record in ["-", "Boşta", "UNKNOWN"]:
                file_to_record = self.pending_filename or f"Baski_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

            if not self.active_session:
                self.start_session(file_to_record, total_layers=total_layer, mode=self.capture_mode, interval=self.capture_interval)
            elif current_file and current_file not in ["-", "Boşta", "UNKNOWN"] and self.active_session.get("filename") != current_file:
                # If active session was started with placeholder name (Baski_...), update filename without discarding frames!
                if self.active_session.get("filename", "").startswith("Baski_") or self.active_session.get("captured_frames", 0) <= 2:
                    self.active_session["filename"] = current_file
                    if total_layer > 0:
                        self.active_session["total_layers"] = total_layer
                    self._save_metadata(self.active_session)
                else:
                    self.finalize_session()
                    self.start_session(current_file, total_layers=total_layer, mode=self.capture_mode, interval=self.capture_interval)

            # 2. Check if a frame should be captured
            if self.active_session:
                now = time.time()
                should_capture = False
                mode = self.active_session.get("mode") or self.capture_mode or "hybrid"
                try:
                    interval = int(self.active_session.get("interval") or self.capture_interval or 10)
                except Exception:
                    interval = 10

                captured_cnt = int(self.active_session.get("captured_frames") or 0)

                # Capture first frame quickly after start
                if captured_cnt == 0 and (now - self.last_captured_time) >= 1.0:
                    should_capture = True
                # Layer change trigger (hybrid or layer mode)
                elif mode in ["hybrid", "layer"] and cur_layer > 0 and cur_layer != self.last_captured_layer:
                    should_capture = True
                # Time interval trigger (hybrid or time mode)
                elif mode in ["hybrid", "time"] and (now - self.last_captured_time) >= interval:
                    should_capture = True

                if should_capture:
                    frame = (camera_broadcaster.latest_frame if camera_broadcaster else None) or self._fetch_direct_snapshot()
                    if frame:
                        self.capture_frame(frame, layer_num=cur_layer)

        # 3. Finalize session if print has finished or printer transitioned to completed/idle with debounce
        elif self.active_session:
            if is_completed or m_status in ["CANCEL_BUILD", "CANCEL", "CANCELLED", "STOPPED", "ABORTED"]:
                print("TimeLapse: Print finished or completed. Finalizing timelapse recording...")
                self.finalize_session()
            else:
                self.consecutive_idle_count += 1
                if self.consecutive_idle_count >= 5:
                    print(f"TimeLapse: Printer idle for {self.consecutive_idle_count} polls. Finalizing recording...")
                    self.finalize_session()


timelapse_manager = TimeLapseManager(TIMELAPSE_DIR)
if "timelapse_mode" in last_status:
    timelapse_manager.capture_mode = last_status["timelapse_mode"]
if "timelapse_interval" in last_status:
    timelapse_manager.capture_interval = int(last_status["timelapse_interval"])


class TimeLapseConfigModel(BaseModel):
    mode: Optional[str] = "hybrid"
    interval: Optional[int] = 10
    recording_enabled: Optional[bool] = True


@app.get("/api/timelapse/config")
async def api_timelapse_get_config():
    """Returns current timelapse capture configuration."""
    return {
        "ok": True,
        "mode": timelapse_manager.capture_mode,
        "interval": timelapse_manager.capture_interval,
        "recording_enabled": timelapse_manager.recording_enabled
    }


@app.post("/api/timelapse/config")
async def api_timelapse_post_config(config: TimeLapseConfigModel):
    """Updates timelapse capture configuration."""
    if config.mode:
        timelapse_manager.capture_mode = config.mode
    if config.interval is not None:
        timelapse_manager.capture_interval = int(config.interval)
    if config.recording_enabled is not None:
        timelapse_manager.recording_enabled = config.recording_enabled
    try:
        save_config(PRINTER_HOST, PRINTER_PORT, PRINTER_SERIAL, PRINTER_CHECK_CODE,
                    timelapse_mode=timelapse_manager.capture_mode,
                    timelapse_interval=timelapse_manager.capture_interval)
    except Exception as e:
        print(f"Error persisting timelapse config: {e}")
    return {
        "ok": True,
        "mode": timelapse_manager.capture_mode,
        "interval": timelapse_manager.capture_interval,
        "recording_enabled": timelapse_manager.recording_enabled
    }


@app.get("/api/timelapse/list")
async def api_timelapse_list():
    """Returns list of recorded timelapses and active recording session."""
    active = timelapse_manager.get_active_session_info()
    recordings = timelapse_manager.get_recordings()
    return {
        "ok": True,
        "active_session": active,
        "recordings": recordings
    }


@app.get("/api/timelapse/video/{session_id}")
async def api_timelapse_video(session_id: str, download: bool = False):
    """Streams or downloads the compiled timelapse video (WebP or MP4)."""
    clean_id = os.path.basename(session_id)
    session_dir = os.path.join(TIMELAPSE_DIR, clean_id)
    if not os.path.isdir(session_dir):
        return JSONResponse({"ok": False, "error": "Kayıt bulunamadı."}, status_code=404)

    # Prefer MP4 if exists, else WebP
    mp4_file = os.path.join(session_dir, "timelapse.mp4")
    webp_file = os.path.join(session_dir, "timelapse.webp")
    
    target_file = None
    media_type = "image/webp"
    
    if os.path.exists(mp4_file) and os.path.getsize(mp4_file) > 100:
        target_file = mp4_file
        media_type = "video/mp4"
    elif os.path.exists(webp_file) and os.path.getsize(webp_file) > 100:
        target_file = webp_file
        media_type = "image/webp"

    if not target_file:
        return JSONResponse({"ok": False, "error": "Video dosyası henüz oluşturulmadı veya işlemde."}, status_code=404)

    ext = os.path.splitext(target_file)[1]
    filename = f"{clean_id}{ext}"
    disposition = f'attachment; filename="{filename}"' if download else f'inline; filename="{filename}"'
    
    return FileResponse(
        target_file,
        media_type=media_type,
        headers={
            "Content-Disposition": disposition,
            "Cache-Control": "public, max-age=86400"
        }
    )


@app.get("/api/timelapse/thumbnail/{session_id}")
async def api_timelapse_thumbnail(session_id: str):
    """Returns the thumbnail poster JPEG for the session."""
    clean_id = os.path.basename(session_id)
    session_dir = os.path.join(TIMELAPSE_DIR, clean_id)
    thumb_path = os.path.join(session_dir, "thumbnail.jpg")
    
    if not os.path.exists(thumb_path):
        frames_dir = os.path.join(session_dir, "frames")
        if os.path.exists(frames_dir):
            frames = sorted([f for f in os.listdir(frames_dir) if f.lower().endswith(".jpg")])
            if frames:
                thumb_path = os.path.join(frames_dir, frames[0])

    if os.path.exists(thumb_path):
        return FileResponse(
            thumb_path,
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=86400"}
        )
    return JSONResponse({"ok": False, "error": "Thumbnail bulunamadı."}, status_code=404)


@app.get("/api/timelapse/frames/{session_id}")
async def api_timelapse_frames(session_id: str):
    """Returns list of frame URLs for interactive layer scrubbing."""
    clean_id = os.path.basename(session_id)
    session_dir = os.path.join(TIMELAPSE_DIR, clean_id)
    frames_dir = os.path.join(session_dir, "frames")
    
    if not os.path.exists(frames_dir):
        return {"ok": True, "session_id": clean_id, "frames": [], "count": 0}

    frame_files = sorted([f for f in os.listdir(frames_dir) if f.lower().endswith(".jpg")])
    frame_urls = [f"/api/timelapse/frame/{clean_id}/{idx+1}" for idx in range(len(frame_files))]
    
    return {
        "ok": True,
        "session_id": clean_id,
        "count": len(frame_urls),
        "frames": frame_urls,
        "frame_urls": frame_urls
    }


@app.get("/api/timelapse/frame/{session_id}/{frame_num}")
async def api_timelapse_frame(session_id: str, frame_num: int):
    """Returns a specific layer frame JPEG."""
    clean_id = os.path.basename(session_id)
    session_dir = os.path.join(TIMELAPSE_DIR, clean_id)
    frames_dir = os.path.join(session_dir, "frames")
    
    if not os.path.exists(frames_dir):
        return JSONResponse({"ok": False, "error": "Kareler bulunamadı."}, status_code=404)

    frame_files = sorted([f for f in os.listdir(frames_dir) if f.lower().endswith(".jpg")])
    if 1 <= frame_num <= len(frame_files):
        target_frame = os.path.join(frames_dir, frame_files[frame_num - 1])
        return FileResponse(
            target_frame,
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=86400"}
        )
    return JSONResponse({"ok": False, "error": "Kare bulunamadı."}, status_code=404)


@app.delete("/api/timelapse/{session_id:path}")
async def api_timelapse_delete(session_id: str):
    """Deletes a recorded timelapse session."""
    clean_id = urllib.parse.unquote(session_id).replace("\\", "/").split("/")[-1].strip()
    success = timelapse_manager.delete_session(clean_id)
    if success:
        return {"ok": True, "message": "Time-Lapse kaydı başarıyla silindi."}
    return JSONResponse({"ok": False, "error": "Kayıt silinemedi veya bulunamadı."}, status_code=404)


@app.post("/api/timelapse/compile/{session_id}")
async def api_timelapse_compile(session_id: str):
    """Forces re-compilation of a timelapse session."""
    clean_id = os.path.basename(session_id)
    session_dir = os.path.join(TIMELAPSE_DIR, clean_id)
    meta_path = os.path.join(session_dir, "metadata.json")
    if not os.path.exists(meta_path):
        return JSONResponse({"ok": False, "error": "Kayıt bulunamadı."}, status_code=404)

    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    meta["session_dir"] = session_dir
    meta["frames_dir"] = os.path.join(session_dir, "frames")
    threading.Thread(target=timelapse_manager._compile_worker, args=(meta,), daemon=True).start()
    return {"ok": True, "message": "Video derleme işlemi arka planda başlatıldı."}



