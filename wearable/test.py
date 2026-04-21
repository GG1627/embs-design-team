import asyncio
from bleak import BleakClient, BleakScanner

ADDRESS = "40:22:D8:75:0F:2A"
UART_RX_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
UART_TX_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"

def handle_notify(sender, data):
    print("Notify:", data.decode(errors="ignore"))

async def main():
    device = await BleakScanner.find_device_by_address(ADDRESS, timeout=10.0)
    if device is None:
        print("Could not find device")
        return

    print("Found:", device.address, device.name)

    async with BleakClient(device, timeout=30.0) as client:
        print("Connected:", client.is_connected)
        await client.start_notify(UART_TX_UUID, handle_notify)
        await client.write_gatt_char(UART_RX_UUID, b"hello from pi")
        print("Sent hello")
        while True:
            await asyncio.sleep(2)
            await client.write_gatt_char(UART_RX_UUID, b"ping")

asyncio.run(main())