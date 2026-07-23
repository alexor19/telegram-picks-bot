import requests
import urllib.parse

def buscar_event_id_sofascore(local, visitante):
    """
    Busca automáticamente el partido en Sofascore usando los nombres del Excel
    y devuelve el Event_ID exacto.
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
                # Buscamos eventos de tipo 'event' (partidos)
                if res.get("type") == "event":
                    entity = res.get("entity", {})
                    event_id = entity.get("id")
                    print(f"[SOFASCORE] Partido encontrado automáticamente. ID: {event_id}")
                    return event_id
        print(f"[SOFASCORE] No se encontró Event_ID automático para: {query}")
        return None
    except Exception as e:
        print(f"[EXCEPCIÓN BÚSQUEDA SOFASCORE] {e}")
        return None


def verificar_alineaciones_automaticas(local, visitante, jugadores_objetivo):
    """
    1. Busca el Event_ID automáticamente.
    2. Consulta la alineación confirmada 30 min antes.
    3. Confirma si los jugadores objetivo están en el 11 titular.
    """
    # Paso 1: Obtener ID automático
    event_id = buscar_event_id_sofascore(local, visitante)
    if not event_id:
        return False, "NO_ID_ENCONTRADO"

    # Paso 2: Consultar alineación oficial en Sofascore
    url_lineups = f"https://api.sofascore.com/api/v3/event/{event_id}/lineups"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Referer": "https://www.sofascore.com/",
        "Accept": "application/json"
    }

    try:
        r = requests.get(url_lineups, headers=headers, timeout=10)
        if r.status_code != 200:
            return False, "ERROR_CONEXION"

        data = r.json()
        
        # Verificar si la liga/equipo ya confirmó la planilla oficial
        if not data.get("confirmed", False):
            print("[SOFASCORE] Las alineaciones aún no son oficiales.")
            return False, "NO_CONFIRMADO"

        # Extraer nombres de los 11 titulares
        titulares = []
        for equipo in ["home", "away"]:
            for p in data.get(equipo, {}).get("players", []):
                if not p.get("substitute", True):
                    titulares.append(p["player"]["name"].lower())

        # Paso 3: Validar que los jugadores analizados sean titulares
        for jugador in jugadores_objetivo:
            jugador_norm = jugador.lower().strip()
            es_titular = any(jugador_norm in t or t in jugador_norm for t in titulares)
            if not es_titular:
                print(f"[ALERTA] {jugador} ES SUPLENTE O NO FUE CONVOCADO.")
                return False, f"JUGADOR_SUPLENTE: {jugador}"

        print("[OK] Todos los jugadores analizados son TITULARES CONFIRMADOS.")
        return True, "TITULARES_OK"

    except Exception as e:
        print(f"[EXCEPCIÓN LINEUPS] {e}")
        return False, "ERROR_EXCEPCION"
