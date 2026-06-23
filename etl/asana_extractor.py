import os
import requests
import pandas as pd
from datetime import datetime
import time
from dotenv import load_dotenv
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed

# Cargar variables de entorno
load_dotenv()

TOKEN = os.getenv("ASANA_TOKEN")
DB_PATH = os.getenv("DATABASE_PATH", "asana_data.db")

if not TOKEN:
    raise ValueError("ASANA_TOKEN no encontrado en las variables de entorno (.env)")

headers = {
    "Authorization": f"Bearer {TOKEN}"
}

def safe_get(url, headers, params=None, retries=3):
    """
    Realiza una petición GET de forma segura, manejando límites de tasa (429)
    y reintentos automáticos para asegurar la estabilidad del ETL.
    """
    for attempt in range(retries):
        try:
            response = requests.get(url, headers=headers, params=params, timeout=15)
            if response.status_code == 200:
                return response
            elif response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", 2))
                print(f"[HTTP 429] Límite de tasa alcanzado. Esperando {retry_after}s...")
                time.sleep(retry_after)
            else:
                # Si es un error temporal del servidor (5xx), reintentar
                if response.status_code >= 500:
                    time.sleep(1)
                    continue
                return response
        except requests.exceptions.RequestException as e:
            if attempt == retries - 1:
                raise e
            time.sleep(1)
    return None

def parse_date(date_str):
    """Parsea de manera segura fechas provenientes de Asana (con o sin hora y zona horaria)."""
    if not date_str:
        return None
    try:
        if 'T' in date_str:
            # Reemplazar Z con +00:00 para que fromisoformat lo entienda en Python < 3.11
            clean_str = date_str.replace('Z', '+00:00')
            return datetime.fromisoformat(clean_str)
        return datetime.strptime(date_str, "%Y-%m-%d")
    except Exception:
        return None

def parse_custom_fields(custom_fields_list):
    """
    Analiza la lista de campos personalizados y extrae el avance y la etapa.
    Busca de manera flexible (insensible a mayúsculas) nombres clave.
    """
    avance = None
    etapa = None
    
    if not custom_fields_list:
        return avance, etapa

    for field in custom_fields_list:
        name = (field.get("name") or "").lower()
        display_value = field.get("display_value")
        enum_value = field.get("enum_value") or {}
        enum_name = enum_value.get("name")
        
        # Extraer avance (porcentaje o progreso)
        if any(kw in name for kw in ["avance", "progress", "progreso", "porcentaje", "completion"]):
            avance = display_value or enum_name or field.get("number_value")
            if avance is not None:
                avance = str(avance)
        
        # Extraer etapa (fase o estado)
        elif any(kw in name for kw in ["etapa", "stage", "estado", "fase", "status"]):
            etapa = display_value or enum_name
            if etapa is not None:
                etapa = str(etapa)
                
    return avance, etapa

def get_task_comments(task_gid, headers):
    """Obtiene los comentarios de una tarea."""
    url = f"https://app.asana.com/api/1.0/tasks/{task_gid}/stories"
    response = safe_get(url, headers=headers)
    if not response or response.status_code != 200:
        return []
    
    stories = response.json().get("data", [])
    comments = []
    
    for story in stories:
        if story.get("type") == "comment":
            comments.append({
                "autor": (story.get("created_by") or {}).get("name"),
                "fecha": story.get("created_at"),
                "comentario": story.get("text", "")
            })
            
    return comments

def get_team_projects(team_gid, headers):
    """Obtiene los proyectos asociados a un equipo."""
    url = f"https://app.asana.com/api/1.0/teams/{team_gid}/projects"
    response = safe_get(url, headers=headers)
    if not response or response.status_code != 200:
        return []
    return response.json().get("data", [])

def fetch_comments_parallel(task_gids, headers, max_workers=10):
    """
    Obtiene los comentarios de múltiples tareas en paralelo para optimizar el rendimiento.
    Usa un número moderado de hilos (max_workers=10) para evitar saturar el límite de tasa de Asana.
    """
    print(f"Descargando comentarios en paralelo para {len(task_gids)} tareas usando {max_workers} hilos...")
    results = {}
    
    def worker(gid):
        try:
            return gid, get_task_comments(gid, headers)
        except Exception as e:
            print(f"Error descargando comentarios para la tarea {gid}: {str(e)}")
            return gid, []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(worker, gid): gid for gid in task_gids}
        for future in as_completed(futures):
            gid, comments = future.result()
            results[gid] = comments
            
    return results

def get_tasks_by_teams(team_gids, headers, include_comments=True):
    """
    Extrae tareas de los equipos especificados, calcula métricas derivadas,
    normaliza campos y retorna un DataFrame con los registros listos.
    """
    if isinstance(team_gids, str):
        team_gids = [team_gids]
        
    todas_las_tareas = []
    
    for team_gid in team_gids:
        # Obtener nombre del equipo
        team_url = f"https://app.asana.com/api/1.0/teams/{team_gid}"
        team_response = safe_get(team_url, headers=headers)
        nombre_equipo = None
        if team_response and team_response.status_code == 200:
            nombre_equipo = team_response.json().get("data", {}).get("name")
            
        proyectos = get_team_projects(team_gid, headers)
        
        for proyecto in proyectos:
            project_gid = proyecto["gid"]
            offset = None
            
            while True:
                url = f"https://app.asana.com/api/1.0/projects/{project_gid}/tasks"
                params = {
                    "limit": 100,
                    "opt_fields": ",".join([
                        "gid",
                        "name",
                        "notes",
                        "completed",
                        "created_at",
                        "completed_at",
                        "modified_at",
                        "start_on",
                        "start_at",
                        "due_on",
                        "assignee.name",
                        "projects.name",
                        "custom_fields.name",
                        "custom_fields.display_value",
                        "custom_fields.enum_value.name",
                        "custom_fields.number_value"
                    ])
                }
                
                if offset:
                    params["offset"] = offset
                    
                response = safe_get(url, headers=headers, params=params)
                if not response or response.status_code != 200:
                    print(f"Error al obtener tareas para el proyecto {project_gid}")
                    break
                    
                data = response.json()
                tareas = data.get("data", [])
                
                for tarea in tareas:
                    # Asignado
                    asignado = (tarea.get("assignee") or {}).get("name")
                    
                    # Fechas básicas
                    fecha_vencimiento = tarea.get("due_on")
                    fecha_inicio = tarea.get("start_on") or tarea.get("start_at")
                    
                    # Cálculo de si está atrasada
                    atrasada = False
                    if fecha_vencimiento and not tarea.get("completed"):
                        due_date = parse_date(fecha_vencimiento)
                        if due_date:
                            if due_date.tzinfo is not None:
                                due_date = due_date.replace(tzinfo=None)
                            atrasada = due_date < datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                            
                    # Campos personalizados
                    custom_fields = tarea.get("custom_fields", [])
                    avance, etapa = parse_custom_fields(custom_fields)
                    
                    todas_las_tareas.append({
                        "gid_tarea": tarea.get("gid"),
                        "nombre_tarea": tarea.get("name"),
                        "descripcion": tarea.get("notes"),
                        "equipo": nombre_equipo,
                        "gid_equipo": team_gid,
                        "proyecto_origen": proyecto.get("name"),
                        "asignado": asignado,
                        "completada": bool(tarea.get("completed")),
                        "atrasada": bool(atrasada),
                        "fecha_inicio": fecha_inicio,
                        "fecha_vencimiento": fecha_vencimiento,
                        "avance": avance,
                        "etapa": etapa,
                        "created_at": tarea.get("created_at"),
                        "modified_at": tarea.get("modified_at")
                    })
                    
                next_page = data.get("next_page")
                if not next_page:
                    break
                offset = next_page.get("offset")
                
    if not todas_las_tareas:
        return pd.DataFrame()

    # Procesar comentarios en paralelo si es requerido
    comentarios_por_tarea = {}
    if include_comments:
        task_gids = [t["gid_tarea"] for t in todas_las_tareas]
        # Usamos 8 trabajadores para ser rápidos pero cautelosos con los límites de Asana
        comentarios_por_tarea = fetch_comments_parallel(task_gids, headers, max_workers=8)
        
    # Construcción final e integración de comentarios y métricas calculadas
    for tarea in todas_las_tareas:
        gid = tarea["gid_tarea"]
        comentarios = comentarios_por_tarea.get(gid, [])
        
        comentarios_list = []
        fecha_ultimo_comentario = None
        
        for c in comentarios:
            autor = c.get("autor") or "Anónimo"
            fecha_c = c.get("fecha")
            texto_c = (c.get("comentario") or "").strip()
            comentarios_list.append(f"[{autor}] ({fecha_c}): {texto_c}")
            
            c_date = parse_date(fecha_c)
            if c_date:
                if not fecha_ultimo_comentario or c_date > fecha_ultimo_comentario:
                    fecha_ultimo_comentario = c_date
                    
        comentarios_texto = "\n".join(comentarios_list) if comentarios_list else None
        
        # Determinar fecha de último movimiento para calcular 'dias_sin_movimiento'
        fecha_movimiento = fecha_ultimo_comentario
        if not fecha_movimiento:
            fecha_movimiento = parse_date(tarea.get("modified_at"))
        if not fecha_movimiento:
            fecha_movimiento = parse_date(tarea.get("created_at"))
            
        dias_sin_movimiento = 0
        if fecha_movimiento:
            if fecha_movimiento.tzinfo is not None:
                fecha_movimiento = fecha_movimiento.replace(tzinfo=None)
            dias_sin_movimiento = (datetime.now() - fecha_movimiento).days
            
        # Formatear la fecha del último comentario para base de datos
        fecha_ultimo_comentario_str = (
            fecha_ultimo_comentario.strftime("%Y-%m-%dT%H:%M:%SZ")
            if fecha_ultimo_comentario else None
        )
        
        # Guardar en el diccionario de la tarea
        tarea["comentarios_texto"] = comentarios_texto
        tarea["fecha_ultimo_comentario"] = fecha_ultimo_comentario_str
        tarea["dias_sin_movimiento"] = int(dias_sin_movimiento)
        
        # Limpiar llaves auxiliares que no van en la tabla de la base de datos
        tarea.pop("created_at", None)
        tarea.pop("modified_at", None)

    return pd.DataFrame(todas_las_tareas)

def save_tasks_to_db(df):
    """Inserta o actualiza las tareas recolectadas en la base de datos SQLite."""
    if df.empty:
        print("No hay tareas para guardar.")
        return
        
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    upsert_query = """
        INSERT INTO tareas (
            gid_tarea, nombre_tarea, descripcion, equipo, gid_equipo, 
            proyecto_origen, asignado, completada, atrasada, fecha_inicio, 
            fecha_vencimiento, avance, etapa, comentarios_texto, 
            fecha_ultimo_comentario, dias_sin_movimiento, last_updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(gid_tarea) DO UPDATE SET
            nombre_tarea=excluded.nombre_tarea,
            descripcion=excluded.descripcion,
            equipo=excluded.equipo,
            gid_equipo=excluded.gid_equipo,
            proyecto_origen=excluded.proyecto_origen,
            asignado=excluded.asignado,
            completada=excluded.completada,
            atrasada=excluded.atrasada,
            fecha_inicio=excluded.fecha_inicio,
            fecha_vencimiento=excluded.fecha_vencimiento,
            avance=excluded.avance,
            etapa=excluded.etapa,
            comentarios_texto=excluded.comentarios_texto,
            fecha_ultimo_comentario=excluded.fecha_ultimo_comentario,
            dias_sin_movimiento=excluded.dias_sin_movimiento,
            last_updated_at=CURRENT_TIMESTAMP
    """
    
    records = []
    for _, row in df.iterrows():
        records.append((
            row["gid_tarea"],
            row["nombre_tarea"],
            row["descripcion"],
            row["equipo"],
            row["gid_equipo"],
            row["proyecto_origen"],
            row["asignado"],
            int(row["completada"]),
            int(row["atrasada"]),
            row["fecha_inicio"],
            row["fecha_vencimiento"],
            row["avance"],
            row["etapa"],
            row["comentarios_texto"],
            row["fecha_ultimo_comentario"],
            int(row["dias_sin_movimiento"])
        ))
        
    cursor.executemany(upsert_query, records)
    conn.commit()
    conn.close()
    print(f"Se insertaron/actualizaron {len(records)} tareas en la base de datos.")

def run_etl():
    """Ejecuta el proceso completo de ETL."""
    print("Iniciando extracción optimizada y en paralelo desde Asana...")
    equipos_interes = [
        '1213716338728426', 
        '1213716338728417', 
        '1213716338728432', 
        '1213716338728439'
    ]
    
    start_time = time.time()
    try:
        df = get_tasks_by_teams(equipos_interes, headers)
        print(f"Extracción completada en {time.time() - start_time:.2f} segundos. Tareas encontradas: {len(df)}")
        save_tasks_to_db(df)
        print("Proceso ETL finalizado exitosamente.")
        return True
    except Exception as e:
        print(f"Error durante el proceso ETL: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    run_etl()
