#!/usr/bin/env bash
# 使い方:
#   ./setup.sh /dev/serial/by-id/usb-XXXX      # インストール & 有効化
#   ./setup.sh --uninstall                     # 削除
set -euo pipefail

SERVICE=fan-control
UNIT_DIR="$HOME/.config/systemd/user"
INSTALL_DIR="$HOME/.local/share/fan-control"
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"

if [[ "${1:-}" == "--uninstall" ]]; then
    systemctl --user disable --now "$SERVICE.service" 2>/dev/null || true
    rm -f "$UNIT_DIR/$SERVICE.service"
    rm -rf "$INSTALL_DIR"
    systemctl --user daemon-reload
    echo "uninstalled"
    exit 0
fi

DEVICE="${1:-}"
if [[ -z "$DEVICE" ]]; then
    echo "usage: $0 <serial-device> | --uninstall" >&2
    echo "  ヒント: ls /dev/serial/by-id/  (再起動しても名前が変わらないのでおすすめ)" >&2
    exit 1
fi
if [[ ! -e "$DEVICE" ]]; then
    echo "error: $DEVICE が存在しません" >&2
    exit 1
fi
DEVICE="$(realpath -s "$DEVICE")"

# 依存チェック
command -v nvidia-smi >/dev/null || { echo "error: nvidia-smi not found" >&2; exit 1; }
python3 -c "import serial" 2>/dev/null || {
    echo "error: pyserial が必要です (sudo apt install python3-serial)" >&2; exit 1; }
if ! id -nG | tr ' ' '\n' | grep -qx dialout; then
    echo "warning: $USER が dialout グループに属していません。" >&2
    echo "         sudo usermod -aG dialout $USER  後に再ログインしてください。" >&2
fi

mkdir -p "$UNIT_DIR" "$INSTALL_DIR"
install -m 755 "$SRC_DIR/fan_control.py" "$INSTALL_DIR/fan_control.py"

cat > "$UNIT_DIR/$SERVICE.service" <<EOF
[Unit]
Description=V100 GPU fan control daemon

[Service]
ExecStart=/usr/bin/python3 $INSTALL_DIR/fan_control.py --device $DEVICE
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now "$SERVICE.service"
# ログアウト後・起動時もユーザーサービスを動かす
loginctl enable-linger "$USER" || echo "warning: enable-linger に失敗 (sudo が必要かも)" >&2

echo "installed. device=$DEVICE"
echo "  status: systemctl --user status $SERVICE"
echo "  log:    journalctl --user -u $SERVICE -f"
