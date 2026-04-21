import serial
import csv
from pathlib import Path
import time
import os

PORT = "/dev/ttyUSB0"   # change if needed
BAUD = 115200
OUT = Path("wearable/biomonitor_log.csv")

def clear():
    os.system("clear")

def fmt_float(x, digits=2):
    try:
        return f"{float(x):.{digits}f}"
    except:
        return str(x)

ser = serial.Serial(PORT, BAUD, timeout=1)
time.sleep(2)

latest = None

with OUT.open("w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow([
        "tag", "ms", "acc_x", "acc_y", "acc_z",
        "gsr_kohm", "stress", "hr_bpm", "spo2", "hrv_ms", "temp_f"
    ])

    while True:
        line = ser.readline().decode(errors="ignore").strip()
        if not line:
            continue

        if line.startswith("DATA,"):
            parts = line.split(",")
            if len(parts) == 11:
                writer.writerow(parts)
                f.flush()
                latest = parts

                _, ms, acc_x, acc_y, acc_z, gsr_kohm, stress, hr_bpm, spo2, hrv_ms, temp_f = parts

                clear()
                print("========================================")
                print("      BIOMONITOR LIVE SERIAL VIEW")
                print("========================================")
                print(f"Time (ms):   {ms}")
                print(f"Heart Rate:  {hr_bpm} bpm")
                print(f"SpO2:        {spo2} %")
                print(f"HRV:         {hrv_ms} ms")
                print(f"Temp:        {temp_f} F")
                print(f"Stress:      {float(stress)*100:.1f} %")
                print(f"GSR:         {gsr_kohm} kOhm")
                print("")
                print("Motion")
                print(f"  AccX:      {fmt_float(acc_x)}")
                print(f"  AccY:      {fmt_float(acc_y)}")
                print(f"  AccZ:      {fmt_float(acc_z)}")
                print("========================================")
                print(f"Logging to:  {OUT}")