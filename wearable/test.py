import asyncio
from bleak import BleakClient, BleakScanner

ADDRESS = "40:22:D8:75:0F:2A"
UART_RX_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
UART_TX_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"

def handle_notify(sender, data):
    print("Notify:", data.decode(errors="ignore"))

async def main():
    print("Scanning...")
    devices = await BleakScanner.discover(timeout=8.0)

    target = None
    for d in devices:
        if d.address.upper() == ADDRESS:
            target = d
            break

    if target is None:
        print("Could not find device")
        return

    print("Found:", target.address, target.name)

    async with BleakClient(target, timeout=30.0) as client:
        print("Connected:", client.is_connected)

        print("Services object:", client.services)

        await client.start_notify(UART_TX_UUID, handle_notify)
        print("Notifications enabled")

        await client.write_gatt_char(UART_RX_UUID, b"hello from pi", response=False)
        print("Sent hello")

        await asyncio.sleep(5)

asyncio.run(main())