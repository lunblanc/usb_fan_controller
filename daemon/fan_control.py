#!/usr/bin/env python3
"""V100 GPU fan control daemon.

nvidia-smi で V100 の温度を一定間隔で取得し、目標温度以下に保つように
シリアル経由でファンの Duty 比(%)をテキストで送信する。
"""
import argparse
import logging
import signal
import subprocess
import sys
import time

import serial  # pyserial

log = logging.getLogger("fan_control")

BAUDRATE = 9600
FAILSAFE_DUTY = 100


def get_v100_max_temp(name_filter):
    """名前に name_filter を含む GPU の最高温度を返す。見つからなければ例外。"""
    out = subprocess.run(
        ["nvidia-smi", "--query-gpu=name,temperature.gpu",
         "--format=csv,noheader,nounits"],
        capture_output=True, text=True, timeout=10, check=True,
    ).stdout
    temps = []
    for line in out.splitlines():
        name, _, temp = line.rpartition(",")
        if name_filter.lower() in name.lower():
            temps.append(int(temp))
    if not temps:
        raise RuntimeError(f"no GPU matching {name_filter!r} found")
    return max(temps)


class FanController:
    """PI 制御。目標温度を超えたら Duty を上げ、下回れば下げる。"""

    def __init__(self, target, kp, ki, min_duty, max_duty):
        self.target = target
        self.kp = kp
        self.ki = ki
        self.min_duty = min_duty
        self.max_duty = max_duty
        self.integral = float(min_duty)  # 積分項は Duty の次元で保持

    def update(self, temp, dt):
        error = temp - self.target
        # アンチワインドアップ: 出力範囲内に積分項をクランプ
        self.integral += self.ki * error * dt
        self.integral = max(self.min_duty, min(self.max_duty, self.integral))
        duty = self.kp * error + self.integral
        return int(round(max(self.min_duty, min(self.max_duty, duty))))


def send_duty(ser, duty, fmt):
    ser.write(fmt.format(duty=duty).encode("ascii"))
    ser.flush()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--device", required=True, help="シリアルデバイス (例: /dev/ttyUSB0)")
    p.add_argument("--target", type=float, default=60.0, help="目標温度[℃] (default: 60)")
    p.add_argument("--interval", type=float, default=5.0, help="取得間隔[秒] (default: 5)")
    p.add_argument("--gpu-name", default="V100", help="対象GPU名に含まれる文字列")
    p.add_argument("--min-duty", type=int, default=30)
    p.add_argument("--max-duty", type=int, default=100)
    p.add_argument("--kp", type=float, default=5.0, help="比例ゲイン[%%/℃]")
    p.add_argument("--ki", type=float, default=0.5, help="積分ゲイン[%%/(℃·s)]")
    p.add_argument("--format", default="{duty}\n",
                   help="送信テキストの書式 (default: '{duty}\\n')")
    args = p.parse_args()
    fmt = args.format.encode().decode("unicode_escape")

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    ser = serial.Serial(args.device, BAUDRATE, timeout=1)
    ctrl = FanController(args.target - 0.0, args.kp, args.ki,
                         args.min_duty, args.max_duty)

    stop = False

    def handle_signal(signum, _frame):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    log.info("started: device=%s target=%.1fC interval=%.1fs",
             args.device, args.target, args.interval)
    last = time.monotonic()
    try:
        while not stop:
            try:
                temp = get_v100_max_temp(args.gpu_name)
                now = time.monotonic()
                duty = ctrl.update(temp, now - last)
                last = now
            except Exception as e:  # 温度が取れない場合は安全側(全開)
                log.error("temperature read failed: %s", e)
                duty = FAILSAFE_DUTY
                temp = None
            try:
                send_duty(ser, duty, fmt)
            except serial.SerialException as e:
                log.error("serial write failed: %s", e)
                return 1  # systemd に再起動させる
            log.info("temp=%s duty=%d%%", temp, duty)
            # stop をすぐ検知できるよう細切れに待つ
            deadline = time.monotonic() + args.interval
            while not stop and time.monotonic() < deadline:
                time.sleep(0.2)
    finally:
        try:
            send_duty(ser, FAILSAFE_DUTY, fmt)  # 終了時は安全のため全開
        except Exception:
            pass
        ser.close()
        log.info("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
