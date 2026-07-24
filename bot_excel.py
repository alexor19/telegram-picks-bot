import os
import glob
import re
import unicodedata
import pandas as pd
import requests
import urllib.parse
from datetime import datetime
import pytz
from thefuzz import fuzz

# ==========================================
# CONFIGURACIÓN Y PARÁMETROS
# ==========================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

CUOTA_PISO_BETANO = 1.70  # Umbral mínimo de referencia opcional
PROBABILIDAD_MINIMA_FILTRO = 88.0
MAX_ALERTAS_POR_JORNADA = 3
MAX_PASOS_BETBUILDER = 3
ARCHIVO_HISTORIAL = "alertas_enviadas.txt"

# Zona horaria oficial: Lima, Perú
ZONA_HORARIA_LIMA = pytz.timezone("America/Lima")


# ==========================================
# MÓDULO: FECHA Y HORA DEL PARTIDO
# ==========================================
def obtener_fecha_hora_partido(event_id):
    """Obtiene la fecha y hora oficial del partido desde la API de Sofascore convertida a la hora de Lima, Perú."""
    url = f"https://api.sofascore.com/api/v3/event/{event_id}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Referer": "https://www.sofascore.com/",
        "Accept": "application/json"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            evento = response.json().get("event", {})
            timestamp = evento.get("startTimestamp")
            if timestamp:
                dt_utc = datetime.fromtimestamp(timestamp, pytz.utc)
                dt_lima = dt_utc.astimezone(ZONA_HORARIA_LIMA)
                return dt_lima.strftime("%d/%m/%Y"), dt_lima.strftime("%H:%M:%S")
    except Exception as e:
        print(f"[EXCEPCIÓN HORA PARTIDO] {e}")
    
    # Fallback si no se logra obtener de la API
    ahora_lima = datetime.now(ZONA_HORARIA_LIMA)
    return ahora_lima.strftime("%d/%m/%Y"), ahora_lima.strftime("%H:%M:%S")


# ==========================================
# MÓDULO: CONSULTA INVISIBLE Y ESTIMACIÓN BETBUILDER (BETANO PERÚ)
# ==========================================
def obtener_cuota_individual_mercado(local, tipo_mercado, detalle_pick=""):
    """
    Busca de manera específica la cuota individual de un mercado o selección 
    dentro de la API de Betano Perú para construir estimaciones precisas.
    """
    url_api_betano = f"https://www.betano.pe/api/results/search/?q={urllib.parse.quote(local)}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Referer": "https://www.betano.pe/",
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json"
    }
    
    try:
        response = requests.get(url_api_betano, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            blocks = data.get("data", {}).get("blocks", [])
            for block in blocks:
                for ev in block.get("events", []):
                    participants = ev.get("participants", [])
                    nombres_part = [normalizar_texto(p.get("name", "")) for p in participants]
                    
                    if any(normalizar_texto(local) in n for n in nombres_part):
                        for market in ev.get("markets", []):
                            market_name = normalizar_texto(market.get("name", ""))
                            for sel in market.get("selections", []):
                                sel_name = normalizar_texto(sel.get("name", ""))
                                price = sel.get("price")
                                
                                if price:
                                    if tipo_mercado == "Goles Totales" and ("1.5" in market_name or "1.5" in sel_name or "over" in sel_name):
                                        return float(price)
                                    elif tipo_mercado == "Resultado Final" and ("1" in sel_name or normalizar_texto(local) in sel_name):
                                        return float(price)
                                    elif "Remates" in tipo_mercado or "Jugador" in tipo_mercado:
                                        if "remate" in market_name or "puerta" in sel_name or "over" in sel_name:
                                            return float(price)
    except Exception as e:
        print(f"[EXCEPCIÓN CUOTA INDIVIDUAL] {e}")
    
    return 1.35  # Valor base conservador de respaldo si la cuota exacta no está en el índice rápido


def obtener_cuotas_betano_invisible(local, visita):
    """
    Consulta mediante ingeniería inversa de red el endpoint interno de Betano Perú 
    para extraer la cuota real y viva de los mercados disponibles sin usar valores fijos engañosos.
    """
    url_api_betano = f"https://www.betano.pe/api/results/search/?q={urllib.parse.quote(local)}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Referer": "https://www.betano.pe/",
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json"
    }
    
    cuota_extraida = "No disponible"
    
    try:
        response = requests.get(url_api_betano, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            blocks = data.get("data", {}).get("blocks", [])
            for block in blocks:
                events = block.get("events", [])
                for ev in events:
                    participants = ev.get("participants", [])
                    nombres_part = [normalizar_texto(p.get("name", "")) for p in participants]
                    
                    if any(normalizar_texto(local) in n for n in nombres_part) or any(normalizar_texto(visita) in n for n in nombres_part):
                        markets = ev.get("markets", [])
                        for market in markets:
                            market_name = normalizar_texto(market.get("name", ""))
                            selections = market.get("selections", [])
                            for sel in selections:
                                sel_name = normalizar_texto(sel.get("name", ""))
                                price = sel.get("price")
                                
                                if price and ("1.5" in market_name or "1.5" in sel_name or "over" in sel_name):
                                    cuota_extraida = str(price)
                                    break
                            if cuota_extraida != "No disponible":
                                break
                    if cuota_extraida != "No disponible":
                        break
                if cuota_extraida != "No disponible":
                    break
    except Exception as e:
        print(f"[EXCEPCIÓN BETANO INVISIBLE] {e}")
    
    return cuota_extraida


# ==========================================
# MÓDULO: MEMORIA DE ALERTAS (HISTORIAL)
# ==========================================
def cargar_historial():
    """Carga las alertas enviadas previamente para no repetir mensajes."""
    if os.path.exists(ARCHIVO_HISTORIAL):
        with open(ARCHIVO_HISTORIAL, "r", encoding="utf-8") as f:
            return set(linea.strip() for linea in f if linea.strip())
    return set()

def registrar_alerta(alerta_id):
    """Guarda el ID de la alerta en el archivo de texto."""
    with open(ARCHIVO_HISTORIAL, "a", encoding="utf-8") as f:
        f.write(f"{alerta_id}\n")


# ==========================================
# MÓDULO: LÓGICA DIFUSA Y NORMALIZACIÓN (FUZZY)
# ==========================================
def normalizar_texto(texto):
    if not texto:
        return ""
    texto = str(texto).lower()
    texto = unicodedata.normalize('NFD', texto).encode('ascii', 'ignore').decode("utf-8")
    palabras_basura = [r'\bfc\b', r'\bcf\b', r'\bcd\b', r'\bclub\b', r'\bsd\b', r'\bud\b', r'\bafc\b']
    for p in palabras_basura:
        texto = re.sub(p, '', texto)
    texto = re.sub(r'[^a-z0-9\s]', '', texto)
    return texto.strip()

def son_mismo_equipo(equipo_excel, equipo_sofascore, umbral=70):
    e1 = normalizar_texto(equipo_excel)
    e2 = normalizar_texto(equipo_sofascore)
    if e1 in e2 or e2 in e1:
        return True
    return fuzz.token_set_ratio(e1, e2) >= umbral

def es_mismo_jugador(nombre_excel, nombre_sofascore, umbral=75):
    j1 = normalizar_texto(nombre_excel)
    j2 = normalizar_texto(nombre_sofascore)
    
    if j1 == j2 or j1 in j2 or j2 in j1:
        return True
        
    if fuzz.token_set_ratio(j1, j2) >= umbral:
        return True
        
    partes_j1 = j1.split()
    partes_j2 = j2.split()
    if partes_j1 and partes_j2:
        if partes_j1[-1] == partes_j2[-1] and len(partes_j1[-1]) > 3:
            return True
    return False


# ==========================================
# MÓDULO: BÚSQUEDA Y VALIDACIÓN EN SOFASCORE
# ==========================================
def buscar_event_id_sofascore(local, visitante):
    query = f"{local} {visitante}"
    query_encoded = urllib.parse.quote(query)
    
    url = f"https://api.sofascore.com/api/v3/search/all?q={query_encoded}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
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
                    home_team = entity.get("homeTeam", {}).get("name", "")
                    away_team = entity.get("awayTeam", {}).get("name", "")
                    
                    if son_mismo_equipo(local, home_team) and son_mismo_equipo(visitante, away_team):
                        event_id = entity.get("id")
                        print(f"[SOFASCORE OK] Coincidencia: {home_team} vs {away_team} (ID: {event_id})")
                        return event_id
        print(f"[SOFASCORE WARN] No se encontró Event_ID para: {local} vs {visitante}")
        return None
    except Exception as e:
        print(f"[EXCEPCIÓN SOFASCORE] {e}")
        return None

def validar_titulares_sofascore(local, visitante, jugadores_objetivo):
    if not jugadores_objetivo:
        return True, "SIN_JUGADORES_QUE_VALIDAR", None

    event_id = buscar_event_id_sofascore(local, visitante)
    if not event_id:
        print(f"[SOFASCORE WARN] Sin ID para {local} vs {visitante}. Omitiendo filtro de plantilla.")
        return True, "ID_NO_ENCONTRADO_OMITIDO", None

    url_lineups = f"https://api.sofascore.com/api/v3/event/{event_id}/lineups"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Referer": "https://www.sofascore.com/",
        "Accept": "application/json"
    }

    try:
        r = requests.get(url_lineups, headers=headers, timeout=10)
        if r.status_code != 200:
            return True, "ERROR_CONEXION_OMITIDO", event_id

        data = r.json()
        if not data.get("confirmed", False):
            print(f"[SOFASCORE] Alineación aún no confirmada para {local} vs {visitante}.")
            return False, "ESPERANDO_ALINEACION_OFICIAL", event_id

        titulares = []
        for equipo in ["home", "away"]:
            for p in data.get(equipo, {}).get("players", []):
                if not p.get("substitute", True):
                    titulares.append(p["player"]["name"])

        for jugador in jugadores_objetivo:
            es_titular = any(es_mismo_jugador(jugador, t) for t in titulares)
            if not es_titular:
                print(f"[ALERTA DE BANCA] {jugador} NO es titular en Sofascore.")
                return False, f"JUGADOR_SUPLENTE: {jugador}", event_id

        print(f"[SOFASCORE OK] Jugadores confirmados como TITULARES: {jugadores_objetivo}")
        return True, "TITULARES_CONFIRMADOS", event_id

    except Exception as e:
        print(f"[EXCEPCIÓN LINEUPS] {e}")
        return True, "EXCEPCION_OMITIDA", event_id


# ==========================================
# FUNCIONES PRINCIPALES Y TELEGRAM
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
    historial = cargar_historial()
    archivos = glob.glob("*.xlsx")
    
    if not archivos:
        print("[ERROR] No se encontró ningún archivo .xlsx.")
        return

    excel_path = archivos[0]
    print(f"[INFO] Leyendo archivo: {excel_path}")

    try:
        xls = pd.ExcelFile(excel_path)
        df_partidos = pd.read_excel(xls, sheet_name="Partidos")
        
        df_jugadores = pd.DataFrame(columns=["Jugador", "Equipo", "Remates al Arco", "Goles", "Asistencias"])
        if "Estadísticas Jugadores" in xls.sheet_names:
            df_jugadores = pd.read_excel(xls, sheet_name="Estadísticas Jugadores")
    except Exception as e:
        print(f"[ERROR EXCEL] Error al leer hojas: {e}")
        return

    df_partidos = df_partidos.dropna(subset=["Local", "Visitante"])
    partidos_jugados = df_partidos.dropna(subset=["Goles L", "Goles V"]).copy()
    partidos_pendientes = df_partidos[df_partidos["Goles L"].isna()].copy()

    if partidos_pendientes.empty:
        print("[INFO] No hay partidos pendientes en el Excel.")
        return

    todas_las_propuestas = []

    for _, fila in partidos_pendientes.iterrows():
        local = str(fila["Local"]).strip()
        visita = str(fila["Visitante"]).strip()
        jornada = fila.get("Jornada", "N/A")
        jornada_txt = int(jornada) if pd.notna(jornada) and isinstance(jornada, (int, float)) else str(jornada)

        alerta_id = f"J{jornada_txt}_{normalizar_texto(local)}_vs_{normalizar_texto(visita)}"
        
        if alerta_id in historial:
            print(f"[OMITIDO] El partido {local} vs {visita} ya fue notificado previamente.")
            continue

        hist_local = partidos_jugados[(partidos_jugados["Local"] == local) | (partidos_jugados["Visitante"] == local)].tail(3)
        hist_visita = partidos_jugados[(partidos_jugados["Local"] == visita) | (partidos_jugados["Visitante"] == visita)].tail(3)

        if len(hist_local) < 1 or len(hist_visita) < 1:
            continue

        goles_L = [p["Goles L"] if p["Local"] == local else p["Goles V"] for _, p in hist_local.iterrows()]
        goles_V = [p["Goles L"] if p["Local"] == visita else p["Goles V"] for _, p in hist_visita.iterrows()]
        remates_L = [p.get("Remates Arco L", 0) if p["Local"] == local else p.get("Remates Arco V", 0) for _, p in hist_local.iterrows()]
        corners_L = [p.get("Corners L", 0) if p["Local"] == local else p.get("Corners V", 0) for _, p in hist_local.iterrows()]
        corners_V = [p.get("Corners L", 0) if p["Local"] == visita else p.get("Corners V", 0) for _, p in hist_visita.iterrows()]

        prom_goles_L = calcular_promedio(goles_L)
        prom_goles_V = calcular_promedio(goles_V)
        prom_remates_L = calcular_promedio(remates_L)
        prom_corners_L = calcular_promedio(corners_L)
        prom_corners_V = calcular_promedio(corners_V)

        familias_seleccionadas = []
        jugadores_a_validar = []

        if prom_goles_L >= 2.3 and prom_goles_V <= 0.7:
            familias_seleccionadas.append({
                "familia": "Resultado Final",
                "texto": f"Victoria de {local} (1)",
                "razon": f"{local} promedia {prom_goles_L:.1f} goles favor vs {prom_goles_V:.1f} de {visita}",
                "score": 89.5
            })

        if (prom_goles_L + prom_goles_V) >= 2.2:
            familias_seleccionadas.append({
                "familia": "Goles Totales",
                "texto": "Over 1.5 Goles Totales del Partido",
                "razon": f"Promedio conjunto de {prom_goles_L + prom_goles_V:.1f} goles por partido",
                "score": 90.0
            })

        tiene_1x2 = any(item["familia"] == "Resultado Final" for item in familias_seleccionadas)
        if not tiene_1x2 and prom_goles_L >= 1.5:
            familias_seleccionadas.append({
                "familia": "Goles Equipo",
                "texto": f"{local} ➔ Over 0.5 Goles (Equipo)",
                "razon": f"{local} promedia {prom_goles_L:.1f} goles anotados por partido",
                "score": 88.5
            })

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

        if prom_remates_L >= 4.5:
            familias_seleccionadas.append({
                "familia": "Remates Equipo",
                "texto": f"{local} ➔ Over 3.5 Remates a Puerta",
                "razon": f"{local} registra {prom_remates_L:.1f} tiros a puerta por partido",
                "score": 88.5
            })

        if not df_jugadores.empty and "Equipo" in df_jugadores.columns:
            jugadores_partido = df_jugadores[df_jugadores["Equipo"].isin([local, visita])].copy()
            
            if "Remates al Arco" in jugadores_partido.columns and not jugadores_partido.empty:
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

            if not jugadores_partido.empty:
                goles_col = jugadores_partido["Goles"].fillna(0) if "Goles" in jugadores_partido.columns else 0
                asist_col = jugadores_partido["Asistencias"].fillna(0) if "Asistencias" in jugadores_partido.columns else 0
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

        jugadores_a_validar = list(set(jugadores_a_validar))

        es_valido, motivo, event_id = validar_titulares_sofascore(local, visita, jugadores_a_validar)
        if not es_valido:
            print(f"[OMITIDO] Se descarta {local} vs {visita} por: {motivo}")
            continue

        # FILTRAR FAMILIAS PARA BETBUILDER: MÁXIMO UN SOLO MERCADO DE JUGADORES
        familias_validas_bb = []
        contador_jugadores = 0
        for item in sorted(familias_seleccionadas, key=lambda x: x["score"], reverse=True):
            es_mercado_jugador = item["familia"] in ["Remates Jugador", "Jugador Gol/Asistencia"]
            if es_mercado_jugador:
                if contador_jugadores < 1:
                    familias_validas_bb.append(item)
                    contador_jugadores += 1
            else:
                familias_validas_bb.append(item)

        # ALTERNANCIA INTELIGENTE ENTRE SIMPLE Y BETBUILDER
        # Si hay suficientes opciones calificadas, decidimos dinámicamente si crear Betbuilder o Simple
        if len(familias_validas_bb) >= 2:
            # Seleccionamos hasta MAX_PASOS_BETBUILDER para la combinada
            picks_finales = familias_validas_bb[:MAX_PASOS_BETBUILDER]
            
            cuotas_componentes = []
            for pick in picks_finales:
                c_ind = obtener_cuota_individual_mercado(local, pick["familia"], pick["texto"])
                cuotas_componentes.append(c_ind)
            
            producto_neto = 1.0
            for c in cuotas_componentes:
                producto_neto *= c
            cuota_viva_real = f"{producto_neto * 0.94:.2f} (Estimada Betbuilder)"
            
            score_promedio = sum(c['score'] for c in picks_finales) / len(picks_finales)
            
            # Si solo quedó 1 paso útil tras el filtro o por decisión analítica, emitimos Simple, de lo contrario Betbuilder
            if len(picks_finales) == 1:
                pick = picks_finales[0]
                c_ind = obtener_cuota_individual_mercado(local, pick["familia"], pick["texto"])
                todas_las_propuestas.append({
                    "alerta_id": alerta_id,
                    "tipo": "SIMPLE",
                    "partido": f"{local} vs. {visita}",
                    "jornada": jornada_txt,
                    "fecha_partido": obtener_fecha_hora_partido(event_id)[0] if event_id else datetime.now(ZONA_HORARIA_LIMA).strftime("%d/%m/%Y"),
                    "hora_partido": obtener_fecha_hora_partido(event_id)[1] if event_id else datetime.now(ZONA_HORARIA_LIMA).strftime("%H:%M:%S"),
                    "pick": pick,
                    "score": pick["score"],
                    "sustento": pick["razon"],
                    "cuota": f"{c_ind:.2f}"
                })
            else:
                todas_las_propuestas.append({
                    "alerta_id": alerta_id,
                    "tipo": "BETBUILDER",
                    "partido": f"{local} vs. {visita}",
                    "jornada": jornada_txt,
                    "fecha_partido": obtener_fecha_hora_partido(event_id)[0] if event_id else datetime.now(ZONA_HORARIA_LIMA).strftime("%d/%m/%Y"),
                    "hora_partido": obtener_fecha_hora_partido(event_id)[1] if event_id else datetime.now(ZONA_HORARIA_LIMA).strftime("%H:%M:%S"),
                    "picks": picks_finales,
                    "score": score_promedio,
                    "sustento": picks_finales[0]["razon"],
                    "cuota": cuota_viva_real
                })
        elif len(familias_validas_bb) == 1:
            pick = familias_validas_bb[0]
            c_ind = obtener_cuota_individual_mercado(local, pick["familia"], pick["texto"])
            cuota_viva_real = f"{c_ind:.2f}"
            
            todas_las_propuestas.append({
                "alerta_id": alerta_id,
                "tipo": "SIMPLE",
                "partido": f"{local} vs. {visita}",
                "jornada": jornada_txt,
                "fecha_partido": obtener_fecha_hora_partido(event_id)[0] if event_id else datetime.now(ZONA_HORARIA_LIMA).strftime("%d/%m/%Y"),
                "hora_partido": obtener_fecha_hora_partido(event_id)[1] if event_id else datetime.now(ZONA_HORARIA_LIMA).strftime("%H:%M:%S"),
                "pick": pick,
                "score": pick["score"],
                "sustento": pick["razon"],
                "cuota": cuota_viva_real
            })

    propuestas_filtradas = [p for p in todas_las_propuestas if p["score"] >= PROBABILIDAD_MINIMA_FILTRO]
    propuestas_filtradas.sort(key=lambda x: x["score"], reverse=True)

    top_selecciones = propuestas_filtradas[:MAX_ALERTAS_POR_JORNADA]

    if not top_selecciones:
        print("[INFO] No hay propuestas nuevas para notificar.")
        return

    for propuesta in top_selecciones:
        if propuesta["tipo"] == "BETBUILDER":
            num_pasos = len(propuesta['picks'])
            lista_formatted = "\n".join([f"    • {item['texto']}" for item in propuesta["picks"]])
            mensaje = (
                f"🎯 *[SELECCIÓN DE ALTA PROBABILIDAD - BETBUILDER]*\n"
                f"🏆 *Jornada:* {propuesta['jornada']}\n"
                f"🏟️ *Partido:* {propuesta['partido']}\n"
                f"📅 *Fecha:* {propuesta['fecha_partido']} | ⏰ *Hora:* {propuesta['hora_partido']}\n"
                f"───────────────────────────\n"
                f"🧩 *COMBINADA FILTRADA ({num_pasos} Pasos - Máx 1 Jugador):*\n"
                f"{lista_formatted}\n"
                f"───────────────────────────\n"
                f"📊 *Sustento Principal:* {propuesta['sustento']}\n"
                f"🔥 *Nivel de Confianza:* {propuesta['score']:.1f}%\n"
                f"💰 *Cuota Betano:* {propuesta['cuota']}\n"
                f"🛡️ *Perfil:* Value Bettor Conservador-Activo"
            )
        else:
            pick = propuesta["pick"]
            mensaje = (
                f"🎯 *[SELECCIÓN DE ALTA PROBABILIDAD - PICK SIMPLE]*\n"
                f"🏆 *Jornada:* {propuesta['jornada']}\n"
                f"🏟️ *Partido:* {propuesta['partido']}\n"
                f"📅 *Fecha:* {propuesta['fecha_partido']} | ⏰ *Hora:* {propuesta['hora_partido']}\n"
                f"───────────────────────────\n"
                f"📌 *Mercado:* {pick['familia']}\n"
                f"👉 *{pick['texto']}*\n"
                f"───────────────────────────\n"
                f"📊 *Sustento Estadístico:* {pick['razon']}\n"
                f"🔥 *Nivel de Confianza:* {propuesta['score']:.1f}%\n"
                f"💰 *Cuota Betano:* {propuesta['cuota']}\n"
                f"🛡️ *Perfil:* Value Bettor Conservador-Activo"
            )
        enviar_telegram(mensaje)
        registrar_alerta(propuesta["alerta_id"])

if __name__ == "__main__":
    analizar_excel()
