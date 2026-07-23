import os
import glob
import pandas as pd
import requests

# ==========================================
# CONFIGURACIÓN Y CREDENCIALES
# ==========================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

CUOTA_PISO_BETANO = 1.70
PROBABILIDAD_MINIMA = 85.0

def enviar_telegram(mensaje):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[ERROR] Faltan credenciales de Telegram en las variables de entorno.")
        return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensaje,
        "parse_mode": "Markdown"
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code == 200:
            print("[TELEGRAM] Alerta enviada con éxito.")
        else:
            print(f"[ERROR TELEGRAM] Código {r.status_code}: {r.text}")
    except Exception as e:
        print(f"[EXCEPCIÓN TELEGRAM] {e}")

def analizar_excel():
    # Buscar cualquier archivo .xlsx en el repositorio
    archivos = glob.glob("*.xlsx")
    if not archivos:
        print("[ERROR] No se encontró ningún archivo .xlsx en el repositorio.")
        return

    excel_path = archivos[0]
    print(f"[INFO] Procesando archivo: {excel_path}")

    try:
        # Cargar la pestaña de Partidos
        df_partidos = pd.read_excel(excel_path, sheet_name="Partidos")
    except Exception as e:
        print(f"[ERROR EXCEL] No se pudo leer la hoja 'Partidos': {e}")
        return

    # Limpiar filas vacías esenciales
    df_partidos = df_partidos.dropna(subset=["Local", "Visitante"])

    # Filtrar partidos jugados (con resultado) para calcular estadísticas históricas
    partidos_jugados = df_partidos.dropna(subset=["Goles L", "Goles V"]).copy()

    # Identificar partidos pendientes o de la jornada actual (sin goles registrados aún)
    partidos_pendientes = df_partidos[df_partidos["Goles L"].isna()].copy()

    if partidos_pendientes.empty:
        print("[INFO] No hay partidos pendientes para analizar en este Excel.")
        enviar_telegram("ℹ️ *[REPORTE EXCEL]*\nNo hay partidos pendientes cargados en la hoja de Excel.")
        return

    alertas_generadas = 0

    # Iterar sobre los partidos de la próxima jornada
    for _, fila in partidos_pendientes.iterrows():
        local = str(fila["Local"]).strip()
        visita = str(fila["Visitante"]).strip()
        jornada = fila.get("Jornada", "N/A")

        # Obtener los últimos 3 partidos de cada equipo
        hist_local = partidos_jugados[(partidos_jugados["Local"] == local) | (partidos_jugados["Visitante"] == local)].tail(3)
        hist_visita = partidos_jugados[(partidos_jugados["Local"] == visita) | (partidos_jugados["Visitante"] == visita)].tail(3)

        if len(hist_local) < 2 or len(hist_visita) < 2:
            continue  # Se requieren al menos 2 partidos previos cargados para calcular racha

        # Cálculo de métricas promedio (Goles + xG)
        goles_local_favor = []
        for _, p in hist_local.iterrows():
            goles_local_favor.append(p["Goles L"] if p["Local"] == local else p["Goles V"])

        goles_visita_favor = []
        for _, p in hist_visita.iterrows():
            goles_visita_favor.append(p["Goles L"] if p["Local"] == visita else p["Goles V"])

        prom_goles_local = sum(goles_local_favor) / len(goles_local_favor)
        prom_goles_visita = sum(goles_visita_favor) / len(goles_visita_favor)

        # Estimación de probabilidad basada en tendencia anotadora
        expectativa_goles = prom_goles_local + prom_goles_visita
        
        # Algoritmo de probabilidad para Over 1.5 Goles
        prob_over_15 = min(99.0, max(50.0, (expectativa_goles / 2.0) * 80.0))

        # Si supera el umbral de valor
        if prob_over_15 >= PROBABILIDAD_MINIMA:
            alertas_generadas += 1
            mensaje = (
                f"🎯 *[ALERTA VALOR VALUE BETTOR]*\n"
                f"🏆 *Jornada:* {jornada}\n"
                f"🏟️ *Partido:* {local} vs. {visita}\n\n"
                f"📊 *Métricas Clave (Últimos 3 partidos):*\n"
                f"• Prom. Goles {local}: {prom_goles_local:.2f}\n"
                f"• Prom. Goles {visita}: {prom_goles_visita:.2f}\n"
                f"• Expectativa Conjunta: {expectativa_goles:.2f} goles\n\n"
                f"🔥 *Probabilidad Calculada:* {prob_over_15:.1f}%\n"
                f"🎯 *Mercado Recomendado:* Over 1.5 Goles / DNB\n"
                f"💰 *Piso Betano Peru:* {CUOTA_PISO_BETANO:.2f}+\n"
                f"🛡️ *Nivel de Confianza:* Alto (Basado en datos de Excel)"
            )
            enviar_telegram(mensaje)

    if alertas_generadas == 0:
        enviar_telegram("📊 *[REPORTE DE JORNADA]*\nSe procesó el Excel correctamente, pero ningún partido pendiente superó la valla estricta del 85% de probabilidad.")

if __name__ == "__main__":
    analizar_excel()
