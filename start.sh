#!/usr/bin/env bash
# FlashForge AD5X Panel Startup Script for Linux / Raspberry Pi
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

PORT="${PORT:-9003}"
HOST="${HOST:-0.0.0.0}"

echo "================================================="
echo " FlashForge AD5X Web Panel Başlatıcı (Raspberry Pi)"
echo "================================================="

if [ ! -d "venv" ]; then
    echo "[+] Sanal ortam (venv) oluşturuluyor..."
    if ! python3 -m venv venv 2>/dev/null; then
        echo "[!] HATA: python3-venv paketi eksik!"
        echo "[i] Lütfen şu komutu çalıştırın: sudo apt update && sudo apt install -y python3-venv python3-full"
        exit 1
    fi
    echo "[+] Sanal ortam başarıyla oluşturuldu."
    echo "[+] Gereksinimler yükleniyor (requirements.txt)..."
    ./venv/bin/pip install --upgrade pip
    ./venv/bin/pip install -r requirements.txt
fi

echo "[✓] Panel başlatılıyor -> http://${HOST}:${PORT}"
exec ./venv/bin/python -m uvicorn flashforge_panel:app --host "$HOST" --port "$PORT"
