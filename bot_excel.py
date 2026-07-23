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
        print("[ERROR] Faltan credenciales de Telegram.")
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
            print("[TELEGRAM] Mensaje enviado correctamente.")
        else:
            print(f"[ERROR TELEGRAM] {r.status_code}: {r.text}")
    except Exception as e:
        print(f"[EXCEPCIÓN TELEGRAM] {e}")

def analizar_excel():
    archivos = glob.glob("*.xlsx")
    if not archivos:
        print("[ERROR] No se encontró ningún archivo .xlsx.")
        return

    excel_path = archivos[0]
    print(f"[INFO] Leyendo archivo: {excel_path}")

    try:
        df_partidos = pd.read_excel(excel_path, sheet_name="Partidos")
    except Exception as e:
        print(f"[ERROR EXCEL] {e}")
        return

    # Limpieza básica
    df_partidos = df_partidos.dropna(subset=["Local", "Visitante"])

    # Partidos jugados vs partidos pendientes
    partidos_jugados = df_partidos.dropna(subset=["Goles L", "Goles V"]).copy()
    partidos_pendientes = df_partidos[df_partidos["Goles L"].isna()].copy()

    if partidos_pendientes.empty:
        enviar_telegram("ℹ️ *[REPORTE EXCEL]*\nNo hay partidos pendientes cargados en la hoja de Excel.")
        return

    alertas_generadas = 0

    for _, fila in partidos_pendientes.iterrows():
        local = str(fila["Local"]).strip()
        visita = str(fila["Visitante"]).strip()
        jornada = fila.get("Jornada", "N/A")

        # Tomar hasta los últimos 3 partidos jugados por cada equipo
        hist_local = partidos_jugados[(partidos_jugados["Local"] == local) | (partidos_jugados["Visitante"] == local)].tail(3)
        hist_visita = partidos_jugados[(partidos_jugados["Local"] == visita) | (partidos_jugados["Visitante"] == visita)].tail(3)

        # Ajuste clave: exige al menos 1 partido previo registrado
        if len(hist_local) < 1 or len(hist_visita) < 1:
            continue

        # Promedio de goles anotados a favor
        goles_local_favor = [p["Goles L"] if p["Local"] == local else p["Goles V"] for _, p in hist_local.iterrows()]
        goles_visita_favor = [p["Goles L"] if p["Local"] == visita else p["Goles V"] for _, p in hist_visita.iterrows()]

        prom_goles_local = sum(goles_local_favor) / len(goles_local_favor)
        prom_goles_visita = sum(goles_visita_favor) / len(goles_visita_favor)

        expectativa_goles = prom_goles_local + prom_goles_visita
        
        # Algoritmo de estimación de probabilidad Over 1.5
        prob_over_15 = min(99.0, max(50.0, (expectativa_goles / 2.0) * 80.0))

        if prob_over_15 >= PROBABILIDAD_MINIMA:
            alertas_generadas += 1
            mensaje = (
                f"🎯 *[ALERTA VALOR VALUE BETTOR]*\n"
                f"🏆 *Jornada:* {int(jornada) if pd.notna(jornada) else 'N/A'}\n"
                f"🏟️ *Partido:* {local} vs. {visita}\n\n"
                f"📊 *Métricas Clave (Basado en historial):*\n"
                f"• Prom. Goles {local}: {prom_goles_local:.2f}\n"
                f"• Prom. Goles {visita}: {prom_goles_visita:.2f}\n"
                f"• Expectativa Conjunta: {expectativa_goles:.2f} goles\n\n"
                f"🔥 *Probabilidad Calculada:* {prob_over_15:.1f}%\n"
                f"🎯 *Mercado Sugerido:* Over 1.5 Goles / DNB\n"
                f"💰 *Piso Betano Peru:* {CUOTA_PISO_BETANO:.2f}+\n"
                f"🛡️ *Nivel de Confianza:* Alto (Modelo Cuantitativo)"
            )
            enviar_telegram(mensaje)

    if alertas_generadas == 0:
        enviar_telegram("📊 *[REPORTE DE JORNADA]*\nSe evaluaron los partidos pendientes, pero ninguno alcanzó el umbral del 85% de probabilidad.")

if __name__ == "__main__":
    analizar_excel()
