import time
import requests
import os
import subprocess
import pwd
import argparse
import math
import random
import re
import threading
from openrgb import OpenRGBClient
from openrgb.utils import RGBColor

# Configurações
OPENRGB_HOST = "127.0.0.1"
NUM_LEDS_FAN = 16

# =========================================================================
# CORES IBM WATSON (AVATAR DO JEOPARDY)
# =========================================================================
COLOR_CYAN = (0, 200, 255)         # Azul Watson (Turquesa / Base)
COLOR_GREEN = (0, 255, 20)         # Verde Neon (Atividade)
COLOR_YELLOW = (255, 215, 0)       # Amarelo Ouro (Pensamento / Resposta)
COLOR_ORANGE = (255, 60, 0)        # Laranja Intenso (Processamento pesado)
COLOR_RED = (255, 0, 0)            # Vermelho Crítico (Estresse Térmico)
COLOR_OFF = (0, 0, 0)              # Apagado

# Cor do Standby (apenas 1 LED aceso bem suave)
COLOR_SLEEP = (0, 6, 8)            # Ciano ultra suave

# Cores Exclusivas para Bloqueio de Tela / tmp
COLOR_PURE_BLUE = (0, 0, 255)
COLOR_PURE_MAGENTA = (255, 0, 255)

# =========================================================================
# CLASSES DE TELEMETRIA E RENDERIZAÇÃO
# =========================================================================

class SystemTelemetry:
    """Gerencia todas as chamadas de I/O de telemetria da máquina em uma thread de background."""
    def __init__(self):
        self.OLLAMA_API = "http://localhost:11434/api/ps"
        self.temp = 0.0
        self.power_mode = "BALANCED"
        self.ai_active = False
        self.is_locked = False
        self.is_suspended = False
        self._stop_event = threading.Event()
        self._thread = None

    def start(self):
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=0.5)

    def _run_loop(self):
        while not self._stop_event.is_set():
            try:
                if not self.is_suspended:
                    self.update()
            except Exception:
                pass
            self._stop_event.wait(0.2)

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


class SuspendDetector:
    def __init__(self):
        self.process = None
        self.buffer = ""
        self.is_suspended = False
        self.start_monitor()

    def start_monitor(self):
        try:
            if self.process:
                try:
                    self.process.terminate()
                    self.process.wait(timeout=0.1)
                except Exception:
                    pass
            self.process = subprocess.Popen(
                ["dbus-monitor", "--system", "type='signal',interface='org.freedesktop.login1.Manager',member='PrepareForSleep'"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1
            )
            fd = self.process.stdout.fileno()
            os.set_blocking(fd, False)
        except Exception:
            self.process = None

    def check_suspend_event(self):
        if not self.process:
            self.start_monitor()
            if not self.process:
                return self.is_suspended

        if self.process.poll() is not None:
            self.start_monitor()
            if not self.process or self.process.poll() is not None:
                return self.is_suspended

        try:
            chunk = self.process.stdout.read()
            if chunk:
                self.buffer += chunk
        except (BlockingIOError, TypeError):
            pass
        except Exception:
            self.start_monitor()

        if len(self.buffer) > 4096:
            self.buffer = self.buffer[-1024:]

        match = re.search(r'PrepareForSleep.*?boolean\s+(true|false)', self.buffer, re.DOTALL)
        if match:
            val = match.group(1)
            self.is_suspended = (val == "true")
            self.buffer = self.buffer[match.end():]

        return self.is_suspended

    def cleanup(self):
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=0.2)
            except Exception:
                pass


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
        self.prev_frame = None
        self.transition_alpha = 0.12  # Fator de suavização temporal (cross-fading)

    def blend_frames(self, frame_a, frame_b, alpha):
        """Mistura suavemente dois frames de cores para transições sem saltos."""
        if not frame_a:
            return frame_b
        blended = []
        for c1, c2 in zip(frame_a, frame_b):
            r = int(c1.red + (c2.red - c1.red) * alpha)
            g = int(c1.green + (c2.green - c1.green) * alpha)
            b = int(c1.blue + (c2.blue - c1.blue) * alpha)
            blended.append(RGBColor(r, g, b))
        return blended

    def _render_comet(self, i, leader, base_color, head_color, tail_color, head_len=1.5, tail_len=4.5):
        """Renderiza um cometa com precisão de subpixel (anti-aliasing)."""
        diff = (i - leader) % self.num_leds
        if diff > self.num_leds / 2:
            diff -= self.num_leds
            
        if diff >= 0:
            # Cabeça do cometa: decaimento rápido em direção ao fundo
            if diff > head_len:
                return base_color
            factor = diff / head_len
            color = blend_color((255, 255, 255), head_color, factor) # Usa branco na ponta da cabeça
            intensity = (1.0 - factor) ** 2.0
            return blend_color(base_color, color, intensity)
        else:
            # Cauda do cometa: decaimento lento com degradê de cores
            if diff < -tail_len:
                return base_color
            factor = abs(diff) / tail_len
            if factor < 0.5:
                sub_factor = factor / 0.5
                color = blend_color(head_color, tail_color, sub_factor)
            else:
                sub_factor = (factor - 0.5) / 0.5
                color = blend_color(tail_color, COLOR_CYAN, sub_factor)
            intensity = (1.0 - factor) ** 1.5
            return blend_color(base_color, color, intensity)

    def _render_star(self, i, leader, base_color, star_color, width=2.0):
        """Renderiza uma estrela simétrica com suavização de subpixel."""
        diff = (i - leader) % self.num_leds
        if diff > self.num_leds / 2:
            diff -= self.num_leds
            
        dist = abs(diff)
        if dist > width:
            return base_color
        intensity = (1.0 - dist / width) ** 2.0
        return blend_color(base_color, star_color, intensity)

    def render_power_save(self, tick, ai_active, current_position, telemetry):
        # Ocioso Power Save: Respiração sutil em Ciano (0-15%)
        time_sec = tick * 0.02
        breathe = (math.sin(time_sec * 0.5) + 1.0) / 2.0
        
        base_color = COLOR_CYAN
        dim_factor = 0.05 + (0.10 * breathe) # 5% a 15% brilho
        
        frame = []
        for i in range(self.num_leds):
            r, g, b = [int(c * dim_factor) for c in base_color]
            bg_color = (r, g, b)
            
            if ai_active:
                # Fantasma verde suave com anti-aliasing
                led_color = self._render_star(
                    i=i,
                    leader=current_position % self.num_leds,
                    base_color=bg_color,
                    star_color=COLOR_GREEN,
                    width=2.0
                )
                r, g, b = [int(x * 0.3) for x in led_color]
            
            frame.append(RGBColor(r, g, b))
        return frame

    def render_balanced(self, tick, ai_active, current_position, telemetry):
        # 1. Temperatura afeta a paleta base (Ciano e Verde) de forma contínua (55°C a 75°C)
        t_factor = max(0.0, min(1.0, (telemetry.temp - 55.0) / 20.0))
        
        # As cores originais se deslocam suavemente para tons mais quentes (Laranja/Vermelho)
        c1 = blend_color(COLOR_CYAN, COLOR_ORANGE, t_factor * 0.7)
        c2 = blend_color(COLOR_GREEN, COLOR_RED, t_factor * 0.7)
        palette_colors = [c1, c2, c1]
        
        # 2. Onda harmônica de fundo (plasma de senos orgânico)
        time_sec = tick * 0.02
        w1 = math.sin(time_sec * 0.4) * 3.5
        w2 = math.sin(time_sec * 1.1 + 1.2) * 1.5
        wave_offset = w1 + w2
        
        smooth_pattern = create_smooth_palette(palette_colors, self.num_leds)
        
        frame = []
        for i in range(self.num_leds):
            # Posicionamento circular fluido usando a onda
            pos = (i + wave_offset) % self.num_leds
            idx1 = int(pos) % self.num_leds
            idx2 = (idx1 + 1) % self.num_leds
            factor = pos - int(pos)
            
            c = blend_color(smooth_pattern[idx1], smooth_pattern[idx2], factor)
            # Brilho de fundo com respiração sutil
            breathe = (math.sin(time_sec * 0.8) + 1.0) / 2.0
            bg_brightness = 0.20 + (0.30 * breathe)
            r, g, b = [int(x * bg_brightness) for x in c]
            bg_color = (r, g, b)
            
            if ai_active:
                # Cometa Yellow/Orange da paleta original com anti-aliasing
                led_color = self._render_comet(
                    i=i,
                    leader=current_position % self.num_leds,
                    base_color=bg_color,
                    head_color=COLOR_YELLOW,
                    tail_color=COLOR_ORANGE,
                    head_len=1.5,
                    tail_len=5.0
                )
            else:
                # Estrela de repouso Yellow da paleta original
                idle_leader = (tick / 15.0) % self.num_leds
                led_color = self._render_star(
                    i=i,
                    leader=idle_leader,
                    base_color=bg_color,
                    star_color=COLOR_YELLOW,
                    width=2.5
                )
            frame.append(RGBColor(*led_color))
        return frame

    def render_max_perf(self, tick, ai_active, current_position, telemetry):
        # Base Alto Desempenho: Paleta ativa original (Ciano, Verde, Laranja)
        # Shift contínuo com base na temperatura da CPU (55°C a 80°C)
        t_factor = max(0.0, min(1.0, (telemetry.temp - 55.0) / 25.0))
        
        c1 = blend_color(COLOR_CYAN, COLOR_RED, t_factor * 0.6)
        c2 = blend_color(COLOR_GREEN, COLOR_ORANGE, t_factor * 0.6)
        c3 = blend_color(COLOR_ORANGE, COLOR_RED, t_factor * 0.8)
        palette_colors = [c1, c2, c3]
        
        # Onda de deslocamento rápida
        time_sec = tick * 0.02
        w1 = math.sin(time_sec * 1.5) * 2.0
        wave_offset = (tick / 4.0) + w1
        
        virtual_leds = int(self.num_leds * 1.5)
        smooth_pattern = create_smooth_palette(palette_colors, virtual_leds)
        
        frame = []
        for i in range(self.num_leds):
            pos = (i + wave_offset) % virtual_leds
            idx1 = int(pos) % virtual_leds
            idx2 = (idx1 + 1) % virtual_leds
            factor = pos - int(pos)
            
            c = smooth_pattern[(idx1) % virtual_leds]
            c_next = smooth_pattern[(idx2) % virtual_leds]
            c_blended = blend_color(c, c_next, factor)
            brightness = 0.80 # Brilho padrão alto (80%)
            r, g, b = [int(x * brightness) for x in c_blended]
            bg_color = (r, g, b)
            
            if ai_active:
                # Cometa Yellow/Orange agressivo
                led_color = self._render_comet(
                    i=i,
                    leader=current_position % self.num_leds,
                    base_color=bg_color,
                    head_color=COLOR_YELLOW,
                    tail_color=blend_color(COLOR_ORANGE, COLOR_RED, t_factor),
                    head_len=1.2,
                    tail_len=6.0
                )
                frame.append(RGBColor(*led_color))
            else:
                frame.append(RGBColor(r, g, b))
        return frame

    def render_suspend(self):
        # Apenas 1 LED aceso bem suave (LED 0)
        frame = [RGBColor(0, 0, 0)] * self.num_leds
        frame[0] = RGBColor(*COLOR_SLEEP)
        return frame

    def render_locked(self, tick):
        # Onda espacial rotacionando suavemente (Neon Noir Aurora - Azul Puro e Magenta Puro)
        time_sec = tick * 0.02
        wave_offset = time_sec * 0.5  # Movimento lento
        frame = []
        for i in range(self.num_leds):
            # Posicionamento senoidal espacial
            factor = (math.sin((i / self.num_leds) * 2 * math.pi + wave_offset) + 1.0) / 2.0
            color = blend_color(COLOR_PURE_BLUE, COLOR_PURE_MAGENTA, factor)
            # Brilho de 15%
            r, g, b = [int(c * 0.15) for c in color]
            frame.append(RGBColor(r, g, b))
        return frame

    def apply_thermal_stress(self, frame, temp):
        # Núcleo de Fusão Térmico - Red flicker overrides
        if temp >= 70.0:
            stressed_frame = []
            for color in frame:
                r = int(min(255, color.red * 0.5 + COLOR_RED[0] * 0.8))
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
        # 0. Modo suspensão
        if getattr(telemetry, 'is_suspended', False):
            target_frame = self.render_suspend()
        # 1. Tela bloqueada
        elif telemetry.is_locked or os.path.exists("/tmp/use_magenta"):
            target_frame = self.render_locked(tick)
        else:
            # 2. Renderização do modo atual
            if telemetry.power_mode == "POWER_SAVE":
                target_frame = self.render_power_save(tick, telemetry.ai_active, current_position, telemetry)
            elif telemetry.power_mode == "MAX_PERF":
                target_frame = self.render_max_perf(tick, telemetry.ai_active, current_position, telemetry)
            else:
                target_frame = self.render_balanced(tick, telemetry.ai_active, current_position, telemetry)
                
            # 3. Aplicação do estresse térmico
            target_frame = self.apply_thermal_stress(target_frame, telemetry.temp)
            
        # 4. Mistura com o frame anterior (temporal cross-fading)
        if self.prev_frame is None:
            self.prev_frame = target_frame
        else:
            self.prev_frame = self.blend_frames(self.prev_frame, target_frame, self.transition_alpha)
            
        return self.prev_frame


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
    suspend_detector = SuspendDetector()

    try:
        telemetry.start()
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
                # Monitora suspensão a cada ciclo (50Hz) para evitar freeze sem desligar LEDs
                telemetry.is_suspended = suspend_detector.check_suspend_event()

                # Log da Telemetria a cada 50 ticks (1 segundo a 50Hz)
                if tick % 50 == 0:
                    if verbose:
                        print(f"Susp: {telemetry.is_suspended} | Temp: {telemetry.temp:.1f}°C | Modo: {telemetry.power_mode} | IA: {telemetry.ai_active} | Bloq: {telemetry.is_locked}")

                # Define velocidade do Cometa baseado no status do sistema
                if telemetry.is_suspended or telemetry.is_locked or os.path.exists("/tmp/use_magenta"):
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
    finally:
        telemetry.stop()
        suspend_detector.cleanup()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    main(verbose=args.verbose)
