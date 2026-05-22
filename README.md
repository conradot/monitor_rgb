Aqui está uma estrutura de README profissional e organizada para o seu projeto de automação de iluminação RGB.

---

# RGB Dynamic System: Watson Framework

Este projeto implementa um sistema de controle de iluminação RGB dinâmico, inteligente e consciente do estado do sistema, projetado para integrar hardware de ventoinhas (ARGB) e periféricos (Dell G15) a estados de processamento de IA (Ollama) e métricas térmicas.

## 🎯 Objetivo

Transformar a iluminação do setup em uma **interface passiva de telemetria**, onde o movimento, a cor e a intensidade da luz comuniquem o nível de esforço do hardware e a atividade de processamento sem a necessidade de olhar para a tela.

---

## ⚙️ Características dos Cenários

O sistema opera em 5 estados distintos, priorizando a legibilidade e o feedback visual:

### 1. Estado Ocioso (Idle / Stand-by)

* **O Desejo:** Evitar que o sistema pareça "morto", mantendo uma identidade visual constante, mas sutil.
* **Comportamento:** A ventoinha utiliza um efeito de **Estrela Cadente Watson**. Uma luz intensa circula as pás sobre uma base de luz fixa. No modo *Alto Desempenho*, o brilho é elevado e todos os LEDs são ativados, criando presença visual constante.

### 2. Processamento de IA (Ollama/LLM Ativo)

* **O Desejo:** Indicar que a máquina está trabalhando em carga de inferência de IA.
* **Comportamento:** O sistema abandona o padrão estático e inicia uma **rotação dinâmica**. A velocidade de rotação escala de forma exponencial conforme a temperatura da CPU sobe, tornando-se um "cometa" veloz em situações de estresse.

### 3. Estresse Térmico (Núcleo de Fusão)

* **O Desejo:** Alertar o usuário visualmente sobre temperaturas críticas de forma intuitiva.
* **Comportamento:** Ao atingir **80°C**, o sistema injeta Vermelho Crítico na paleta e aplica um efeito de **micro-flicker caótico (centelha)**. A luz parece "crepitar" como plasma, refletindo a instabilidade térmica em alta performance.

### 4. Economia de Energia (Power Save)

* **O Desejo:** Mínimo consumo e poluição visual, mantendo apenas um indicador discreto.
* **Comportamento:** Os LEDs operam com brilho reduzido (5-15%), exibindo uma animação lenta e fantasmagórica em Ciano, sugerindo que o sistema está em modo de repouso profundo.

### 5. Segurança (Tela Bloqueada)

* **O Desejo:** Indicar ausência do usuário com uma iluminação ambiente sofisticada.
* **Comportamento:** O movimento rotacional para completamente. O sistema alterna suavemente entre Azul Puro e Magenta, agindo como uma luz ambiente estática (*Neon Noir Aurora*).

---

## 🛠️ Especificações Técnicas

* **Taxa de Atualização:** 50 Hz (estável via time.sleep(0.02)), garantindo transições fluidas sem *flicker* perceptível.
* **Hardware Integrado:**
* Ventoinhas **ASUS TUF TF120** (16 LEDs com difusão dupla).
* Teclado **Dell G15** (4 zonas lógicas de controle).


* **Tecnologia:**
* Python com biblioteca OpenRGB.
* Integração via systemd para persistência em background.
* Mapeamento térmico via /sys/class/hwmon.
* Detecção de processos via pgrep e requests (API Ollama).



---

## 🚀 Como Executar

1. **Instalação:** Certifique-se de que o servidor OpenRGB está rodando em 127.0.0.1:6742.
2. **Serviço:** Os scripts são gerenciados via systemd para execução automática:
```bash
systemctl --user restart monitor-rgb.service
systemctl --user restart monitor-teclado.service


```



```
3. **Logs:** Utilize a flag -v ao executar manualmente para monitorar a telemetria em tempo real:
   ```bash
   python3 monitor_rgb.py -v
   

```

---

*Projeto desenvolvido para otimização de feedback visual em sistemas de alta performance.*