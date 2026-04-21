import serial
import time

PORT = "/dev/ttyUSB0"   # change if needed
BAUD = 115200

ser = serial.Serial(PORT, BAUD, timeout=1)
time.sleep(2)

while True:
    line = ser.readline().decode(errors="ignore").strip()
    if line:
        print(line)