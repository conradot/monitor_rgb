import time
import requests
import os
import subprocess
from openrgb import OpenRGBClient
from openrgb.utils import RGBColor

# Configurações
OLLAMA_API = "http://localhost:11434/api/ps"
OPENRGB_HOST = "127.0.0.1"
NUM_LEDS_FAN = 16

# DEFINIÇÃO DE CORES
COLOR_BLUE = (0, 0, 255)
COLOR_GREEN = (0, 255, 20)
COLOR_YELLOW = (255, 215, 0)
COLOR_MAGENTA = (255, 0, 255)
COLOR_ORANGE = (255, 50, 0)
COLOR_RED = (255, 0, 0)
COLOR_OFF = (0, 0, 0)

def get_cpu_temp():
    try:
        for hwmon in os.listdir('/sys/class/hwmon'):
            with open(f'/sys/class/hwmon/{hwmon}/name', 'r') as f:
                if f.read().strip() in ['k10temp', 'zenpower']:
                    with open(f'/sys/class/hwmon/{hwmon}/temp1_input', 'r') as f:
                        return int(f.read().strip()) / 1000.0
    except Exception:
        pass
    return 0.0

def get_power_mode():
    try:
        if os.path.exists('/sys/firmware/acpi/platform_profile'):
            with open('/sys/firmware/acpi/platform_profile', 'r') as f:
                profile = f.read().strip()
                if profile == 'performance':
                    return "MAX_PERF"
                elif profile in ['low-power', 'power-saver']:
                    return "POWER_SAVE"
                elif profile == 'balanced':
                    return "BALANCED"
    except Exception:
        pass
    return "BALANCED"

def is_ai_running():
    try:
        response = requests.get(OLLAMA_API, timeout=0.5)
        if response.json().get("models"):
            return True
    except Exception:
        pass

    try:
        output = subprocess.check_output(["pgrep", "-f", "-i", "llama|ollama"], text=True)
        if output.strip():
            return True
    except subprocess.CalledProcessError:
        pass

    return False

def blend_color(color_init, color_target, factor):
    factor = max(0.0, min(1.0, factor))
    r = int(color_init[0] + (color_target[0] - color_init[0]) * factor)
    g = int(color_init[1] + (color_target[1] - color_init[1]) * factor)
    b = int(color_init[2] + (color_target[2] - color_init[2]) * factor)
    return (r, g, b)

def create_smooth_palette(colors, num_leds):
    palette = []
    n_colors = len(colors)
    for i in range(num_leds):
        pos = (i / num_leds) * n_colors
        idx1 = int(pos) % n_colors
        idx2 = (idx1 + 1) % n_colors
        factor = pos - int(pos)
        palette.append(blend_color(colors[idx1], colors[idx2], factor))
    return palette

def get_temp_color(temp):
    temp_min = 50.0
    temp_mid = 70.0
    temp_max = 85.0

    if temp <= temp_min:
        return COLOR_YELLOW
    elif temp <= temp_mid:
        factor = (temp - temp_min) / (temp_mid - temp_min)
        return blend_color(COLOR_YELLOW, COLOR_ORANGE, factor)
    elif temp <= temp_max:
        factor = (temp - temp_mid) / (temp_max - temp_mid)
        return blend_color(COLOR_ORANGE, COLOR_RED, factor)
    else:
        return COLOR_RED

def generate_fan_frame(ai_active, temp, tick, power_mode):
    if power_mode == "POWER_SAVE":
        return [RGBColor(*COLOR_OFF)] * NUM_LEDS_FAN

    if temp > 60.0:
        base_color = get_temp_color(temp)
        pattern = [base_color] * NUM_LEDS_FAN

        pattern[0] = blend_color(base_color, COLOR_OFF, 0.7)
        pattern[8] = blend_color(base_color, COLOR_OFF, 0.7)

        speed = int(2 + (temp - 60) / 10)
        shift = (tick * speed) % NUM_LEDS_FAN
        rotated = pattern[shift:] + pattern[:shift]
        return [RGBColor(*c) for c in rotated]

    if os.path.exists("/tmp/use_magenta"):
        base_colors = [COLOR_BLUE, COLOR_MAGENTA]
    else:
        base_colors = [COLOR_BLUE, COLOR_GREEN, COLOR_YELLOW, COLOR_MAGENTA]

    smooth_pattern = create_smooth_palette(base_colors, NUM_LEDS_FAN)

    if ai_active or power_mode == "MAX_PERF":
        shift = (tick * 3) % NUM_LEDS_FAN
        dim_factor = 1.0
    else:
        shift = (tick // 5) % NUM_LEDS_FAN
        dim_factor = 0.4

    final_pattern = [
        (int(c[0] * dim_factor), int(c[1] * dim_factor), int(c[2] * dim_factor))
        for c in smooth_pattern
    ]

    rotated = final_pattern[shift:] + final_pattern[:shift]
    return [RGBColor(*c) for c in rotated]

def main():
    client = None
    fan_zone = None
    tick = 0
    ai_active = False
    temp = 0.0
    power_mode = "BALANCED"

    while True:
        if client is None or fan_zone is None:
            try:
                client = OpenRGBClient(OPENRGB_HOST, 6742)
                # Busca flexível pela placa mãe ASUS
                device = next((d for d in client.devices if 'ASUS' in d.name or 'B650M' in d.name), None)

                if not device:
                    print("Servidor conectado, mas a placa-mãe não foi encontrada. Aguardando...")
                    client = None
                    time.sleep(5)
                    continue

                # Força o modo de controle direto frame-a-frame
                try:
                    device.set_mode('direct')
                except Exception:
                    pass

                # Busca inteligente pela zona Addressable 3 por nome, com fallback seguro
                fan_zone = next((z for z in device.zones if 'Addressable 3' in z.name), None)
                if not fan_zone:
                    fan_zone = device.zones[-1] # Usa a última zona disponível se não achar pelo nome

                print(f"Conectado com sucesso à zona: '{fan_zone.name}'!")
            except Exception as e:
                print(f"Aguardando OpenRGB Flatpak Server... (Erro: {e})")
                client = None
                fan_zone = None
                time.sleep(5)
                continue

        try:
            if tick % 20 == 0:
                power_mode = get_power_mode()
                temp = get_cpu_temp()
                ai_active = is_ai_running()
                print(f"[MONITOR] Temp: {temp}°C | Perfil: {power_mode} | IA: {ai_active}")

            frame = generate_fan_frame(ai_active, temp, tick, power_mode)
            fan_zone.set_colors(frame)

            tick += 1
            time.sleep(0.1)

        except (ConnectionResetError, BrokenPipeError):
            print("Conexão perdida com o Flatpak. Reconectando...")
            client = None
            fan_zone = None
            time.sleep(2)

if __name__ == "__main__":
    main()
