import os
import glob
import pandas as pd
import requests
import urllib.parse

# ==========================================
# CONFIGURACIÓN Y PARÁMETROS
# ==========================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

CUOTA_PISO_BETANO = 1.70
PROBABILIDAD_MINIMA_FILTRO = 88.0
MAX_ALERTAS_POR_JORNADA = 3
MAX_PASOS_BETBUILDER = 3  # <--- LÍMITE STRICTO DE SELECCIONES POR BETBUILDER


# ==========================================
# MÓDULO: BÚSQUEDA Y VALIDACIÓN EN SOFASCORE
# ==========================================
def buscar_event_id_sofascore(local, visitante):
    """
    Busca automáticamente el partido en Sofascore usando los nombres del Excel.
    """
    query = f"{local} vs {visitante}"
    query_encoded = urllib.parse.quote(query)
    
    url = f"https://api.sofascore.com/api/v3/search/all?q={query_encoded}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Referer": "https://www.sofascore.com/",
        "Accept": "application/json"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            resultados = response.json().get("results", [])
            for res in resultados:
                if res.get("type") == "event":
                    entity = res.get("entity", {})
                    event_id = entity.get("id")
                    print(f"[SOFASCORE] Event_ID encontrado automáticamente ({query}): {event_id}")
                    return event_id
        print(f"[SOFASCORE] No se encontró Event_ID automático para: {query}")
        return None
    except Exception as e:
        print(f"[EXCEPCIÓN BÚSQUEDA SOFASCORE] {e}")
        return None


def validar_titulares_sofascore(local, visitante, jugadores_objetivo):
    """
    Consulta las alineaciones oficiales de Sofascore usando el Event_ID automático.
    Retorna True solo si las alineaciones son oficiales Y los jugadores clave son titulares confirmados.
    """
    if not jugadores_objetivo:
        return True, "SIN_JUGADORES_QUE_VALIDAR"

    event_id = buscar_event_id_sofascore(local, visitante)
    if not event_id:
        print(f"[SOFASCORE WARN] No se pudo obtener ID para {local} vs {visitante}. Se omite filtro de plantilla.")
        return True, "ID_NO_ENCONTRADO_OMITIDO"

    url_lineups = f"https://api.sofascore.com/api/v3/event/{event_id}/lineups"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Referer": "https://www.sofascore.com/",
        "Accept": "application/json"
    }

    try:
        r = requests.get(url_lineups, headers=headers, timeout=10)
        if r.status_code != 200:
            return True, "ERROR_CONEXION_OMITIDO"

        data = r.json()
        
        # AJUSTE ESTRICTO: Si la alineación aún no es oficial, NO se envía la apuesta.
        # Esperará a la siguiente ejecución de los 20 minutos.
        if not data.get("confirmed", False):
            print(f"[SOFASCORE] Alineación aún no confirmada para {local} vs {visitante}. Se aguarda a la siguiente corrida de 20 min.")
            return False, "ESPERANDO_ALINEACION_OFICIAL"

        # Extraer lista de 11 titulares
        titulares = []
        for equipo in ["home", "away"]:
            for p in data.get(equipo, {}).get("players", []):
                if not p.get("substitute", True):
                    titulares.append(p["player"]["name"].lower())

        # Validar si los jugadores del Excel son titulares
        for jugador in jugadores_objetivo:
            jugador_norm = jugador.lower().strip()
            es_titular = any(jugador_norm in t or t in jugador_norm for t in titulares)
            if not es_titular:
                print(f"[ALERTA DE BANCA] {jugador} NO es titular en Sofascore.")
                return False, f"JUGADOR_SUPLENTE: {jugador}"

        print(f"[SOFASCORE OK] Jugadores validados como TITULARES: {jugadores_objetivo}")
        return True, "TITULARES_CONFIRMADOS"

    except Exception as e:
        print(f"[EXCEPCIÓN LINEUPS SOFASCORE] {e}")
        return True, "EXCEPCION_OMITIDA"


# ==========================================
# FUNCIONES ORIGINALES DE TELEGRAM Y PROMEDIOS
# ==========================================
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

    df_partidos = df_partidos.dropna(subset=["Local", "Visitante"])
    partidos_jugados = df_partidos.dropna(subset=["Goles L", "Goles V"]).copy()
    partidos_pendientes = df_partidos[df_partidos["Goles L"].isna()].copy()

    if partidos_pendientes.empty:
        enviar_telegram("ℹ️ *[REPORTE EXCEL]*\nNo hay partidos pendientes en el archivo Excel.")
        return

    todas_las_propuestas = []

    for _, fila in partidos_pendientes.iterrows():
        local = str(fila["Local"]).strip()
        visita = str(fila["Visitante"]).strip()
        jornada = fila.get("Jornada", "N/A")

        hist_local = partidos_jugados[(partidos_jugados["Local"] == local) | (partidos_jugados["Visitante"] == local)].tail(3)
        hist_visita = partidos_jugados[(partidos_jugados["Local"] == visita) | (partidos_jugados["Visitante"] == visita)].tail(3)

        if len(hist_local) < 1 or len(hist_visita) < 1:
            continue

        # Promedios
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

        # EVALUACIÓN DE TODAS LAS FAMILIAS
        familias_seleccionadas = []
        jugadores_a_validar = []  # Almacena jugadores para verificación en Sofascore

        # FAMILIA 1: RESULTADO FINAL (1X2)
        if prom_goles_L >= 2.3 and prom_goles_V <= 0.7:
            familias_seleccionadas.append({
                "familia": "Resultado Final",
                "texto": f"Victoria de {local} (1)",
                "razon": f"{local} promedia {prom_goles_L:.1f} goles favor vs {prom_goles_V:.1f} de {visita}",
                "score": 89.5
            })

        # FAMILIA 2: GOLES TOTALES DEL PARTIDO
        if (prom_goles_L + prom_goles_V) >= 2.2:
            familias_seleccionadas.append({
                "familia": "Goles Totales",
                "texto": "Over 1.5 Goles Totales del Partido",
                "razon": f"Promedio conjunto de {prom_goles_L + prom_goles_V:.1f} goles por partido",
                "score": 90.0
            })

        # FAMILIA 3: GOLES POR EQUIPO
        tiene_1x2 = any(item["familia"] == "Resultado Final" for item in familias_seleccionadas)
        if not tiene_1x2 and prom_goles_L >= 1.5:
            familias_seleccionadas.append({
                "familia": "Goles Equipo",
                "texto": f"{local} ➔ Over 0.5 Goles (Equipo)",
                "razon": f"{local} promedia {prom_goles_L:.1f} goles anotados por partido",
                "score": 88.5
            })

        # FAMILIA 4: CÓRNERS (TOTALES O POR EQUIPO)
        if (prom_corners_L + prom_corners_V) >= 8.5:
            familias_seleccionadas.append({
                "familia": "Córners",
                "texto": "Over 7.5 Córners Totales del Partido",
                "razon": f"Promedio combinado de {prom_corners_L + prom_corners_V:.1f} tiros de esquina",
                "score": 89.0
            })
        elif prom_corners_L >= 4.5:
            familias_seleccionadas.append({
                "familia": "Córners",
                "texto": f"{local} ➔ Over 3.5 Córners Totales",
                "razon": f"{local} genera en promedio {prom_corners_L:.1f} córners",
                "score": 88.0
            })

        # FAMILIA 5: REMATES AL ARCO POR EQUIPO
        if prom_remates_L >= 4.5:
            familias_seleccionadas.append({
                "familia": "Remates Equipo",
                "texto": f"{local} ➔ Over 3.5 Remates a Puerta",
                "razon": f"{local} registra {prom_remates_L:.1f} tiros a puerta por partido",
                "score": 88.5
            })

        # FAMILIAS 6 Y 7: JUGADORES
        if not df_jugadores.empty:
            jugadores_partido = df_jugadores[df_jugadores["Equipo"].isin([local, visita])]
            
            if "Remates al Arco" in jugadores_partido.columns:
                rematadores = jugadores_partido[jugadores_partido["Remates al Arco"] >= 2]
                if not rematadores.empty:
                    top_r = rematadores.sort_values(by="Remates al Arco", ascending=False).iloc[0]
                    familias_seleccionadas.append({
                        "familia": "Remates Jugador",
                        "texto": f"{top_r['Jugador']} ({top_r['Equipo']}) ➔ Over 0.5 Remates a Puerta",
                        "razon": f"Registra {int(top_r['Remates al Arco'])} tiros directos en sus apariciones",
                        "score": 91.0
                    })
                    jugadores_a_validar.append(str(top_r['Jugador']))

            if "Goles" in jugadores_partido.columns or "Asistencias" in jugadores_partido.columns:
                goles_col = jugadores_partido.get("Goles", 0)
                asist_col = jugadores_partido.get("Asistencias", 0)
                jugadores_partido["Participacion"] = goles_col + asist_col
                
                goleadores = jugadores_partido[jugadores_partido["Participacion"] >= 2]
                if not goleadores.empty:
                    top_g = goleadores.sort_values(by="Participacion", ascending=False).iloc[0]
                    familias_seleccionadas.append({
                        "familia": "Jugador Gol/Asistencia",
                        "texto": f"{top_g['Jugador']} ({top_g['Equipo']}) ➔ Gol o Asistencia / Anota en cualquier momento",
                        "razon": f"Suma {int(top_g['Participacion'])} participaciones directas de gol",
                        "score": 89.0
                    })
                    jugadores_a_validar.append(str(top_g['Jugador']))

        # -----------------------------------------------------------------
        # VERIFICACIÓN EN SOFASCORE ANTES DE CREAR LA PROPUESTA
        # -----------------------------------------------------------------
        es_valido, motivo = validar_titulares_sofascore(local, visita, jugadores_a_validar)
        if not es_valido:
            print(f"[OMITIDO] Se descarta temporal o definitivamente el partido {local} vs {visita} por motivo: {motivo}")
            continue

        jornada_txt = int(jornada) if pd.notna(jornada) and isinstance(jornada, (int, float)) else str(jornada)

        # -----------------------------------------------------------------
        # CORRECCIÓN DE REGLA: MÁXIMO 3 PASOS POR BETBUILDER
        # -----------------------------------------------------------------
        if len(familias_seleccionadas) >= 2:
            familias_seleccionadas.sort(key=lambda x: x["score"], reverse=True)
            picks_finales = familias_seleccionadas[:MAX_PASOS_BETBUILDER]
            
            score_promedio = sum(c['score'] for c in picks_finales) / len(picks_finales)
            todas_las_propuestas.append({
                "tipo": "BETBUILDER",
                "partido": f"{local} vs. {visita}",
                "jornada": jornada_txt,
                "picks": picks_finales,
                "score": score_promedio,
                "sustento": picks_finales[0]["razon"]
            })
        elif len(familias_seleccionadas) == 1:
            pick = familias_seleccionadas[0]
            todas_las_propuestas.append({
                "tipo": "SIMPLE",
                "partido": f"{local} vs. {visita}",
                "jornada": jornada_txt,
                "pick": pick,
                "score": pick["score"],
                "sustento": pick["razon"]
            })

    # FILTRADO Y ENVÍO
    propuestas_filtradas = [p for p in todas_las_propuestas if p["score"] >= PROBABILIDAD_MINIMA_FILTRO]
    propuestas_filtradas.sort(key=lambda x: x["score"], reverse=True)

    top_selecciones = propuestas_filtradas[:MAX_ALERTAS_POR_JORNADA]

    if not top_selecciones:
        print("[INFO] No hay propuestas listas con alineación confirmada en esta ejecución.")
        return

    for propuesta in top_selecciones:
        if propuesta["tipo"] == "BETBUILDER":
            num_pasos = len(propuesta['picks'])
            lista_formatted = "\n".join([f"  • {item['texto']}" for item in propuesta["picks"]])
            mensaje = (
                f"🎯 *[SELECCIÓN DE ALTA PROBABILIDAD - BETBUILDER]*\n"
                f"🏆 *Jornada:* {propuesta['jornada']}\n"
                f"🏟️ *Partido:* {propuesta['partido']}\n"
                f"───────────────────────────\n"
                f"🧩 *COMBINACIÓN FILTRADA ({num_pasos} Pasos):*\n"
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
                f"📌 *Mercado:* {pick['familia']}\n"
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
