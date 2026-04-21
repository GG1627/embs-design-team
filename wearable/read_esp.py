import serial
import csv
from pathlib import Path
import time

PORT = "/dev/ttyUSB0"   # change if needed
BAUD = 115200
OUT = Path("wearable/biomonitor_log.csv")

ser = serial.Serial(PORT, BAUD, timeout=1)
time.sleep(2)

with OUT.open("w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["tag", "ms", "acc_x", "acc_y", "acc_z", "gsr_kohm", "stress", "hr_bpm", "spo2", "hrv_ms", "temp_f"])

    while True:
        line = ser.readline().decode(errors="ignore").strip()
        if not line:
            continue

        print(line)

        if line.startswith("DATA,"):
            parts = line.split(",")
            if len(parts) == 11:
                writer.writerow(parts)
                f.flush()