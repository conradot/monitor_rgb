import time
import requests
import os
from openrgb import OpenRGBClient
from openrgb.utils import RGBColor

# Configurações
OLLAMA_API = "http://localhost:11434/api/ps"
OPENRGB_HOST = "127.0.0.1"
NUM_LEDS_FAN = 16

# DEFINIÇÃO DE CORES COM SUPER SATURAÇÃO
COLOR_BLUE = (0, 0, 255)       # Azul Puro
COLOR_GREEN = (0, 255, 20)     # Verde Neon
COLOR_YELLOW = (255, 215, 0)   # Amarelo Ouro
COLOR_MAGENTA = (255, 0, 255)  # Magenta Puro (Roxo)
COLOR_ORANGE = (255, 50, 0)    # Laranja Fogo
COLOR_RED = (255, 0, 0)        # Vermelho Alerta
COLOR_OFF = (0, 0, 0)          # Luz Desligada

def get_cpu_temp():
    """Lê a temperatura real do Ryzen direto do driver do kernel (k10temp)."""
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
    """Detecta o perfil de energia correto do sistema operacional (Host)."""
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

def blend_color(color_init, color_target, factor):
    """Mistura linearmente duas cores com base em um fator de 0.0 a 1.0."""
    r = int(color_init[0] + (color_target[0] - color_init[0]) * factor)
    g = int(color_init[1] + (color_target[1] - color_init[1]) * factor)
    b = int(color_init[2] + (color_target[2] - color_init[2]) * factor)
    return (r, g, b)

def generate_fan_frame(ollama_active, temp, tick, power_mode, idle_palette_phase):
    """Gera o frame dos 16 LEDs com a hierarquia correta de prioridades."""

    # PRIORIDADE 1: Se o modo for Economia de Energia, apaga tudo
    if power_mode == "POWER_SAVE":
        return [RGBColor(*COLOR_OFF)] * NUM_LEDS_FAN

    # PRIORIDADE 2: Alertas Térmicos Globais (Giro rápido Laranja/Vermelho)
    if temp > 70.0:
        base_pattern = [COLOR_RED] * 8 + [(20, 0, 0)] * 8
        shift = tick % NUM_LEDS_FAN
        return [RGBColor(*c) for c in (base_pattern[shift:] + base_pattern[:shift])]

    if 60.0 <= temp <= 70.0:
        base_pattern = [COLOR_ORANGE] * 8 + [(25, 5, 0)] * 8
        shift = tick % NUM_LEDS_FAN
        return [RGBColor(*c) for c in (base_pattern[shift:] + base_pattern[:shift])]

    # PRIORIDADE 3: Modo Ativo (Ollama ou Desempenho Máximo) -> Giro Rápido 4 cores
    if power_mode == "MAX_PERF" or ollama_active:
        base_jeopardy = [COLOR_BLUE] * 4 + [COLOR_GREEN] * 4 + [COLOR_YELLOW] * 4 + [COLOR_MAGENTA] * 4
        shift = tick % NUM_LEDS_FAN
        return [RGBColor(*c) for c in (base_jeopardy[shift:] + base_jeopardy[:shift])]

    # PRIORIDADE 4: MODO BALANCEADO / IDLE (Sem Ollama e CPU fria)
    # Brilho reduzido em 40% com rotação ultra lenta contínua
    dim_factor = 0.4

    if idle_palette_phase == 0:
        # Sub-modo 1: Paleta unificada de 4 cores
        base_idle = [COLOR_BLUE] * 4 + [COLOR_MAGENTA] * 4 + [COLOR_GREEN] * 4 + [COLOR_YELLOW] * 4
    else:
        # Sub-modo 2: Apenas o seu Roxo (Magenta) e Azul Puro (pedido atual)
        base_idle = [COLOR_BLUE] * 4 + [COLOR_MAGENTA] * 4 + [COLOR_BLUE] * 4 + [COLOR_MAGENTA] * 4

    idle_pattern = [
        (int(c[0] * dim_factor), int(c[1] * dim_factor), int(c[2] * dim_factor))
        for c in base_idle
    ]
    # Mantém o giro ultra lento idêntico em ambos os sub-modos
    shift = (tick // 15) % NUM_LEDS_FAN
    rotated_idle = idle_pattern[shift:] + idle_pattern[:shift]
    return [RGBColor(*c) for c in rotated_idle]

def main():
    client = None
    tick = 0
    ollama_active = False
    temp = 0.0
    power_mode = "BALANCED"

    # Gerenciador da paleta de Idle (Alterna a cada 10 segundos / 100 ticks)
    idle_palette_phase = 0
    idle_timer = 0

    while True:
        if client is None:
            try:
                client = OpenRGBClient(OPENRGB_HOST, 6742)
                device = next((d for d in client.devices if d.name == 'ASUS B650M-AYW WIFI'), None)
                if not device:
                    print("Placa-mãe ASUS B650M-AYW WIFI não encontrada.")
                    return
                fan_zone = device.zones[2]
                print("Conectado ao OpenRGB SDK com sucesso!")
            except Exception:
                print("Aguardando servidor OpenRGB iniciar...")
                time.sleep(5)
                continue

        try:
            if tick % 20 == 0:
                power_mode = get_power_mode()
                try:
                    temp = get_cpu_temp()
                    response = requests.get(OLLAMA_API, timeout=1)
                    ollama_active = bool(response.json().get("models"))
                except Exception:
                    ollama_active = False

            # Lógica de alternância temporal da paleta apenas quando em Idle
            if power_mode == "BALANCED" and not ollama_active and temp < 60.0:
                idle_timer += 1
                if idle_timer >= 100: # 10 segundos
                    idle_palette_phase = 1 - idle_palette_phase
                    idle_timer = 0
            else:
                idle_timer = 0
                idle_palette_phase = 0

            frame = generate_fan_frame(ollama_active, temp, tick, power_mode, idle_palette_phase)
            fan_zone.set_colors(frame)

            tick += 1
            time.sleep(0.1)

        except (ConnectionResetError, BrokenPipeError):
            print("Conexão com o OpenRGB perdida. Reabastecendo conexão...")
            client = None
            time.sleep(2)

if __name__ == "__main__":
    main()
