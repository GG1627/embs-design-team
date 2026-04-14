import asyncio
from bleak import BleakScanner

async def main():
    print("Scanning for all BLE devices for 5 seconds...")
    # This discovers everything currently broadcasting nearby
    devices = await BleakScanner.discover(timeout=5.0)
    
    found_devices = 0
    for d in devices:
        found_devices += 1
        print(f"Name: {d.name}, Address: {d.address}")
        
    print(f"\nTotal devices found: {found_devices}")

if __name__ == "__main__":
    asyncio.run(main())