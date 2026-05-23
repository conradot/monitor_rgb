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

# Separação de LEDs
LEDS_INTERNOS = range(0, 8)    # LEDs 1-8 (índices 0-7)
LEDS_EXTERNOS = range(8, 16)   # LEDs 9-16 (índices 8-15)

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
COLOR_WARN_WHITE = (255, 230, 200)    # Branco quente (Picos com tom mais suave)
COLOR_ALERT_RED = (218, 30, 40)       # Red 60 (Sobrecarga / Hardware Critical)
COLOR_OFF = (0, 0, 0)                 # Apagado

# IBM Jeopardy palette
COLOR_CYAN = (0, 200, 255)           # Azul Watson (Turquesa / Base)
COLOR_GREEN = (0, 255, 20)           # Verde Neon (Atividade)
COLOR_YELLOW = (255, 215, 0)         # Amarelo Ouro (Pensamento / Resposta)

# Cores para gradação térmica dos LEDs internos (Amarelo→Laranja→Vermelho)
COLOR_HEAT_YELLOW = (255, 215, 0)    # Amarelo
COLOR_HEAT_ORANGE = (255, 140, 0)    # Laranja
COLOR_HEAT_RED = (255, 40, 40)       # Vermelho quente

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
    def __init__(self, num_leds, jeopardy=False):
        self.num_leds = num_leds
        self.use_jeopardy = jeopardy
        self.heat_spark_index = None
        self.heat_spark_timer = 0

    def _base_palette(self):
        if self.use_jeopardy:
            return [COLOR_CYAN, COLOR_GREEN, COLOR_YELLOW]
        return [COLOR_DEEP_BLUE, COLOR_WATSON_CYAN, COLOR_IBM_BLUE]

    def _heat_tinted(self, color, temp_factor, max_shift=0.75):
        heat_shift = max(0.0, min(1.0, (temp_factor - 0.20) / 0.80)) * max_shift
        return blend_color(color, COLOR_ALERT_RED, heat_shift)

    def _colorize(self, color, brightness, temp_factor):
        r, g, b = self._heat_tinted(color, temp_factor)
        return [int(max(0, min(255, c * brightness))) for c in (r, g, b)]

    def _is_rotor_gap(self, index, position, width=2):
        leader = int(position) % self.num_leds
        offset = (index - leader) % self.num_leds
        return offset < width

    def _get_thermal_gradient_color(self, temp_factor):
        """Retorna cor gradual amarelo→laranja→vermelho baseado na temperatura."""
        # temp_factor: 0.0 (46°C) a 1.0 (95°C)
        if temp_factor < 0.5:
            # Amarelo → Laranja (0.0 a 0.5 → gradação)
            factor = temp_factor * 2.0  # 0.0 a 1.0
            return blend_color(COLOR_HEAT_YELLOW, COLOR_HEAT_ORANGE, factor)
        else:
            # Laranja → Vermelho (0.5 a 1.0 → gradação)
            factor = (temp_factor - 0.5) * 2.0  # 0.0 a 1.0
            return blend_color(COLOR_HEAT_ORANGE, COLOR_HEAT_RED, factor)

    def _sync_led_color(self, index, color):
        """Sincroniza cor entre LEDs internos (0-7) e externos (8-15)."""
        if index in LEDS_INTERNOS:
            # LED interno: mantém a cor original
            return color
        elif index in LEDS_EXTERNOS:
            # LED externo: usa cor do LED interno correspondente
            internal_index = index - 8  # Converte 8-15 para 0-7
            return color  # Será sincronizado no apply_thermal_stress
        return color

    def render_power_save(self, tick, ai_active, current_position, temp_factor):
        # Ocioso: Pulso Vital - Respiração sutil em Deep Blue / Ciano Escuro
        palette = create_smooth_palette(self._base_palette(), self.num_leds)
        breathe = (math.sin(tick * (2 * math.pi / 220)) + 1.0) / 2.0
        brightness = 0.15 + (0.10 * breathe)
        shift_amount = int(tick / 30.0) % self.num_leds
        active_color = COLOR_GREEN if self.use_jeopardy else COLOR_WATSON_TEAL

        frame = []
        for i in range(self.num_leds):
            if self._is_rotor_gap(i, current_position):
                frame.append(RGBColor(*COLOR_OFF))
                continue

            base_color = palette[(shift_amount + i) % self.num_leds]
            r, g, b = self._colorize(base_color, brightness, temp_factor)

            if ai_active:
                leader = int(current_position) % self.num_leds
                if i == leader:
                    r, g, b = self._colorize(active_color, 0.30, temp_factor)
                elif i == (leader - 1) % self.num_leds:
                    r, g, b = self._colorize(active_color, 0.15, temp_factor)

            frame.append(RGBColor(r, g, b))
        return frame

    def render_balanced(self, tick, ai_active, current_position, temp_factor):
        # Ocioso: Fluxo de Dados - Maré de cores girando levemente
        palette = create_smooth_palette(self._base_palette(), self.num_leds)
        shift_amount = int(tick / 18.0) % self.num_leds
        active_head = COLOR_YELLOW if self.use_jeopardy else COLOR_WATSON_MAGENTA
        active_tail = COLOR_GREEN if self.use_jeopardy else COLOR_WATSON_PURPLE

        frame = []
        for i in range(self.num_leds):
            if self._is_rotor_gap(i, current_position):
                frame.append(RGBColor(*COLOR_OFF))
                continue

            c = palette[(shift_amount + i) % self.num_leds]
            r, g, b = self._colorize(c, 0.45, temp_factor)

            if ai_active:
                leader = current_position % self.num_leds
                diff = (i - leader) % self.num_leds
                if diff > self.num_leds / 2:
                    diff -= self.num_leds

                if 0 <= diff <= 1.5:
                    factor = 1.0 - (diff / 1.5)
                    r, g, b = self._colorize(blend_color((r, g, b), active_head, factor), 0.65, temp_factor)
                elif -3.5 <= diff < 0:
                    factor = 1.0 - (abs(diff) / 3.5)
                    r, g, b = self._colorize(blend_color((r, g, b), active_tail, factor), 0.50, temp_factor)
            else:
                idle_leader = (tick / 10.0) % self.num_leds
                diff = (i - idle_leader) % self.num_leds
                if diff > self.num_leds / 2:
                    diff -= self.num_leds

                if 0 <= diff <= 2.0:
                    factor = 1.0 - (diff / 2.0)
                    idle_color = COLOR_GREEN if self.use_jeopardy else COLOR_WATSON_PURPLE
                    r, g, b = self._colorize(blend_color((r, g, b), idle_color, factor), 0.55, temp_factor)

            frame.append(RGBColor(r, g, b))
        return frame

    def render_max_perf(self, tick, ai_active, current_position, temp_factor):
        # Ocioso: Nó de Computação - Circulação intensa com cores de alta performance
        if self.use_jeopardy:
            palette_colors = [COLOR_YELLOW, COLOR_GREEN, COLOR_CYAN]
        else:
            palette_colors = [COLOR_WATSON_MAGENTA, COLOR_WATSON_PURPLE, COLOR_WATSON_CYAN]

        virtual_leds = int(self.num_leds * 1.5)
        smooth_pattern = create_smooth_palette(palette_colors, virtual_leds)
        if ai_active:
            shift_amount = int(current_position) % virtual_leds
        else:
            shift_amount = int(tick / 5.0) % virtual_leds

        active_trail = COLOR_YELLOW if self.use_jeopardy else COLOR_WATSON_MAGENTA

        frame = []
        for i in range(self.num_leds):
            if self._is_rotor_gap(i, current_position):
                frame.append(RGBColor(*COLOR_OFF))
                continue

            c = smooth_pattern[(shift_amount + i) % virtual_leds]
            r, g, b = self._colorize(c, 0.92, temp_factor)

            if ai_active:
                leader = current_position % self.num_leds
                diff = (i - leader) % self.num_leds
                if diff > self.num_leds / 2:
                    diff -= self.num_leds

                if 0 <= diff <= 1.0:
                    factor = 1.0 - diff
                    r, g, b = self._colorize(blend_color((r, g, b), COLOR_WHITE, factor), 1.0, temp_factor)
                elif -4.0 <= diff < 0:
                    factor = 1.0 - (abs(diff) / 4.0)
                    r, g, b = self._colorize(blend_color((r, g, b), active_trail, factor), 0.85, temp_factor)

            frame.append(RGBColor(r, g, b))
        return frame

    def render_locked(self, tick):
        # Tela bloqueada em onda Azul/Magenta constante
        wave = (math.sin(tick * (2 * math.pi / 250)) + 1.0) / 2.0
        ambient_color = blend_color(COLOR_IBM_BLUE, COLOR_WATSON_MAGENTA, wave)
        dim_ambient = [int(c * 0.15) for c in ambient_color]
        return [RGBColor(*dim_ambient)] * self.num_leds

    def apply_thermal_stress(self, frame, temp, power_mode):
        # Núcleo de Fusão Térmico com sincronização LED interno↔externo
        # LEDs internos (0-7): gradação térmica (Amarelo→Laranja→Vermelho) + centelha
        # LEDs externos (8-15): apenas centelha (sincronizados com internos)
        
        if temp >= 60.0:
            stressed_frame = []
            spark_active = False
            
            # Calcular fator de temperatura para gradação (0.0 = 60°C, 1.0 = 95°C)
            temp_factor_thermal = max(0.0, min(1.0, (temp - 60.0) / 35.0))
            
            if power_mode == "POWER_SAVE" and temp >= 78.0:
                spark_chance = min(0.50, 0.15 + ((temp - 78.0) / 22.0))  
                spark_duration = random.randint(1, 2)
            elif power_mode == "MAX_PERF" and temp >= 74.0:
                spark_chance = min(0.55, 0.15 + ((temp - 74.0) / 18.0))  
                spark_duration = random.randint(1, 3)
            elif temp >= 82.0:
                spark_chance = 0.12 + ((temp - 82.0) / 40.0)  
                spark_duration = 1
            else:
                spark_chance = 0.0
                spark_duration = 0

            if self.heat_spark_timer <= 0 and random.random() < spark_chance:
                # Definir centelha aleatória nos LEDs externos apenas
                self.heat_spark_index = random.choice(list(LEDS_EXTERNOS))
                self.heat_spark_timer = spark_duration

            spark_active = self.heat_spark_timer > 0

            for index, color in enumerate(frame):
                if index in LEDS_INTERNOS:
                    # ===== LEDs INTERNOS: Gradação Térmica + Centelha =====
                    # Cor base com gradação amarelo→laranja→vermelho
                    thermal_color = self._get_thermal_gradient_color(temp_factor_thermal)
                    r = thermal_color[0]
                    g = thermal_color[1]
                    b = thermal_color[2]
                    
                    # Aplicar centelha opcional
                    if spark_active and index == self.heat_spark_index:
                        # Centelha branca com intensidade baseada em temperatura
                        white_intensity = 0.8 + (0.2 * temp_factor_thermal)
                        r = min(255, int(COLOR_WARN_WHITE[0] * white_intensity))
                        g = min(255, int(COLOR_WARN_WHITE[1] * white_intensity))
                        b = min(255, int(COLOR_WARN_WHITE[2] * white_intensity))
                    else:
                        # Flicker suave nos internos
                        flicker = random.uniform(-0.15, 0.15)
                        r = min(255, max(0, int(r * (1.0 + flicker))))
                        g = min(255, max(0, int(g * (1.0 + flicker))))
                        b = min(255, max(0, int(b * (1.0 + flicker))))
                    
                elif index in LEDS_EXTERNOS:
                    # ===== LEDs EXTERNOS: Apenas Centelha (sincronizado) =====
                    # Começar com cor base escura
                    r = int(color.red * 0.3)
                    g = int(color.green * 0.3)
                    b = int(color.blue * 0.3)
                    
                    # Aplicar centelha se houver
                    if spark_active and index == self.heat_spark_index:
                        # Centelha branca brilhante
                        white_intensity = 1.0 if self.heat_spark_timer >= 2 else 0.65
                        r = min(255, int(r * 0.1 + COLOR_WARN_WHITE[0] * white_intensity))
                        g = min(255, int(g * 0.1 + COLOR_WARN_WHITE[1] * white_intensity))
                        b = min(255, int(b * 0.1 + COLOR_WARN_WHITE[2] * white_intensity))
                    else:
                        # Flicker suave sem cor base (apenas centelha)
                        flicker = random.uniform(-0.20, 0.20)
                        r = min(255, max(0, int(r * (1.0 + flicker))))
                        g = min(255, max(0, int(g * (1.0 + flicker))))
                        b = min(255, max(0, int(b * (1.0 + flicker))))

                stressed_frame.append(RGBColor(r, g, b))

            if spark_active:
                self.heat_spark_timer -= 1
                if self.heat_spark_timer <= 0:
                    self.heat_spark_index = None
            return stressed_frame
        return frame
        
    def generate_frame(self, telemetry, tick, current_position):
        if telemetry.is_locked or os.path.exists("/tmp/use_magenta"):
            return self.render_locked(tick)
            
        temp_clamped = max(46.0, min(95.0, telemetry.temp))
        temp_factor = (temp_clamped - 46.0) / 49.0
        
        if telemetry.power_mode == "POWER_SAVE":
            frame = self.render_power_save(tick, telemetry.ai_active, current_position, temp_factor)
        elif telemetry.power_mode == "MAX_PERF":
            frame = self.render_max_perf(tick, telemetry.ai_active, current_position, temp_factor)
        else:
            frame = self.render_balanced(tick, telemetry.ai_active, current_position, temp_factor)
            
        return self.apply_thermal_stress(frame, telemetry.temp, telemetry.power_mode)


# =========================================================================
# MAIN LOOP ORQUESTRADOR
# =========================================================================
def main(verbose=False, jeopardy=False):
    client = None
    fan_zone = None
    tick = 0
    current_position = 0.0

    telemetry = SystemTelemetry()
    renderer = RGBRenderer(NUM_LEDS_FAN, jeopardy=jeopardy)

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

            # Define velocidade do Cometa baseado na IA, temperatura e modo
            if telemetry.is_locked or os.path.exists("/tmp/use_magenta"):
                speed = 0.0
            else:
                temp_clamped = max(46.0, min(95.0, telemetry.temp))
                temp_factor = (temp_clamped - 46.0) / 49.0
                if telemetry.ai_active:
                    if telemetry.power_mode == "POWER_SAVE":
                        speed = 0.05 + (0.12 * (temp_factor ** 1.8))
                    elif telemetry.power_mode == "MAX_PERF":
                        speed = 0.30 + (2.0 * (temp_factor ** 2.0))
                    else:
                        speed = 0.15 + (1.0 * (temp_factor ** 2.0))
                else:
                    if telemetry.power_mode == "POWER_SAVE":
                        speed = 0.02 + (0.10 * (temp_factor ** 1.6))
                    elif telemetry.power_mode == "MAX_PERF":
                        speed = 0.06 + (0.18 * (temp_factor ** 1.6))
                    else:
                        speed = 0.04 + (0.12 * (temp_factor ** 1.6))

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
    parser.add_argument("-j", "--jeopardy", action="store_true", help="Ativa paleta IBM Jeopardy")
    args = parser.parse_args()
    main(verbose=args.verbose, jeopardy=args.jeopardy)
