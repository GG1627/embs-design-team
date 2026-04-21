import asyncio
from bleak import BleakClient, BleakScanner

DEVICE_ADDRESS = "40:22:D8:75:0F:2A"

UART_SERVICE_UUID = "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
UART_RX_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"  # write to ESP32
UART_TX_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"  # notify from ESP32

def handle_notify(sender, data):
    try:
        print("Notify:", data.decode(errors="ignore"))
    except Exception:
        print("Notify bytes:", data)

async def main():
    print("Connecting to:", DEVICE_ADDRESS)

    device = await BleakScanner.find_device_by_address(DEVICE_ADDRESS, timeout=10.0)
    if device is None:
        print("Could not find device")
        return

    async with BleakClient(device, timeout=20.0) as client:
        print("Connected:", client.is_connected)

        await client.start_notify(UART_TX_UUID, handle_notify)
        print("Notifications enabled")

        await client.write_gatt_char(UART_RX_UUID, b"hello from pi")
        print("Sent: hello from pi")

        while True:
            await asyncio.sleep(2)
            await client.write_gatt_char(UART_RX_UUID, b"ping")

asyncio.run(main())