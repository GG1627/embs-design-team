import asyncio
import struct
from bleak import BleakScanner, BleakClient

# The name we set in BLEDevice::init()
DEVICE_NAME = "BioMonitor"

# The UUIDs from your ESP32 code
HR_UUID = "12345678-1234-1234-1234-123456789a01"
SPO2_UUID = "12345678-1234-1234-1234-123456789a02"
HRV_UUID = "12345678-1234-1234-1234-123456789a03"
TEMP_UUID = "12345678-1234-1234-1234-123456789a04"

# Callbacks to handle incoming data from the ESP32
def hr_handler(sender, data):
    # Unpack 2 bytes as a little-endian unsigned integer
    heart_rate = struct.unpack("<H", data)[0]
    if heart_rate > 0:
        print(f"Heart Rate: {heart_rate} BPM")

def spo2_handler(sender, data):
    # Unpack 4 bytes as a little-endian float
    spo2 = struct.unpack("<f", data)[0]
    if spo2 > 0:
        print(f"SpO2:       {spo2:.1f} %")

def hrv_handler(sender, data):
    hrv = struct.unpack("<f", data)[0]
    if hrv > 0:
        print(f"HRV:        {hrv:.1f} ms")

def temp_handler(sender, data):
    temp_c = struct.unpack("<f", data)[0]
    temp_f = temp_c * 9.0 / 5.0 + 32.0
    print(f"Skin Temp:  {temp_c:.2f} C / {temp_f:.2f} F\n")

async def main():
    print(f"Scanning for {DEVICE_NAME}...")
    
    # 1. Automatically find the ESP32 by its broadcast name
    device = await BleakScanner.find_device_by_name(DEVICE_NAME, timeout=10.0)
    
    if device is None:
        print(f"Could not find {DEVICE_NAME}. Make sure it is powered on.")
        return

    print(f"Found {DEVICE_NAME} at {device.address}! Connecting...")

    # 2. Connect to the device
    async with BleakClient(device) as client:
        print("Connected successfully!\n")
        
        # 3. Subscribe to the notifications
        await client.start_notify(HR_UUID, hr_handler)
        await client.start_notify(SPO2_UUID, spo2_handler)
        await client.start_notify(HRV_UUID, hrv_handler)
        await client.start_notify(TEMP_UUID, temp_handler)
        
        print("Listening for biometric data. Press Ctrl+C to stop.")
        
        # Keep the script running to listen for incoming BLE packets
        while True:
            await asyncio.sleep(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nDisconnected.")