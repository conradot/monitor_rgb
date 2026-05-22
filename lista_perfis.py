from openrgb import OpenRGBClient

client = OpenRGBClient("127.0.0.1", 6742)
for device in client.devices:
    print(f"Dispositivo: '{device.name}' (ID: {device.id})")
    for zone in device.zones:
        # len(zone.leds) funciona em qualquer versão da biblioteca
        print(f"  -> Zona: '{zone.name}' (ID: {zone.id}) | LEDs: {len(zone.leds)}")
