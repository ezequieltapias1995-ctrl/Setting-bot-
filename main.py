import os
import requests
import time
from datetime import datetime
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler

# =============================================================================
# DETECCIÓN DE ENTORNO: ¿Estamos en Render (con variables de entorno) o en local?
# =============================================================================
ENV_VARS_EXIST = all(k in os.environ for k in ['TELEGRAM_TOKEN', 'TELEGRAM_CHAT_ID', 'ODDS_API_KEY'])

if ENV_VARS_EXIST:
    # Modo nube (Render)
    TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
    TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')
    ODDS_API_KEY = os.environ.get('ODDS_API_KEY')
    UMBRAL_EV = float(os.environ.get('UMBRAL_EV', 5.0))
    print("✅ Usando variables de entorno (modo nube)")
else:
    # Modo local (Pydroid) - pedimos datos al usuario
    print("🔧 Modo local: necesito que introduzcas tus claves.")
    TELEGRAM_TOKEN = input("Introduce tu TELEGRAM_TOKEN: ").strip()
    TELEGRAM_CHAT_ID = input("Introduce tu TELEGRAM_CHAT_ID: ").strip()
    ODDS_API_KEY = input("Introduce tu ODDS_API_KEY: ").strip()
    try:
        UMBRAL_EV = float(input("Umbral de EV % (Enter para 5%): ") or "5.0")
    except:
        UMBRAL_EV = 5.0
    print("✅ Datos guardados para esta sesión (no se almacenan).")

# Verificar que no estén vacíos
if not all([TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, ODDS_API_KEY]):
    raise ValueError("❌ Faltan datos. No se puede continuar.")

# =============================================================================
# SERVIDOR DE SALUD (obligatorio para Render, no estorba en local)
# =============================================================================
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'OK')

def run_health_server():
    port = int(os.environ.get('PORT', 8000))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.serve_forever()

Thread(target=run_health_server, daemon=True).start()

# =============================================================================
# FUNCIONES AUXILIARES
# =============================================================================
def enviar_mensaje_telegram(mensaje):
    """Envía un mensaje a tu Telegram"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': mensaje,
        'parse_mode': 'HTML'
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        print("✅ Mensaje enviado a Telegram")
    except Exception as e:
        print(f"❌ Error al enviar mensaje a Telegram: {e}")

def obtener_cuotas_1x2(partido):
    """Extrae cuotas del mercado 1X2 para todas las casas"""
    cuotas_local = []
    cuotas_empate = []
    cuotas_visitante = []
    
    for bookmaker in partido['bookmakers']:
        for market in bookmaker['markets']:
            if market['key'] == 'h2h':
                for outcome in market['outcomes']:
                    if outcome['name'] == partido['home_team']:
                        cuotas_local.append(outcome['price'])
                    elif outcome['name'] == partido['away_team']:
                        cuotas_visitante.append(outcome['price'])
                    else:
                        cuotas_empate.append(outcome['price'])
                break
    
    return {
        'local': cuotas_local,
        'empate': cuotas_empate,
        'visitante': cuotas_visitante
    }

def obtener_cuotas_goles(partido, lineas=None):
    """Extrae cuotas de Over/Under (totals) para las líneas especificadas"""
    if lineas is None:
        lineas = [2.5, 3.5]
    
    resultados = {}
    for bookmaker in partido['bookmakers']:
        for market in bookmaker['markets']:
            if market['key'] == 'totals':  # El mercado se llama 'totals', no 'over_under'
                for outcome in market['outcomes']:
                    partes = outcome['name'].split()
                    if len(partes) == 2:
                        tipo, linea_str = partes
                        try:
                            linea = float(linea_str)
                            if linea in lineas:
                                clave = f"{tipo}_{linea}".lower()
                                if clave not in resultados:
                                    resultados[clave] = []
                                resultados[clave].append(outcome['price'])
                        except ValueError:
                            continue
    return resultados

def calcular_probabilidad_real(cuotas_lista):
    """Calcula probabilidad real como promedio de probabilidades implícitas"""
    if len(cuotas_lista) < 2:
        return None
    prob_total = sum(1/c for c in cuotas_lista)
    return prob_total / len(cuotas_lista)

def evaluar_value_bets(partidos):
    """Analiza todos los partidos y genera alertas para 1X2 y goles"""
    alertas = []
    
    for partido in partidos:
        home = partido['home_team']
        away = partido['away_team']
        start_time = datetime.fromisoformat(partido['commence_time'].replace('Z', '+00:00'))
        hora = start_time.strftime('%d/%m %H:%M')
        
        # ----- MERCADO 1X2 -----
        cuotas_1x2 = obtener_cuotas_1x2(partido)
        for tipo, cuotas in cuotas_1x2.items():
            if len(cuotas) < 2:
                continue
            mejor_cuota = max(cuotas)
            prob_real = calcular_probabilidad_real(cuotas)
            if prob_real is None:
                continue
            ev = (prob_real * mejor_cuota - 1) * 100  # en %
            if ev >= UMBRAL_EV:
                # Buscar casa que ofrece la mejor cuota
                casa_mejor = None
                for bookmaker in partido['bookmakers']:
                    for market in bookmaker['markets']:
                        if market['key'] == 'h2h':
                            for outcome in market['outcomes']:
                                if ((tipo == 'local' and outcome['name'] == home) or
                                    (tipo == 'empate' and outcome['name'] not in [home, away]) or
                                    (tipo == 'visitante' and outcome['name'] == away)):
                                    if outcome['price'] == mejor_cuota:
                                        casa_mejor = bookmaker['title']
                                        break
                            break
                alerta = (
                    f"⚽ <b>{home} vs {away}</b>\n"
                    f"📅 {hora}\n"
                    f"🎯 <b>1X2 - {tipo.upper()}</b>\n"
                    f"💰 Mejor cuota: <b>{mejor_cuota:.2f}</b> en {casa_mejor}\n"
                    f"📊 Prob. real: <b>{prob_real*100:.1f}%</b>\n"
                    f"💎 EV: <b>+{ev:.1f}%</b>"
                )
                alertas.append(alerta)
        
        # ----- MERCADO DE GOLES (totals) -----
        cuotas_goles = obtener_cuotas_goles(partido, lineas=[2.5, 3.5])
        for mercado, cuotas in cuotas_goles.items():
            if len(cuotas) < 2:
                continue
            mejor_cuota = max(cuotas)
            prob_real = calcular_probabilidad_real(cuotas)
            if prob_real is None:
                continue
            ev = (prob_real * mejor_cuota - 1) * 100
            if ev >= UMBRAL_EV:
                casa_mejor = None
                tipo_apuesta = mercado.replace('_', ' ').upper()  # ej: "OVER 2.5"
                for bookmaker in partido['bookmakers']:
                    for market in bookmaker['markets']:
                        if market['key'] == 'totals':
                            for outcome in market['outcomes']:
                                if outcome['name'].lower().replace(' ', '_') == mercado and outcome['price'] == mejor_cuota:
                                    casa_mejor = bookmaker['title']
                                    break
                            break
                alerta = (
                    f"⚽ <b>{home} vs {away}</b>\n"
                    f"📅 {hora}\n"
                    f"🎯 <b>GOLES - {tipo_apuesta}</b>\n"
                    f"💰 Mejor cuota: <b>{mejor_cuota:.2f}</b> en {casa_mejor}\n"
                    f"📊 Prob. real: <b>{prob_real*100:.1f}%</b>\n"
                    f"💎 EV: <b>+{ev:.1f}%</b>"
                )
                alertas.append(alerta)
    
    return alertas

def main():
    print(f"\n--- {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---")
    print("🔍 Buscando value bets...")
    
    # Parámetros de la API
    deporte = "soccer"
    region = "eu"
    mercados = "h2h,totals"  # IMPORTANTE: 'totals' es el mercado de goles
    
    url = f"https://api.the-odds-api.com/v4/sports/{deporte}/odds"
    params = {
        'apiKey': ODDS_API_KEY,
        'regions': region,
        'markets': mercados,
        'oddsFormat': 'decimal'
    }
    
    try:
        response = requests.get(url, params=params, timeout=15)
        if response.status_code != 200:
            print(f"❌ Error {response.status_code} de la API:")
            print(response.text)  # Muestra el mensaje de error detallado
            response.raise_for_status()
        partidos = response.json()
    except Exception as e:
        print(f"❌ Error al obtener datos de la API: {e}")
        return
    
    if not partidos:
        print("No se recibieron partidos. Revisa la API key o los parámetros.")
        return
    
    print(f"Partidos recibidos: {len(partidos)}")
    
    alertas = evaluar_value_bets(partidos)
    
    if alertas:
        for alerta in alertas:
            enviar_mensaje_telegram(alerta)
            time.sleep(1)
        print(f"✅ Enviadas {len(alertas)} alertas")
    else:
        print("😴 No se encontraron value bets en esta ejecución.")

# =============================================================================
# BUCLE PRINCIPAL
# =============================================================================
if __name__ == "__main__":
    print("🤖 Bot de value bets iniciado correctamente")
    print(f"🔧 Umbral EV: {UMBRAL_EV}%")
    print("⏳ Comprobando cada 10 minutos... (Presiona Ctrl+C para detener)")
    try:
        while True:
            main()
            time.sleep(600)  # 10 minutos
    except KeyboardInterrupt:
        print("\n👋 Bot detenido por el usuario.")
