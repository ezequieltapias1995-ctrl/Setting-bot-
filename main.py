import requests
import time
from datetime import datetime

# ================= CONFIGURACIÓN =================
TELEGRAM_TOKEN = "8652195121:AAHtJxNAvm50fEeXpK14sVrzieLQXEhPevw"
TELEGRAM_CHAT_ID = "6094136485"
ODDS_API_KEY = "d8ef2af98eddc2b3a3e878944ab4894d"

# Parámetros
DEPORTE = "soccer"
REGION = "eu"
MERCADO = "h2h"
UMBRAL_EV = 3.0  # Solo alertas con EV superior al 3%
# =================================================

def enviar_mensaje_telegram(mensaje):
    """Envía mensaje a Telegram"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    datos = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': mensaje,
        'parse_mode': 'HTML'
    }
    try:
        requests.post(url, json=datos)
    except Exception as e:
        print(f"Error: {e}")

def calcular_probabilidad_implicita(cuota):
    """Convierte cuota en probabilidad (fórmula básica)"""
    return 1 / cuota

def calcular_probabilidad_real(partido):
    """
    Calcula probabilidad "real" usando el promedio del mercado
    (método simple pero efectivo para value bets)
    """
    cuotas_local = []
    
    for bookmaker in partido['bookmakers']:
        for mercado in bookmaker['markets']:
            if mercado['key'] == 'h2h':
                for outcome in mercado['outcomes']:
                    if outcome['name'] == partido['home_team']:
                        cuotas_local.append(outcome['price'])
                        break
    
    if len(cuotas_local) < 2:
        return None
    
    # La probabilidad real es el promedio de las probabilidades implícitas
    prob_promedio = sum([1/c for c in cuotas_local]) / len(cuotas_local)
    return prob_promedio

def encontrar_value_bets(partidos):
    """Analiza partidos y calcula EV para cada uno"""
    alertas = []
    
    for partido in partidos:
        equipo_local = partido['home_team']
        equipo_visitante = partido['away_team']
        comienzo = datetime.fromisoformat(partido['commence_time'].replace('Z', '+00:00'))
        hora = comienzo.strftime('%d/%m %H:%M')
        
        # Buscar la mejor cuota local
        mejor_cuota = 0
        casa_mejor = ""
        
        for bookmaker in partido['bookmakers']:
            for mercado in bookmaker['markets']:
                if mercado['key'] == 'h2h':
                    for outcome in mercado['outcomes']:
                        if outcome['name'] == equipo_local:
                            if outcome['price'] > mejor_cuota:
                                mejor_cuota = outcome['price']
                                casa_mejor = bookmaker['title']
        
        # Calcular probabilidad real y EV
        prob_real = calcular_probabilidad_real(partido)
        if prob_real and mejor_cuota > 0:
            ev = (prob_real * mejor_cuota - 1) * 100  # En porcentaje
            
            # Solo enviar si supera el umbral
            if ev >= UMBRAL_EV:
                alerta = f"""
⚠️ <b>VALUE BET DETECTADA</b>
⚽ {equipo_local} vs {equipo_visitante}
📅 {hora}
💰 Mejor cuota: <b>{mejor_cuota:.2f}</b> en {casa_mejor}
📊 Prob. real: <b>{prob_real*100:.1f}%</b>
💎 EV: <b>+{ev:.1f}%</b>
"""
                alertas.append(alerta)
                print(f"✅ Value bet: {equipo_local} | EV: +{ev:.1f}%")
    
    return alertas

def main():
    print("🔍 Buscando value bets...")
    
    # Obtener partidos
    url = f"https://api.the-odds-api.com/v4/sports/{DEPORTE}/odds"
    params = {
        'apiKey': ODDS_API_KEY,
        'regions': REGION,
        'markets': MERCADO,
        'oddsFormat': 'decimal'
    }
    
    try:
        respuesta = requests.get(url, params=params)
        partidos = respuesta.json()
    except Exception as e:
        print(f"❌ Error API: {e}")
        return
    
    # Analizar y enviar alertas
    alertas = encontrar_value_bets(partidos)
    
    if alertas:
        for alerta in alertas:
            enviar_mensaje_telegram(alerta)
            time.sleep(1)
        print(f"✅ Enviadas {len(alertas)} alertas")
    else:
        print("😴 No hay value bets en este momento")

if __name__ == "__main__":
    # Bucle infinito para ejecutar cada 10 minutos
    while True:
        main()
        print("⏳ Esperando 10 minutos...")
        time.sleep(600)  # 600 segundos = 10 minutos
