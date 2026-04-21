import asyncio
from bleak import BleakClient, BleakScanner

DEVICE_NAME = "BioMonitor_ESP32"
UART_SERVICE_UUID = "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
UART_RX_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"  # write to ESP32
UART_TX_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"  # notify from ESP32

def handle_rx(_, data):
    print("Received:", data.decode(errors="ignore"))

async def main():
    print("Scanning...")
    device = await BleakScanner.find_device_by_name(DEVICE_NAME, timeout=10.0)

    if device is None:
        print("Could not find device")
        return

    print("Found:", device)

    async with BleakClient(device, timeout=20.0) as client:
        print("Connected:", client.is_connected)

        await client.start_notify(UART_TX_UUID, handle_rx)
        print("Notifications enabled")

        await client.write_gatt_char(UART_RX_UUID, b"hello from pi")
        print("Sent message to ESP32")

        await asyncio.sleep(10)

asyncio.run(main())