import os
import glob
import pandas as pd
import requests

# ==========================================
# CONFIGURACIÓN Y PARÁMETROS DE FILTRADO
# ==========================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

CUOTA_PISO_BETANO = 1.70
PROBABILIDAD_MINIMA_FILTRO = 88.0  # Valla estricta para seleccionar solo lo mejor
MAX_ALERTAS_POR_JORNADA = 3        # Máximo de señales a enviar por jornada (Calidad sobre cantidad)

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

def calcular_promedio(lista):
    validos = [v for v in lista if pd.notna(v)]
    return sum(validos) / len(validos) if validos else 0.0

def analizar_excel():
    archivos = glob.glob("*.xlsx")
    if not archivos:
        print("[ERROR] No se encontró ningún archivo .xlsx.")
        return

    excel_path = archivos[0]
    print(f"[INFO] Leyendo archivo: {excel_path}")

    try:
        xls = pd.ExcelFile(excel_path)
        df_partidos = pd.read_excel(xls, sheet_name="Partidos")
        
        df_jugadores = pd.DataFrame()
        if "Estadísticas Jugadores" in xls.sheet_names:
            df_jugadores = pd.read_excel(xls, sheet_name="Estadísticas Jugadores")
    except Exception as e:
        print(f"[ERROR EXCEL] Error al leer hojas: {e}")
        return

    # Limpieza de partidos
    df_partidos = df_partidos.dropna(subset=["Local", "Visitante"])
    partidos_jugados = df_partidos.dropna(subset=["Goles L", "Goles V"]).copy()
    partidos_pendientes = df_partidos[df_partidos["Goles L"].isna()].copy()

    if partidos_pendientes.empty:
        enviar_telegram("ℹ️ *[REPORTE EXCEL]*\nNo hay partidos pendientes cargados en la hoja de Excel.")
        return

    todas_las_propuestas = []

    for _, fila in partidos_pendientes.iterrows():
        local = str(fila["Local"]).strip()
        visita = str(fila["Visitante"]).strip()
        jornada = fila.get("Jornada", "N/A")

        # Historial de los últimos 3 partidos
        hist_local = partidos_jugados[(partidos_jugados["Local"] == local) | (partidos_jugados["Visitante"] == local)].tail(3)
        hist_visita = partidos_jugados[(partidos_jugados["Local"] == visita) | (partidos_jugados["Visitante"] == visita)].tail(3)

        if len(hist_local) < 1 or len(hist_visita) < 1:
            continue

        # Promedios cuantitativos
        goles_L = [p["Goles L"] if p["Local"] == local else p["Goles V"] for _, p in hist_local.iterrows()]
        goles_V = [p["Goles L"] if p["Local"] == visita else p["Goles V"] for _, p in hist_visita.iterrows()]
        
        remates_L = [p.get("Remates Arco L", 0) if p["Local"] == local else p.get("Remates Arco V", 0) for _, p in hist_local.iterrows()]
        remates_V = [p.get("Remates Arco L", 0) if p["Local"] == visita else p.get("Remates Arco V", 0) for _, p in hist_visita.iterrows()]

        corners_L = [p.get("Corners L", 0) if p["Local"] == local else p.get("Corners V", 0) for _, p in hist_local.iterrows()]
        corners_V = [p.get("Corners L", 0) if p["Local"] == visita else p.get("Corners V", 0) for _, p in hist_visita.iterrows()]

        prom_goles_L = calcular_promedio(goles_L)
        prom_goles_V = calcular_promedio(goles_V)
        prom_remates_L = calcular_promedio(remates_L)
        prom_remates_V = calcular_promedio(remates_V)
        prom_corners_L = calcular_promedio(corners_L)
        prom_corners_V = calcular_promedio(corners_V)

        candidatos = []

        # 1. Resultado Final (1X2) - Solo en dominancia clara
        if prom_goles_L >= 2.3 and prom_goles_V <= 0.7:
            candidatos.append({
                "categoria": "Resultado Final (1X2)",
                "texto": f"Victoria de {local} (1)",
                "razon": f"{local} promedia {prom_goles_L:.1f} goles favor vs {prom_goles_V:.1f} de {visita}",
                "score": 89.5
            })

        # 2. Goles Totales
        if (prom_goles_L + prom_goles_V) >= 2.2:
            candidatos.append({
                "categoria": "Goles Totales",
                "texto": "Over 1.5 Goles Totales del Partido",
                "razon": f"Promedio acumulado de {prom_goles_L + prom_goles_V:.1f} goles por encuentro",
                "score": 90.0
            })

        # 3. Goles por Equipo
        if prom_goles_L >= 1.5:
            candidatos.append({
                "categoria": "Goles por Equipo",
                "texto": f"{local} ➔ Over 0.5 Goles (Equipo)",
                "razon": f"{local} promedia {prom_goles_L:.1f} goles anotados por partido",
                "score": 88.5
            })

        # 4. Córners Totales
        if (prom_corners_L + prom_corners_V) >= 8.5:
            candidatos.append({
                "categoria": "Córners Totales",
                "texto": "Over 7.5 Córners Totales del Partido",
                "razon": f"Promedio conjunto de {prom_corners_L + prom_corners_V:.1f} tiros de esquina",
                "score": 89.0
            })

        # 5. Córners por Equipo
        if prom_corners_L >= 4.5:
            candidatos.append({
                "categoria": "Córners por Equipo",
                "texto": f"{local} ➔ Over 3.5 Córners Totales",
                "razon": f"{local} registra {prom_corners_L:.1f} córners por partido",
                "score": 88.0
            })

        # 6. Remates al Arco por Equipo
        if prom_remates_L >= 4.5:
            candidatos.append({
                "categoria": "Remates a Puerta (Equipo)",
                "texto": f"{local} ➔ Over 3.5 Remates a Puerta",
                "razon": f"{local} promedia {prom_remates_L:.1f} tiros directos a puerta",
                "score": 88.5
            })

        # 7. Jugadores (Remates, Goles, Asistencias)
        if not df_jugadores.empty:
            jugadores_partido = df_jugadores[df_jugadores["Equipo"].isin([local, visita])]
            
            if "Remates al Arco" in jugadores_partido.columns:
                rematadores = jugadores_partido[jugadores_partido["Remates al Arco"] >= 2]
                if not rematadores.empty:
                    top_r = rematadores.sort_values(by="Remates al Arco", ascending=False).iloc[0]
                    candidatos.append({
                        "categoria": "Remates a Puerta (Jugador)",
                        "texto": f"{top_r['Jugador']} ({top_r['Equipo']}) ➔ Over 0.5 Remates a Puerta",
                        "razon": f"Acumula {int(top_r['Remates al Arco'])} tiros directos al arco en {int(top_r['Minutos'])}'",
                        "score": 91.0
                    })

        if not candidatos:
            continue

        jornada_txt = int(jornada) if pd.notna(jornada) and isinstance(jornada, (int, float)) else str(jornada)

        # Evaluar si armar BetBuilder o Pick Simple
        if len(candidatos) >= 2:
            betbuilder_picks = candidatos[:3]
            score_promedio = sum(c['score'] for c in betbuilder_picks) / len(betbuilder_picks)
            
            todas_las_propuestas.append({
                "tipo": "BETBUILDER",
                "partido": f"{local} vs. {visita}",
                "jornada": jornada_txt,
                "picks": betbuilder_picks,
                "score": score_promedio,
                "sustento": betbuilder_picks[0]["razon"]
            })
        else:
            pick = candidatos[0]
            todas_las_propuestas.append({
                "tipo": "SIMPLE",
                "partido": f"{local} vs. {visita}",
                "jornada": jornada_txt,
                "pick": pick,
                "score": pick["score"],
                "sustento": pick["razon"]
            })

    # --- FILTRADO Y SELECCIÓN DE LAS MEJORES OPCIONES DE LA JORNADA ---
    propuestas_filtradas = [p for p in todas_las_propuestas if p["score"] >= PROBABILIDAD_MINIMA_FILTRO]
    propuestas_filtradas.sort(key=lambda x: x["score"], reverse=True)

    top_selecciones = propuestas_filtradas[:MAX_ALERTAS_POR_JORNADA]

    if not top_selecciones:
        enviar_telegram("📊 *[FILTRO DE JORNADA]*\nSe analizaron todos los partidos pendientes, pero ninguno superó la valla estricta del 88% de probabilidad. No se recomiendan apuestas en esta jornada.")
        return

    for propuesta in top_selecciones:
        if propuesta["tipo"] == "BETBUILDER":
            lista_formatted = "\n".join([f"  • {item['texto']}" for item in propuesta["picks"]])
            mensaje = (
                f"🎯 *[SELECCIÓN DE ALTA PROBABILIDAD - BETBUILDER]*\n"
                f"🏆 *Jornada:* {propuesta['jornada']}\n"
                f"🏟️ *Partido:* {propuesta['partido']}\n"
                f"───────────────────────────\n"
                f"🧩 *COMBINACIÓN FILTRADA ({len(propuesta['picks'])} Pasos):*\n"
                f"{lista_formatted}\n"
                f"───────────────────────────\n"
                f"📊 *Sustento Principal:* {propuesta['sustento']}\n"
                f"🔥 *Nivel de Confianza:* {propuesta['score']:.1f}%\n"
                f"💰 *Piso de Cuota Betano:* {CUOTA_PISO_BETANO:.2f}+\n"
                f"🛡️ *Perfil:* Value Bettor Conservador-Activo"
            )
        else:
            pick = propuesta["pick"]
            mensaje = (
                f"🎯 *[SELECCIÓN DE ALTA PROBABILIDAD - PICK SIMPLE]*\n"
                f"🏆 *Jornada:* {propuesta['jornada']}\n"
                f"🏟️ *Partido:* {propuesta['partido']}\n"
                f"───────────────────────────\n"
                f"📌 *Mercado:* {pick['categoria']}\n"
                f"👉 **{pick['texto']}**\n"
                f"───────────────────────────\n"
                f"📊 *Sustento Estadístico:* {pick['razon']}\n"
                f"🔥 *Nivel de Confianza:* {propuesta['score']:.1f}%\n"
                f"💰 *Piso de Cuota Betano:* {CUOTA_PISO_BETANO:.2f}+\n"
                f"🛡️ *Perfil:* Value Bettor Conservador-Activo"
            )
        enviar_telegram(mensaje)

if __name__ == "__main__":
    analizar_excel()
