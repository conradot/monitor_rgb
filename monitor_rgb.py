import time
import requests
import os
import subprocess
import pwd
from openrgb import OpenRGBClient
from openrgb.utils import RGBColor

# Configurações
OLLAMA_API = "http://localhost:11434/api/ps"
OPENRGB_HOST = "127.0.0.1"
NUM_LEDS_FAN = 16

# DEFINIÇÃO DE CORES
COLOR_CYAN = (0, 200, 255)         # Azul Watson (Turquesa)
COLOR_GREEN = (0, 255, 20)         # Verde Neon
COLOR_YELLOW = (255, 215, 0)       # Amarelo Ouro
COLOR_ORANGE = (255, 50, 0)        # Laranja Fogo
COLOR_RED = (255, 0, 0)            # Vermelho Alerta
COLOR_OFF = (0, 0, 0)              # Apagado

# Cores Exclusivas para Bloqueio de Tela e Flag /tmp
COLOR_PURE_BLUE = (0, 0, 255)      # Azul Puro
COLOR_PURE_MAGENTA = (255, 0, 255) # Magenta Puro

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
    """Detecta o perfil via driver AMD P-State ou Scaling Governor genérico."""
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
    """Verifica pelo systemd (loginctl) se a sessão do usuário atual está bloqueada."""
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

def get_temp_color(temp):
    """Escalada mais agressiva baseada na temperatura do Ryzen."""
    temp_min = 48.0  # Começa a escalar logo ao sair do estado normal (45-47)
    temp_mid = 58.0  # Atinge o Laranja bem mais cedo
    temp_max = 68.0  # Chega no Vermelho intenso muito rápido

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

def generate_fan_frame(ai_active, temp, tick, power_mode, is_locked):
    if power_mode == "POWER_SAVE":
        return [RGBColor(*COLOR_OFF)] * NUM_LEDS_FAN

    # ALERTA TÉRMICO EXTREMO (Ajustado para 65°C para não matar o gradiente cedo demais)
    if temp > 65.0:
        base_color = get_temp_color(temp)
        pattern = [base_color] * NUM_LEDS_FAN

        pattern[0] = blend_color(base_color, COLOR_OFF, 0.7)
        pattern[8] = blend_color(base_color, COLOR_OFF, 0.7)

        speed = int(2 + (temp - 65) / 5)
        shift = (tick * speed) % NUM_LEDS_FAN
        rotated = pattern[shift:] + pattern[:shift]
        return [RGBColor(*c) for c in rotated]

    # SELEÇÃO DA BASE DE CORES (Bloqueio de tela tem prioridade)
    if is_locked or os.path.exists("/tmp/use_magenta"):
        base_colors = [COLOR_PURE_BLUE, COLOR_PURE_MAGENTA]
    else:
        # Paleta Watson nativa limpa do azul puro e magenta
        dynamic_yellow = get_temp_color(temp)
        base_colors = [COLOR_CYAN, COLOR_GREEN, dynamic_yellow]

    # DEFINIÇÃO DE COMPORTAMENTO
#    if ai_active and not is_locked:
#        stretch_factor = 1
#        shift_amount = int(tick * 1.5) # Velocidade reduzida para a IA
#        dim_factor = 1.0
#    elif power_mode == "MAX_PERF" and not is_locked:
#        stretch_factor = 1
#        shift_amount = (tick // 2)
#        dim_factor = 0.7
#    else:
#        stretch_factor = 2
#        shift_amount = (tick // 3)
#        dim_factor = 0.4

# DEFINIÇÃO DE COMPORTAMENTO
    if ai_active and not is_locked:
        stretch_factor = 1.0
        shift_amount = int(tick * 1.5) # Velocidade reduzida para a IA
        dim_factor = 1.0
    elif power_mode == "MAX_PERF" and not is_locked:
        stretch_factor = 1.0
        shift_amount = (tick // 2)
        dim_factor = 0.7
    else:
        # REDUZIDO AQUI: Antes era 2 (muito esticado).
        # Você pode testar 1.5, 1.3 ou 1.2 até achar o tamanho perfeito das faixas.
        stretch_factor = 1.5
        shift_amount = (tick // 3)
        dim_factor = 0.4

    # Adicionado o int() para permitir o uso de números quebrados no stretch_factor
    virtual_leds = int(NUM_LEDS_FAN * stretch_factor)
    smooth_pattern = create_smooth_palette(base_colors, virtual_leds)


    final_frame = []
    for i in range(NUM_LEDS_FAN):
        idx = (shift_amount + i) % virtual_leds
        c = smooth_pattern[idx]
        final_frame.append(
            RGBColor(int(c[0] * dim_factor), int(c[1] * dim_factor), int(c[2] * dim_factor))
        )

    return final_frame

def main():
    client = None
    fan_zone = None
    tick = 0
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
                    print("Servidor conectado, mas a placa-mãe não foi encontrada. Aguardando...")
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
                is_locked = is_screen_locked()
                print(f"[MONITOR] Temp: {temp:.1f}°C | Perfil: {power_mode} | IA: {ai_active} | Bloqueado: {is_locked}")

            frame = generate_fan_frame(ai_active, temp, tick, power_mode, is_locked)
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
