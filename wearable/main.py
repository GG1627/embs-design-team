import asyncio
import struct
from bleak import BleakScanner, BleakClient

# --- CONFIGURATION ---
# The exact MAC address of the ESP32 from the scanner
TARGET_MAC = "40:22:D8:75:0F:2A"

# The UUIDs from your ESP32 code
HR_UUID = "12345678-1234-1234-1234-123456789a01"
SPO2_UUID = "12345678-1234-1234-1234-123456789a02"
HRV_UUID = "12345678-1234-1234-1234-123456789a03"
TEMP_UUID = "12345678-1234-1234-1234-123456789a04"

# --- CALLBACK HANDLERS ---
def hr_handler(sender, data):
    heart_rate = struct.unpack("<H", data)[0]
    if heart_rate > 0:
        print(f"Heart Rate: {heart_rate} BPM")

def spo2_handler(sender, data):
    spo2 = struct.unpack("<f", data)[0]
    if spo2 > 0:
        print(f"SpO2:       {spo2:.1f} %")

def hrv_handler(sender, data):
    hrv = struct.unpack("<f", data)[0]
    if hrv > 0:
        print(f"HRV:        {hrv:.1f} ms")

def temp_handler(sender, data):
    # Unpack as a 2-byte unsigned integer and divide by 100
    raw_temp = struct.unpack("<H", data)[0]
    temp_f = raw_temp / 100.0
    print(f"Skin Temp:  {temp_f:.2f} F\n")

# --- MAIN BLUETOOTH LOOP ---
async def main():
    print(f"Scanning for ESP32 at {TARGET_MAC}...")
    
    # 1. Automatically find the ESP32 by its exact MAC address
    device = await BleakScanner.find_device_by_address(TARGET_MAC, timeout=30.0)
    
    if device is None:
        print(f"Could not find ESP32 at {TARGET_MAC}. Make sure it is powered on.")
        return

    print(f"Found ESP32! Connecting...")

    # 2. Connect to the device
    async with BleakClient(device) as client:
        print("Connected successfully!\n")

        await asyncio.sleep(2.0)  # Short delay to ensure connection is stable
        
        # 3. Subscribe to the notifications
        await client.start_notify(HR_UUID, hr_handler)
        print("Subscribed to HR")
        await client.start_notify(SPO2_UUID, spo2_handler)
        print("Subscribed to SpO2")
        await client.start_notify(HRV_UUID, hrv_handler)
        print("Subscribed to HRV")
        await client.start_notify(TEMP_UUID, temp_handler)
        print("Subscribed to Temperature")
        
        print("Listening for biometric data. Press Ctrl+C to stop.\n" + "-"*40)
        
        # Keep the script running to listen for incoming BLE packets
        while True:
            await asyncio.sleep(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nDisconnected.")