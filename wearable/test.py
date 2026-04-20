import asyncio
from bleak import BleakClient, BleakScanner

ADDRESS = "40:22:D8:75:0F:2A"
TX_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"
RX_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"

def on_notify(_, data):
    print("notify:", data.decode())

async def main():
    async with BleakClient(ADDRESS) as client:
        print("connected:", client.is_connected)
        await client.start_notify(TX_UUID, on_notify)
        await client.write_gatt_char(RX_UUID, b"hello from pi")
        await asyncio.sleep(30)

asyncio.run(main())