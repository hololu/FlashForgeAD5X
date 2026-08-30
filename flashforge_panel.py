from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import asyncio
import socket
import os
import json
import urllib.request
import threading
from collections import deque
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")

PRINTER_HOST = "192.168.1.12"
PRINTER_PORT = 8899
RECONNECT_DELAY = 3.0
WATCH_INTERVAL = 2.0
PRINTER_SERIAL = ""
PRINTER_CHECK_CODE = ""

def load_config():
    global PRINTER_HOST, PRINTER_PORT, PRINTER_SERIAL, PRINTER_CHECK_CODE, RECONNECT_DELAY, WATCH_INTERVAL
    PRINTER_HOST = os.getenv("FLASHFORGE_HOST", "192.168.1.12")
    PRINTER_PORT = int(os.getenv("FLASHFORGE_PORT", "8899"))
    RECONNECT_DELAY = float(os.getenv("FLASHFORGE_RECONNECT_DELAY", "3"))
    WATCH_INTERVAL = float(os.getenv("FLASHFORGE_WATCH_INTERVAL", "2"))
    PRINTER_SERIAL = os.getenv("FLASHFORGE_SERIAL", "")
    PRINTER_CHECK_CODE = os.getenv("FLASHFORGE_CHECK_CODE", "")

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
        except Exception as e:
            print(f"Error loading config.json: {e}")

def save_config(host, port, serial, check_code):
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
        "z_offset": last_status.get("z_offset", 0.0)
    })
    
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
        elif ":" in line and any(k in line for k in ["X-max", "Y-max", "Z-min", "LED"]):
            if "X-max:" in line:
                out["endstop"]["x"] = line.split("X-max:")[-1].strip()
            if "Y-max:" in line:
                out["endstop"]["y"] = line.split("Y-max:")[-1].strip()
            if "Z-min:" in line:
                out["endstop"]["z"] = line.split("Z-min:")[-1].strip()
            if line.startswith("LED:"):
                out["led"] = line.replace("LED:", "").strip()
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

    status = {
        "machine_status": parsed_m119.get("machine_status", "UNKNOWN"),
        "move_mode": parsed_m119.get("move_mode", "UNKNOWN"),
        "current_file": parsed_m119.get("current_file", ""),
        "progress": parsed_m27.get("progress", 0),
        "layer": parsed_m27.get("layer", "0/0"),
        "temperatures": parsed_m105,
        "endstop": parsed_m119.get("endstop", {}),
        "led": parsed_m119.get("led", "?"),
        "status_flags": parsed_m119.get("status_flags", "S:? L:? J:? F:?"),
        "updated_at": datetime.now().strftime("%H:%M:%S"),
        "error": None if "ERR:" not in m119_text and "ERR:" not in m27_text else m119_text,
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


async def watch_loop():
    while True:
        try:
            await refresh_once()
        except Exception as e:
            async with lock:
                last_status["error"] = str(e)
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
        return JSONResponse(dict(last_status))


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
    elif c in cmd_map:
        raw = await send_command(cmd_map[c])
    else:
        return JSONResponse({"ok": False, "error": "Desteklenmeyen komut"}, status_code=400)
        
    text = raw.decode("utf-8", errors="ignore") if isinstance(raw, bytes) else str(raw)
    return JSONResponse({"ok": True, "response": text.strip()})


def _upload_gcode_sync(host, serial, check_code, filename, file_bytes, print_now=False):
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
    
    headers = {
        "serialNumber": serial,
        "serialNo": serial,
        "checkCode": check_code,
        "fileSize": str(len(file_bytes)),
        "printNow": "true" if print_now else "false",
        "Content-Type": content_type
    }
    
    req = urllib.request.Request(
        url,
        data=bytes(body),
        headers=headers,
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.loads(response.read().decode())


@app.post("/api/upload")
async def api_upload(request: Request, filename: str, print_now: bool = False):
    if not PRINTER_SERIAL or not PRINTER_CHECK_CODE:
        return JSONResponse({"ok": False, "error": "Seri Numarası veya LAN Kodu ayarlanmamış"}, status_code=400)
    
    try:
        file_bytes = await request.body()
        if not file_bytes:
            return JSONResponse({"ok": False, "error": "Dosya içeriği boş"}, status_code=400)
            
        loop = asyncio.get_event_loop()
        res = await loop.run_in_executor(
            None, _upload_gcode_sync, PRINTER_HOST, PRINTER_SERIAL, PRINTER_CHECK_CODE, filename, file_bytes, print_now
        )
        
        code_val = res.get("code")
        msg_val = res.get("message")
        if code_val == 0 or code_val == 200 or msg_val == "success":
            return {"ok": True, "message": "Dosya başarıyla yüklendi" + (" ve baskı başlatıldı." if print_now else ".")}
        else:
            return JSONResponse({"ok": False, "error": f"Yazıcı hata döndürdü - Kod: {code_val}, Mesaj: {msg_val}"}, status_code=500)
            
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"Bağlantı hatası: {str(e)}"}, status_code=500)


class SettingsModel(BaseModel):
    host: str
    port: int
    serial: str
    check_code: str


@app.get("/api/settings")
async def get_settings():
    async with lock:
        return {
            "host": PRINTER_HOST,
            "port": PRINTER_PORT,
            "serial": PRINTER_SERIAL,
            "check_code": PRINTER_CHECK_CODE,
            "tcp_error": last_status.get("error"),
            "ifs_error": last_status.get("filament_info_error")
        }


@app.post("/api/settings")
async def post_settings(settings: SettingsModel):
    save_config(settings.host, settings.port, settings.serial, settings.check_code)
    try:
        camera_broadcaster.reset()
    except Exception:
        pass
    # Trigger an immediate background check to reflect new settings
    asyncio.create_task(refresh_once())
    return {"ok": True}


@app.post("/api/service/restart")
async def api_service_restart():
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
                        loop.call_soon_threadsafe(self._dispatch_frame, frame_payload)
                        
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
        loop.call_soon_threadsafe(self._notify_closed)

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

    async def unsubscribe(self, q):
        async with self.lock:
            self.subscribers.discard(q)
            if not self.subscribers:
                self.stop_event.set()
                self.thread = None


camera_broadcaster = CameraBroadcaster()


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
    # 1. Use cached frame if recent (within last 3 seconds)
    if camera_broadcaster.latest_frame and camera_broadcaster.latest_frame_time:
        age = (datetime.now() - camera_broadcaster.latest_frame_time).total_seconds()
        if age < 3.0:
            return Response(
                content=camera_broadcaster.latest_frame,
                media_type="image/jpeg",
                headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
            )

    camera_url = f"http://{PRINTER_HOST}:8080/?action=snapshot"

    def fetch_snapshot():
        # Try ?action=snapshot
        try:
            req = urllib.request.Request(
                camera_url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) FlashForge-Panel/1.0", "Accept": "*/*"}
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = resp.read()
                if data and len(data) > 1000 and data.startswith(b"\xff\xd8"):
                    return data
        except Exception:
            pass

        # Fallback: Read 1 frame from ?action=stream
        try:
            stream_url = f"http://{PRINTER_HOST}:8080/?action=stream"
            req = urllib.request.Request(
                stream_url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) FlashForge-Panel/1.0", "Accept": "*/*"}
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
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
                            return bytes(buf[start:end+2])
        except Exception as e:
            print(f"Camera snapshot fallback error: {e}")
        return None

    loop = asyncio.get_running_loop()
    img_bytes = await loop.run_in_executor(None, fetch_snapshot)
    if img_bytes:
        camera_broadcaster.latest_frame = img_bytes
        camera_broadcaster.latest_frame_time = datetime.now()
        return Response(
            content=img_bytes,
            media_type="image/jpeg",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
        )
    return JSONResponse({"ok": False, "error": "Kamera görüntüsü alınamadı"}, status_code=502)



