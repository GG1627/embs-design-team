import asyncio
from bleak import BleakClient, BleakScanner

NAME = "BioMonitor_ESP32"
TX_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"
RX_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"

def on_notify(sender, data):
    try:
        print("Notify:", data.decode())
    except:
        print("Notify bytes:", data)

async def main():
    device = await BleakScanner.find_device_by_name(NAME, timeout=10.0)
    if not device:
        print("ESP32 not found")
        return

    async with BleakClient(device, timeout=20.0) as client:
        print("Connected:", client.is_connected)
        await client.start_notify(TX_UUID, on_notify)

        await client.write_gatt_char(RX_UUID, b"hello esp32")
        print("Sent message")

        while True:
            await asyncio.sleep(1)

asyncio.run(main())