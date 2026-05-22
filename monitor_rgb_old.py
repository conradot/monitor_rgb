import time
import requests
import os
import subprocess
import pwd
import argparse
import math
import random
from openrgb import OpenRGBClient
from openrgb.utils import RGBColor

# Configurações
OLLAMA_API = "http://localhost:11434/api/ps"
OPENRGB_HOST = "127.0.0.1"
NUM_LEDS_FAN = 16

# DEFINIÇÃO DE CORES DA PALETA FIXA
COLOR_CYAN = (0, 200, 255)         # Azul Watson (Turquesa)
COLOR_GREEN = (0, 255, 20)         # Verde Neon
COLOR_YELLOW = (255, 215, 0)       # Amarelo Ouro (Modo Balanceado)
COLOR_ORANGE = (255, 60, 0)        # Laranja Intenso (Modo Alto Desempenho)
COLOR_RED = (255, 0, 0)            # Vermelho Crítico
COLOR_OFF = (0, 0, 0)              # Apagado

# Cores Exclusivas para Bloqueio de Tela / tmp
COLOR_PURE_BLUE = (0, 0, 255)
COLOR_PURE_MAGENTA = (255, 0, 255)

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
    epp_path = '/sys/devices/system/cpu/cpu0/cpufreq/energy_performance_preference'
    if os.path.exists(epp_path):
        try:
            with open(epp_path, 'r') as f:
                epp = f.read().strip()
                if epp == 'performance': return "MAX_PERF"
                if epp in ['power', 'powersave']: return "POWER_SAVE"
                return "BALANCED"
        except Exception:
            pass

    gov_path = '/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor'
    if os.path.exists(gov_path):
        try:
            with open(gov_path, 'r') as f:
                gov = f.read().strip()
                if gov == 'performance': return "MAX_PERF"
                if gov == 'powersave': return "POWER_SAVE"
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
        output = subprocess.check_output(["pgrep", "-i", "llama|ollama"], text=True)
        if output.strip():
            return True
    except subprocess.CalledProcessError:
        pass

    return False

def is_screen_locked():
    try:
        user = pwd.getpwuid(os.getuid()).pw_name
        sessions_output = subprocess.check_output(["loginctl", "list-sessions", "--no-legend"], text=True)
        for line in sessions_output.strip().split('\n'):
            if user in line:
                session_id = line.split()[0]
                locked = subprocess.check_output(["loginctl", "show-session", session_id, "-p", "LockedHint", "--value"], text=True).strip()
                if locked == "yes":
                    return True
    except Exception:
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

def generate_fan_frame(ai_active, temp, current_position, power_mode, is_locked, tick):
    temp_clamped = max(46.0, min(95.0, temp))
    temp_factor = (temp_clamped - 46.0) / 49.0

    # =========================================================================
    # CENÁRIO 4: ECONOMIA DE ENERGIA - Efeito Estrela Cadente Fluida (Ciano)
    # =========================================================================
    if power_mode == "POWER_SAVE":
        frame = []
        continuous_leader = (tick / 15.0) % NUM_LEDS_FAN

        for i in range(NUM_LEDS_FAN):
            diff = (i - continuous_leader) % NUM_LEDS_FAN
            if diff > NUM_LEDS_FAN / 2:
                diff -= NUM_LEDS_FAN

            brightness = 0.0
            if 0 <= diff <= 2.5:
                factor = 1.0 - (diff / 2.5)
                brightness = 0.10 * (factor ** 2)
            elif -4.5 <= diff < 0:
                factor = 1.0 - (abs(diff) / 4.5)
                brightness = 0.10 * (factor ** 2.5)

            frame.append(RGBColor(
                int(COLOR_CYAN[0] * brightness),
                int(COLOR_CYAN[1] * brightness),
                int(COLOR_CYAN[2] * brightness)
            ))
        return frame

    # =========================================================================
    # CENÁRIO 5: TELA BLOQUEADA
    # =========================================================================
    if is_locked or os.path.exists("/tmp/use_magenta"):
        wave = (math.sin(tick * (2 * math.pi / 250)) + 1.0) / 2.0
        ambient_color = blend_color(COLOR_PURE_BLUE, COLOR_PURE_MAGENTA, wave)
        dim_ambient = (int(ambient_color[0] * 0.15), int(ambient_color[1] * 0.15), int(ambient_color[2] * 0.15))
        return [RGBColor(*dim_ambient)] * NUM_LEDS_FAN

    # SELEÇÃO DE CORES BASE
    if power_mode == "MAX_PERF":
        base_colors = [COLOR_CYAN, COLOR_GREEN, COLOR_ORANGE]
    else:
        base_colors = [COLOR_CYAN, COLOR_GREEN, COLOR_YELLOW]

    # =========================================================================
    # CENÁRIO 1: OCIOSO (IA Desligada)
    # =========================================================================
    if not ai_active:
        if temp >= 60.0:
            active_colors = [COLOR_CYAN, COLOR_GREEN, COLOR_ORANGE, COLOR_RED, COLOR_RED]
        else:
            active_colors = base_colors

        stretch_factor = 1.5
        virtual_leds = int(NUM_LEDS_FAN * stretch_factor)
        smooth_pattern = create_smooth_palette(active_colors, virtual_leds)

        final_frame = []

        rhythm_speed = tick / 12.0
        continuous_leader = rhythm_speed % NUM_LEDS_FAN
        shift_amount = int(rhythm_speed)

        for i in range(NUM_LEDS_FAN):
            if power_mode == "MAX_PERF":
                # MODO ALTO DESEMPENHO: Todos os LEDs acesos (80% de brilho) e fita gira
                c = smooth_pattern[(shift_amount + i) % virtual_leds]
                brightness = 0.80
            else:
                # MODO BALANCEADO: Fita estática no fundo (20% brilho) + Estrela passando a 80%
                c = smooth_pattern[i % virtual_leds]

                diff = (i - continuous_leader) % NUM_LEDS_FAN
                if diff > NUM_LEDS_FAN / 2:
                    diff -= NUM_LEDS_FAN

                base_glow = 0.20 # O fundo nunca apaga totalmente
                star_brightness = 0.0

                if 0 <= diff <= 2.5:
                    factor = 1.0 - (diff / 2.5)
                    star_brightness = 0.80 * (factor ** 2)
                elif -5.5 <= diff < 0:
                    factor = 1.0 - (abs(diff) / 5.5)
                    star_brightness = 0.80 * (factor ** 2.5)

                # Usa o brilho da estrela se for maior que o brilho de fundo
                brightness = max(base_glow, star_brightness)

            r, g, b = c[0] * brightness, c[1] * brightness, c[2] * brightness

            if temp >= 60.0 and c[0] > 150 and c[2] < 100:
                flicker = random.uniform(-0.25, 0.25)
                r = min(255, max(0, r * (1.0 + flicker)))
                g = min(255, max(0, g * (1.0 + flicker)))
                b = min(255, max(0, b * (1.0 + flicker)))

            final_frame.append(RGBColor(int(r), int(g), int(b)))

        return final_frame

    # =========================================================================
    # CENÁRIOS 2 e 3: IA ATIVA (Cometa ou Núcleo de Fusão Térmico)
    # =========================================================================
    shift_amount = int(current_position)

    if temp >= 80.0:
        active_colors = [COLOR_CYAN, COLOR_GREEN, COLOR_ORANGE, COLOR_RED, COLOR_RED]
        dim_factor = 0.8 + (0.2 * temp_factor)
    else:
        active_colors = base_colors
        dim_factor = 0.6 + (0.4 * temp_factor)

    if power_mode == "MAX_PERF":
        dim_factor = min(1.0, dim_factor + 0.05)

    stretch_factor = 1.0
    virtual_leds = int(NUM_LEDS_FAN * stretch_factor)
    smooth_pattern = create_smooth_palette(active_colors, virtual_leds)

    final_frame = []
    for i in range(NUM_LEDS_FAN):
        c = smooth_pattern[(shift_amount + i) % virtual_leds]
        r, g, b = c[0] * dim_factor, c[1] * dim_factor, c[2] * dim_factor

        if temp >= 80.0 and c[0] > 150 and c[2] < 100:
            flicker = random.uniform(-0.25, 0.25)
            r = min(255, max(0, r * (1.0 + flicker)))
            g = min(255, max(0, g * (1.0 + flicker)))
            b = min(255, max(0, b * (1.0 + flicker)))

        final_frame.append(RGBColor(int(r), int(g), int(b)))

    return final_frame

def main(verbose=False):
    client = None
    fan_zone = None
    tick = 0
    current_position = 0.0

    ai_active = False
    is_locked = False
    temp = 0.0
    power_mode = "BALANCED"

    while True:
        if client is None or fan_zone is None:
            try:
                client = OpenRGBClient(OPENRGB_HOST, 6742)
                device = next((d for d in client.devices if 'ASUS' in d.name or 'B650M' in d.name), None)

                if not device:
                    if verbose: print("Aguardando placa-mãe...")
                    client = None
                    time.sleep(5)
                    continue

                try:
                    device.set_mode('direct')
                except Exception:
                    pass

                fan_zone = next((z for z in device.zones if 'Addressable 3' in z.name), None)
                if not fan_zone:
                    fan_zone = device.zones[-1]

                if verbose: print(f"Conectado: '{fan_zone.name}'!")
            except Exception as e:
                if verbose: print(f"Aguardando Flatpak... ({e})")
                client = None
                fan_zone = None
                time.sleep(5)
                continue

        try:
            if tick % 100 == 0:
                power_mode = get_power_mode()
                temp = get_cpu_temp()
                ai_active = is_ai_running()
                is_locked = is_screen_locked()

                if verbose:
                    print(f"Temp: {temp:.1f}°C | Modo: {power_mode} | IA: {ai_active} | Bloq: {is_locked}")

            temp_clamped = max(46.0, min(95.0, temp))
            temp_factor = (temp_clamped - 46.0) / 49.0

            if is_locked or os.path.exists("/tmp/use_magenta"):
                speed = 0.0
            elif ai_active:
                speed = 0.1 + (1.5 * (temp_factor ** 2.0))
            else:
                speed = 0.0

            current_position += speed

            frame = generate_fan_frame(ai_active, temp, current_position, power_mode, is_locked, tick)
            fan_zone.set_colors(frame)

            tick += 1
            time.sleep(0.02) # 50Hz

        except (ConnectionResetError, BrokenPipeError):
            if verbose: print("Reconectando...")
            client = None
            fan_zone = None
            time.sleep(2)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    main(verbose=args.verbose)
