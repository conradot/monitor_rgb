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
OPENRGB_HOST = "127.0.0.1"
NUM_LEDS_FAN = 16

# =========================================================================
# CORES IBM WATSON / CARBON DESIGN SYSTEM
# =========================================================================
COLOR_IBM_BLUE = (15, 98, 254)        # Blue 60 (Estabilidade, Base)
COLOR_DEEP_BLUE = (0, 45, 156)        # Blue 80 (Fundo / repouso absoluto)
COLOR_WATSON_CYAN = (0, 255, 255)     # Cyan (Processamento / Ciano brilhante)
COLOR_WATSON_TEAL = (0, 157, 154)     # Teal 50 (Fluxo de dados, Turquesa)
COLOR_WATSON_PURPLE = (138, 63, 252)  # Purple 50 (Alta energia)
COLOR_WATSON_MAGENTA = (238, 83, 150) # Magenta 50 (Inteligência ativa)
COLOR_WHITE = (255, 255, 255)         # Branco frio (Picos de processamento)
COLOR_ALERT_RED = (218, 30, 40)       # Red 60 (Sobrecarga / Hardware Critical)
COLOR_OFF = (0, 0, 0)                 # Apagado

# =========================================================================
# CLASSES DE TELEMETRIA E RENDERIZAÇÃO
# =========================================================================

class SystemTelemetry:
    """Gerencia todas as chamadas de I/O de telemetria da máquina."""
    def __init__(self):
        self.OLLAMA_API = "http://localhost:11434/api/ps"
        self.temp = 0.0
        self.power_mode = "BALANCED"
        self.ai_active = False
        self.is_locked = False

    def update(self):
        self.temp = self._get_cpu_temp()
        self.power_mode = self._get_power_mode()
        self.ai_active = self._is_ai_running()
        self.is_locked = self._is_screen_locked()

    def _get_cpu_temp(self):
        try:
            for hwmon in os.listdir('/sys/class/hwmon'):
                with open(f'/sys/class/hwmon/{hwmon}/name', 'r') as f:
                    if f.read().strip() in ['k10temp', 'zenpower']:
                        with open(f'/sys/class/hwmon/{hwmon}/temp1_input', 'r') as f:
                            return int(f.read().strip()) / 1000.0
        except Exception:
            pass
        return 0.0

    def _get_power_mode(self):
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

    def _is_ai_running(self):
        try:
            response = requests.get(self.OLLAMA_API, timeout=0.5)
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

    def _is_screen_locked(self):
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
    """Interpolação linear de cores para criar paletas suaves."""
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


class RGBRenderer:
    """Isola a lógica visual e renderização de cada modo operacional (Efeitos)."""
    def __init__(self, num_leds):
        self.num_leds = num_leds

    def render_power_save(self, tick, ai_active, current_position):
        # Ocioso: Pulso Vital - Respiração sutil em Deep Blue / Ciano Escuro
        frame = []
        breathe = (math.sin(tick * (2 * math.pi / 200)) + 1.0) / 2.0  # Onda de 0 a 1
        base_color = blend_color(COLOR_DEEP_BLUE, COLOR_WATSON_CYAN, breathe)
        dim_factor = 0.05 + (0.10 * breathe) # 5% a 15% brilho
        
        for i in range(self.num_leds):
            r, g, b = [int(c * dim_factor) for c in base_color]
            
            # IA Ativa: Fantasma Sintético - Trilha quase invisível em Teal
            if ai_active:
                leader = int(current_position) % self.num_leds
                if i == leader:
                    r, g, b = [int(max(r, c * 0.30)) for c in COLOR_WATSON_TEAL]
                elif i == (leader - 1) % self.num_leds:
                    r, g, b = [int(max(r, c * 0.15)) for c in COLOR_WATSON_TEAL]
            
            frame.append(RGBColor(r, g, b))
        return frame

    def render_balanced(self, tick, ai_active, current_position):
        # Ocioso: Fluxo de Dados - Maré de Ciano e Deep Blue girando bem levemente
        palette_colors = [COLOR_DEEP_BLUE, COLOR_WATSON_CYAN, COLOR_IBM_BLUE]
        smooth_pattern = create_smooth_palette(palette_colors, self.num_leds)
        shift_amount = int(tick / 15.0) % self.num_leds
        
        frame = []
        for i in range(self.num_leds):
            c = smooth_pattern[(shift_amount + i) % self.num_leds]
            r, g, b = [int(x * 0.40) for x in c] # 40% de brilho de fundo
            
            # IA Ativa: Sintaxe Ativa - Cometa em Magenta rodando por cima
            if ai_active:
                leader = current_position % self.num_leds
                diff = (i - leader) % self.num_leds
                if diff > self.num_leds / 2:
                    diff -= self.num_leds
                
                # Renderiza Cometa (Cabeça em Magenta, Cauda em Roxo)
                if 0 <= diff <= 1.5: 
                    factor = 1.0 - (diff / 1.5)
                    comet_color = COLOR_WATSON_MAGENTA
                    r = int(blend_color((r,g,b), comet_color, factor)[0] * 0.8)
                    g = int(blend_color((r,g,b), comet_color, factor)[1] * 0.8)
                    b = int(blend_color((r,g,b), comet_color, factor)[2] * 0.8)
                elif -3.5 <= diff < 0:
                    factor = 1.0 - (abs(diff) / 3.5)
                    comet_color = COLOR_WATSON_PURPLE
                    r = int(blend_color((r,g,b), comet_color, factor)[0] * 0.6)
                    g = int(blend_color((r,g,b), comet_color, factor)[1] * 0.6)
                    b = int(blend_color((r,g,b), comet_color, factor)[2] * 0.6)
            else:
                # Watson Idle Presence: Um cometa muito suave em Teal/Purple girando devagar
                idle_leader = (tick / 10.0) % self.num_leds
                diff = (i - idle_leader) % self.num_leds
                if diff > self.num_leds / 2:
                    diff -= self.num_leds
                
                if 0 <= diff <= 2.0:
                    factor = 1.0 - (diff / 2.0)
                    idle_color = COLOR_WATSON_PURPLE
                    r = int(blend_color((r,g,b), idle_color, factor)[0] * 0.6)
                    g = int(blend_color((r,g,b), idle_color, factor)[1] * 0.6)
                    b = int(blend_color((r,g,b), idle_color, factor)[2] * 0.6)
                    
            frame.append(RGBColor(r, g, b))
        return frame

    def render_max_perf(self, tick, ai_active, current_position, temp_factor):
        # Ocioso: Nó de Computação - Circulação de Roxo, Magenta e Ciano
        palette_colors = [COLOR_WATSON_MAGENTA, COLOR_WATSON_PURPLE, COLOR_WATSON_CYAN]
        virtual_leds = int(self.num_leds * 1.5)
        smooth_pattern = create_smooth_palette(palette_colors, virtual_leds)
        
        if ai_active:
            shift_amount = int(current_position) % virtual_leds
        else:
            shift_amount = int(tick / 5.0) % virtual_leds
            
        frame = []
        for i in range(self.num_leds):
            c = smooth_pattern[(shift_amount + i) % virtual_leds]
            brightness = 0.80 # 80% brilho nativo
            r, g, b = [int(x * brightness) for x in c]
            
            # IA Ativa: Cometa Neural - Cometa base branca e rastro esticado magenta
            if ai_active:
                leader = current_position % self.num_leds
                diff = (i - leader) % self.num_leds
                if diff > self.num_leds / 2:
                    diff -= self.num_leds
                    
                if 0 <= diff <= 1.0: 
                    factor = 1.0 - diff
                    r = int(blend_color((r,g,b), COLOR_WHITE, factor)[0])
                    g = int(blend_color((r,g,b), COLOR_WHITE, factor)[1])
                    b = int(blend_color((r,g,b), COLOR_WHITE, factor)[2])
                elif -4.0 <= diff < 0:
                    factor = 1.0 - (abs(diff) / 4.0)
                    r = int(blend_color((r,g,b), COLOR_WATSON_MAGENTA, factor)[0])
                    g = int(blend_color((r,g,b), COLOR_WATSON_MAGENTA, factor)[1])
                    b = int(blend_color((r,g,b), COLOR_WATSON_MAGENTA, factor)[2])

            frame.append(RGBColor(r, g, b))
        return frame

    def render_locked(self, tick):
        # Tela bloqueada em onda Azul/Magenta constante
        wave = (math.sin(tick * (2 * math.pi / 250)) + 1.0) / 2.0
        ambient_color = blend_color(COLOR_IBM_BLUE, COLOR_WATSON_MAGENTA, wave)
        dim_ambient = [int(c * 0.15) for c in ambient_color]
        return [RGBColor(*dim_ambient)] * self.num_leds

    def apply_thermal_stress(self, frame, temp):
        # Núcleo de Fusão Térmico - Red flicker overrides
        if temp >= 80.0:
            stressed_frame = []
            for color in frame:
                r = int(min(255, color.red * 0.5 + COLOR_ALERT_RED[0] * 0.8))
                g = int(color.green * 0.4)
                b = int(color.blue * 0.4)
                
                flicker = random.uniform(-0.30, 0.30)
                r = min(255, max(0, int(r * (1.0 + flicker))))
                g = min(255, max(0, int(g * (1.0 + flicker))))
                b = min(255, max(0, int(b * (1.0 + flicker))))
                
                stressed_frame.append(RGBColor(r, g, b))
            return stressed_frame
        return frame
        
    def generate_frame(self, telemetry, tick, current_position):
        if telemetry.is_locked or os.path.exists("/tmp/use_magenta"):
            return self.render_locked(tick)
            
        temp_clamped = max(46.0, min(95.0, telemetry.temp))
        temp_factor = (temp_clamped - 46.0) / 49.0
        
        if telemetry.power_mode == "POWER_SAVE":
            frame = self.render_power_save(tick, telemetry.ai_active, current_position)
        elif telemetry.power_mode == "MAX_PERF":
            frame = self.render_max_perf(tick, telemetry.ai_active, current_position, temp_factor)
        else:
            frame = self.render_balanced(tick, telemetry.ai_active, current_position)
            
        return self.apply_thermal_stress(frame, telemetry.temp)


# =========================================================================
# MAIN LOOP ORQUESTRADOR
# =========================================================================
def main(verbose=False):
    client = None
    fan_zone = None
    tick = 0
    current_position = 0.0

    telemetry = SystemTelemetry()
    renderer = RGBRenderer(NUM_LEDS_FAN)

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
                if verbose: print(f"Aguardando OpenRGB... ({e})")
                client = None
                fan_zone = None
                time.sleep(5)
                continue

        try:
            # Polling da Telemetria a cada 100 ticks (2 segundos a 50Hz)
            if tick % 100 == 0:
                telemetry.update()
                if verbose:
                    print(f"Temp: {telemetry.temp:.1f}°C | Modo: {telemetry.power_mode} | IA: {telemetry.ai_active} | Bloq: {telemetry.is_locked}")

            # Define velocidade do Cometa baseado na IA e temperatura
            if telemetry.is_locked or os.path.exists("/tmp/use_magenta"):
                speed = 0.0
            elif telemetry.ai_active:
                temp_clamped = max(46.0, min(95.0, telemetry.temp))
                temp_factor = (temp_clamped - 46.0) / 49.0
                if telemetry.power_mode == "POWER_SAVE":
                    speed = 0.05
                elif telemetry.power_mode == "MAX_PERF":
                    speed = 0.3 + (2.0 * (temp_factor ** 2.0))
                else:
                    speed = 0.15 + (1.0 * (temp_factor ** 2.0))
            else:
                speed = 0.0

            current_position += speed

            # Gera e aplica o frame
            frame = renderer.generate_frame(telemetry, tick, current_position)
            fan_zone.set_colors(frame)

            tick += 1
            time.sleep(0.02) # Trava em 50Hz

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
