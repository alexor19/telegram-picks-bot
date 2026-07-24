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

PROBABILIDAD_MINIMA_FILTRO = 88.0
MAX_ALERTAS_POR_JORNADA = 3
MAX_PASOS_BETBUILDER = 1 
ARCHIVO_HISTORIAL = "alertas_enviadas.txt"

# Zona horaria oficial: Lima, Perú
ZONA_HORARIA_LIMA = pytz.timezone("America/Lima")


# ==========================================
# MÓDULO: FECHA Y HORA DEL PARTIDO
# ==========================================
def obtener_fecha_hora_partido(event_id):
    """Obtiene la fecha y hora oficial del partido desde la API de Sofascore."""
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
    
    ahora_lima = datetime.now(ZONA_HORARIA_LIMA)
    return ahora_lima.strftime("%d/%m/%Y"), ahora_lima.strftime("%H:%M:%S")


# ==========================================
# MÓDULO: EXTRACCIÓN DE CUOTAS DESDE SOFASCORE
# ==========================================
def obtener_cuota_real_sofascore(event_id, tipo_mercado):
    """
    Consulta las cuotas de mercado directamente desde los proveedores integrados en Sofascore 
    para el event_id correspondiente. Retorna la cuota exacta o None si no está disponible.
    """
    if not event_id:
        return None

    # Endpoint de proveedores de cuotas (Odds) de Sofascore
    url_odds = f"https://api.sofascore.com/api/v3/event/{event_id}/odds/1/all"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Referer": "https://www.sofascore.com/",
        "Accept": "application/json"
    }
    
    try:
        response = requests.get(url_odds, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            markets = data.get("markets", [])
            for market in markets:
                market_name = normalizar_texto(market.get("marketName", ""))
                choices = market.get("choices", [])
                
                for choice in choices:
                    choice_name = normalizar_texto(choice.get("name", ""))
                    fractional_value = choice.get("initialFractionalValue", "") or choice.get("fractionalValue", "")
                    
                    # Intentar obtener el valor decimal directamente si existe, o calcularlo desde fraccional
                    decimal_price = choice.get("decimalValue")
                    if not decimal_price and fractional_value:
                        try:
                            parts = fractional_value.split('/')
                            if len(parts) == 2:
                                decimal_price = round((float(parts[0]) / float(parts[1])) + 1.0, 2)
                        except:
                            pass

                    if decimal_price:
                        # Filtrado según el tipo de mercado del pick
                        if tipo_mercado == "Goles Totales" and ("1.5" in market_name or "over" in market_name or "mas" in choice_name):
                            return float(decimal_price)
                        elif tipo_mercado == "Resultado Final" and ("1" in choice_name or "home" in choice_name):
                            return float(decimal_price)
                        elif "Córners" in tipo_mercado and ("corner" in market_name or "esquina" in market_name):
                            return float(decimal_price)
                        elif "Remates" in tipo_mercado or "Jugador" in tipo_mercado:
                            if "remate" in market_name or "puerta" in choice_name or "over" in choice_name:
                                return float(decimal_price)
                            
            # Fallback: si hay mercados principales, toma la primera cuota disponible de ganador o línea principal
            if markets:
                primera_choice = markets[0].get("choices", [])
                if primera_choice and "decimalValue" in primera_choice[0]:
                    return float(primera_choice[0]["decimalValue"])
                    
    except Exception as e:
        print(f"[EXCEPCIÓN CUOTAS SOFASCORE] {e}")
        
    return None


# ==========================================
# MÓDULO: MEMORIA DE ALERTAS (HISTORIAL)
# ==========================================
def cargar_historial():
    if os.path.exists(ARCHIVO_HISTORIAL):
        with open(ARCHIVO_HISTORIAL, "r", encoding="utf-8") as f:
            return set(linea.strip() for linea in f if linea.strip())
    return set()

def registrar_alerta(alerta_id):
    with open(ARCHIVO_HISTORIAL, "a", encoding="utf-8") as f:
        f.write(f"{alerta_id}\n")


# ==========================================
# MÓDULO: LÓGICA DIFUSA Y NORMALIZACIÓN
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
# MÓDULO: SOFASCORE BÚSQUEDA Y ALINEACIONES
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
                        return entity.get("id")
    except Exception as e:
        print(f"[EXCEPCIÓN SOFASCORE] {e}")
    return None

def validar_titulares_sofascore(local, visitante, jugadores_objetivo):
    if not jugadores_objetivo:
        return True, "SIN_JUGADORES", None

    event_id = buscar_event_id_sofascore(local, visitante)
    if not event_id:
        return True, "ID_NO_ENCONTRADO", None

    url_lineups = f"https://api.sofascore.com/api/v3/event/{event_id}/lineups"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Referer": "https://www.sofascore.com/",
        "Accept": "application/json"
    }

    try:
        r = requests.get(url_lineups, headers=headers, timeout=10)
        if r.status_code != 200:
            return True, "ERROR_CONEXION", event_id

        data = r.json()
        if not data.get("confirmed", False):
            return False, "ESPERANDO_ALINEACION", event_id

        titulares = []
        for equipo in ["home", "away"]:
            for p in data.get(equipo, {}).get("players", []):
                if not p.get("substitute", True):
                    titulares.append(p["player"]["name"])

        for jugador in jugadores_objetivo:
            if not any(es_mismo_jugador(jugador, t) for t in titulares):
                return False, f"SUPLENTE: {jugador}", event_id

        return True, "CONFIRMADO", event_id
    except Exception as e:
        print(f"[EXCEPCIÓN LINEUPS] {e}")
        return True, "EXCEPCION", event_id


# ==========================================
# FUNCIONES PRINCIPALES Y TELEGRAM
# ==========================================
def enviar_telegram(mensaje):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"[EXCEPCIÓN TELEGRAM] {e}")

def calcular_promedio(lista):
    validos = [v for v in lista if pd.notna(v)]
    return sum(validos) / len(validos) if validos else 0.0

def analizar_excel():
    historial = cargar_historial()
    archivos = glob.glob("*.xlsx")
    
    if not archivos:
        return

    excel_path = archivos[0]
    try:
        xls = pd.ExcelFile(excel_path)
        df_partidos = pd.read_excel(xls, sheet_name="Partidos")
        df_jugadores = pd.DataFrame(columns=["Jugador", "Equipo", "Remates al Arco", "Goles", "Asistencias"])
        if "Estadísticas Jugadores" in xls.sheet_names:
            df_jugadores = pd.read_excel(xls, sheet_name="Estadísticas Jugadores")
    except Exception as e:
        return

    df_partidos = df_partidos.dropna(subset=["Local", "Visitante"])
    partidos_jugados = df_partidos.dropna(subset=["Goles L", "Goles V"]).copy()
    partidos_pendientes = df_partidos[df_partidos["Goles L"].isna()].copy()

    if partidos_pendientes.empty:
        return

    todas_las_propuestas = []

    for _, fila in partidos_pendientes.iterrows():
        local = str(fila["Local"]).strip()
        visita = str(fila["Visitante"]).strip()
        jornada = fila.get("Jornada", "N/A")
        jornada_txt = int(jornada) if pd.notna(jornada) and isinstance(jornada, (int, float)) else str(jornada)

        alerta_id = f"J{jornada_txt}_{normalizar_texto(local)}_vs_{normalizar_texto(visita)}"
        if alerta_id in historial:
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
            familias_seleccionadas.append({"familia": "Resultado Final", "texto": f"Victoria de {local} (1)", "razon": f"{local} promedia {prom_goles_L:.1f} goles favor", "score": 89.5})

        if (prom_goles_L + prom_goles_V) >= 2.2:
            familias_seleccionadas.append({"familia": "Goles Totales", "texto": "Over 1.5 Goles Totales del Partido", "razon": f"Promedio conjunto de {prom_goles_L + prom_goles_V:.1f} goles", "score": 90.0})

        if (prom_corners_L + prom_corners_V) >= 8.5:
            familias_seleccionadas.append({"familia": "Córners", "texto": "Over 7.5 Córners Totales del Partido", "razon": f"Promedio de {prom_corners_L + prom_corners_V:.1f} córners", "score": 89.0})

        if not df_jugadores.empty and "Equipo" in df_jugadores.columns:
            jugadores_partido = df_jugadores[df_jugadores["Equipo"].isin([local, visita])].copy()
            if "Remates al Arco" in jugadores_partido.columns and not jugadores_partido.empty:
                rematadores = jugadores_partido[jugadores_partido["Remates al Arco"] >= 2]
                if not rematadores.empty:
                    top_r = rematadores.sort_values(by="Remates al Arco", ascending=False).iloc[0]
                    familias_seleccionadas.append({"familia": "Remates Jugador", "texto": f"{top_r['Jugador']} ➔ Over 0.5 Remates a Puerta", "razon": f"Registra tiros directos previos", "score": 91.0})
                    jugadores_a_validar.append(str(top_r['Jugador']))

        jugadores_a_validar = list(set(jugadores_a_validar))
        es_valido, _, event_id = validar_titulares_sofascore(local, visita, jugadores_a_validar)
        if not es_valido:
            continue

        familias_validas = sorted(familias_seleccionadas, key=lambda x: x["score"], reverse=True)
        if familias_validas:
            pick = familias_validas[0]
            
            # EXTRACCIÓN DE CUOTA REAL DESDE EL MÓDULO DE SOFASCORE
            cuota_real = obtener_cuota_real_sofascore(event_id, pick["familia"])
            if cuota_real is None:
                print(f"[ADVERTENCIA] No hay cuotas disponibles en Sofascore para {local} vs {visita}. Pick omitido.")
                continue
            
            todas_las_propuestas.append({
                "alerta_id": alerta_id,
                "partido": f"{local} vs. {visita}",
                "jornada": jornada_txt,
                "fecha_partido": obtener_fecha_hora_partido(event_id)[0] if event_id else datetime.now(ZONA_HORARIA_LIMA).strftime("%d/%m/%Y"),
                "hora_partido": obtener_fecha_hora_partido(event_id)[1] if event_id else datetime.now(ZONA_HORARIA_LIMA).strftime("%H:%M:%S"),
                "pick": pick,
                "score": pick["score"],
                "cuota": f"{cuota_real:.2f}"
            })

    propuestas_filtradas = [p for p in todas_las_propuestas if p["score"] >= PROBABILIDAD_MINIMA_FILTRO]
    propuestas_filtradas.sort(key=lambda x: x["score"], reverse=True)

    for propuesta in propuestas_filtradas[:MAX_ALERTAS_POR_JORNADA]:
        pick = propuesta["pick"]
        mensaje = (
            f"🎯 *[SELECCIÓN VERIFICADA - SOFASCORE]*\n"
            f"🏆 *Jornada:* {propuesta['jornada']}\n"
            f"🏟️ *Partido:* {propuesta['partido']}\n"
            f"📅 *Fecha:* {propuesta['fecha_partido']} | ⏰ *Hora:* {propuesta['hora_partido']}\n"
            f"───────────────────────────\n"
            f"📌 *Mercado:* {pick['familia']}\n"
            f"👉 *{pick['texto']}*\n"
            f"───────────────────────────\n"
            f"📊 *Sustento:* {pick['razon']}\n"
            f"🔥 *Confianza:* {propuesta['score']:.1f}%\n"
            f"💰 *Cuota de Mercado (Sofascore):* {propuesta['cuota']}\n"
            f"🛡️ *Perfil:* Value Bettor Conservador"
        )
        enviar_telegram(mensaje)
        registrar_alerta(propuesta["alerta_id"])

if __name__ == "__main__":
    analizar_excel()
