import os
import requests
import pandas as pd
from datetime import datetime, timezone
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

def get_project_last_sync(project_gid):
    """Obtiene la fecha de la última sincronización exitosa de un proyecto."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT last_sync_time FROM etl_sync_state WHERE proyecto_gid = ?", (project_gid,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

def save_project_last_sync(project_gid, sync_time):
    """Guarda o actualiza la fecha de la última sincronización de un proyecto."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO etl_sync_state (proyecto_gid, last_sync_time)
        VALUES (?, ?)
        ON CONFLICT(proyecto_gid) DO UPDATE SET last_sync_time=excluded.last_sync_time
    """, (project_gid, sync_time))
    conn.commit()
    conn.close()

def delete_orphaned_projects_and_tasks(active_project_gids, active_team_gids):
    """
    Elimina los proyectos y tareas huérfanas en la base de datos local que ya no existen
    en Asana para los equipos configurados.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 1. Purga de proyectos en la base de datos local que ya no están activos en Asana
    cursor.execute("SELECT DISTINCT gid_proyecto FROM tareas WHERE gid_proyecto IS NOT NULL")
    db_projects = [row[0] for row in cursor.fetchall()]
    
    projects_to_delete = [p for p in db_projects if p not in active_project_gids]
    
    if projects_to_delete:
        print(f"Eliminando {len(projects_to_delete)} proyectos huérfanos de la base de datos local...")
        for p_gid in projects_to_delete:
            cursor.execute("DELETE FROM tareas WHERE gid_proyecto = ?", (p_gid,))
            cursor.execute("DELETE FROM etl_sync_state WHERE proyecto_gid = ?", (p_gid,))
            
    # 2. Por si acaso hay tareas de un equipo que ya no está mapeado
    if active_team_gids:
        placeholders = ",".join(["?"] * len(active_team_gids))
        cursor.execute(f"DELETE FROM tareas WHERE gid_equipo NOT IN ({placeholders})", active_team_gids)
        
    conn.commit()
    conn.close()

def delete_removed_tasks_from_project(project_gid, current_task_gids):
    """
    Elimina de la base de datos local aquellas tareas de un proyecto específico
    que ya no existen en Asana.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("SELECT gid_tarea FROM tareas WHERE gid_proyecto = ?", (project_gid,))
    local_gids = [row[0] for row in cursor.fetchall()]
    
    current_set = set(current_task_gids)
    gids_to_delete = [gid for gid in local_gids if gid not in current_set]
    
    if gids_to_delete:
        print(f"Limpiando {len(gids_to_delete)} tareas eliminadas en Asana para el proyecto {project_gid}...")
        for i in range(0, len(gids_to_delete), 500):
            batch = gids_to_delete[i:i+500]
            placeholders = ",".join(["?"] * len(batch))
            cursor.execute(f"DELETE FROM tareas WHERE gid_tarea IN ({placeholders})", batch)
            
    conn.commit()
    conn.close()

def get_project_task_gids(project_gid, headers):
    """
    Obtiene rápidamente una lista de todos los GIDs de tareas activas de un proyecto.
    Esta petición es ultraligera ya que solo pide el campo 'gid'.
    """
    gids = []
    offset = None
    while True:
        url = f"https://app.asana.com/api/1.0/projects/{project_gid}/tasks"
        params = {
            "limit": 100,
            "opt_fields": "gid"
        }
        if offset:
            params["offset"] = offset
            
        response = safe_get(url, headers=headers, params=params)
        if not response or response.status_code != 200:
            break
            
        data = response.json()
        for tarea in data.get("data", []):
            if tarea.get("gid"):
                gids.append(tarea["gid"])
                
        next_page = data.get("next_page")
        if not next_page:
            break
        offset = next_page.get("offset")
        
    return gids

def get_tasks_by_teams(team_gids, headers, include_comments=True):
    """
    Extrae tareas de los equipos especificados, calcula métricas derivadas,
    normaliza campos y retorna un DataFrame con los registros listos.
    Aplica una lógica híbrida (incremental/completo) por proyecto.
    """
    if isinstance(team_gids, str):
        team_gids = [team_gids]
        
    todas_las_tareas = []
    active_project_gids = []
    
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
            active_project_gids.append(project_gid)
            
            # Obtener estado de sincronización anterior
            last_sync_time = get_project_last_sync(project_gid)
            current_run_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            
            offset = None
            project_tasks_success = True
            project_tasks_fetched = 0
            
            print(f"Procesando proyecto: {proyecto.get('name')} ({project_gid}) | Sincronización anterior: {last_sync_time or 'Ninguna (Sync Completa)'}")
            
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
                
                # Si ya se sincronizó antes, pedir solo las tareas creadas/modificadas desde entonces
                if last_sync_time:
                    params["modified_since"] = last_sync_time
                
                if offset:
                    params["offset"] = offset
                    
                response = safe_get(url, headers=headers, params=params)
                if not response or response.status_code != 200:
                    print(f"Error al obtener tareas para el proyecto {project_gid}. Se omitirá la actualización de estado para este proyecto.")
                    project_tasks_success = False
                    break
                    
                data = response.json()
                tareas = data.get("data", [])
                project_tasks_fetched += len(tareas)
                
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
                        "gid_proyecto": project_gid,
                        "asignado": asignado,
                        "completada": bool(tarea.get("completed")),
                        "atrasada": bool(atrasada),
                        "fecha_inicio": fecha_inicio,
                        "fecha_vencimiento": fecha_vencimiento,
                        "fecha_completada": tarea.get("completed_at"),
                        "avance": avance,
                        "etapa": etapa,
                        "created_at": tarea.get("created_at"),
                        "modified_at": tarea.get("modified_at")
                    })
                    
                next_page = data.get("next_page")
                if not next_page:
                    break
                offset = next_page.get("offset")
            
            # Si el fetch de tareas del proyecto fue exitoso, actualizamos estado y purgamos eliminadas
            if project_tasks_success:
                print(f"Proyecto {proyecto.get('name')}: {project_tasks_fetched} tareas nuevas/modificadas detectadas.")
                save_project_last_sync(project_gid, current_run_time)
                
                # Obtener GIDs actuales de tareas en Asana y purgar las locales que falten
                current_task_gids = get_project_task_gids(project_gid, headers)
                delete_removed_tasks_from_project(project_gid, current_task_gids)
                
    # Eliminar proyectos de nuestra base de datos local que ya no existan en Asana para los equipos configurados
    delete_orphaned_projects_and_tasks(active_project_gids, team_gids)
                
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
        
        # Ya NO limpiamos creadas_at ni modified_at para poder guardarlas en la base de datos

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
            proyecto_origen, gid_proyecto, asignado, completada, atrasada, fecha_inicio, 
            fecha_vencimiento, fecha_completada, avance, etapa, comentarios_texto, 
            fecha_ultimo_comentario, dias_sin_movimiento, created_at, modified_at,
            fecha_vencimiento_original, reprogramada, last_updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, CURRENT_TIMESTAMP)
        ON CONFLICT(gid_tarea) DO UPDATE SET
            nombre_tarea=excluded.nombre_tarea,
            descripcion=excluded.descripcion,
            equipo=excluded.equipo,
            gid_equipo=excluded.gid_equipo,
            proyecto_origen=excluded.proyecto_origen,
            gid_proyecto=excluded.gid_proyecto,
            asignado=excluded.asignado,
            completada=excluded.completada,
            atrasada=excluded.atrasada,
            fecha_inicio=excluded.fecha_inicio,
            fecha_vencimiento=excluded.fecha_vencimiento,
            fecha_completada=excluded.fecha_completada,
            avance=excluded.avance,
            etapa=excluded.etapa,
            comentarios_texto=excluded.comentarios_texto,
            fecha_ultimo_comentario=excluded.fecha_ultimo_comentario,
            dias_sin_movimiento=excluded.dias_sin_movimiento,
            created_at=excluded.created_at,
            modified_at=excluded.modified_at,
            fecha_vencimiento_original=COALESCE(tareas.fecha_vencimiento_original, excluded.fecha_vencimiento_original),
            reprogramada=CASE 
                WHEN (tareas.fecha_vencimiento_original IS NOT NULL 
                      AND excluded.fecha_vencimiento IS NOT NULL 
                      AND tareas.fecha_vencimiento_original != excluded.fecha_vencimiento) THEN 1 
                ELSE tareas.reprogramada 
            END,
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
            row["gid_proyecto"],
            row["asignado"],
            int(row["completada"]),
            int(row["atrasada"]),
            row["fecha_inicio"],
            row["fecha_vencimiento"],
            row["fecha_completada"],
            row["avance"],
            row["etapa"],
            row["comentarios_texto"],
            row["fecha_ultimo_comentario"],
            int(row["dias_sin_movimiento"]),
            row["created_at"],
            row["modified_at"],
            row["fecha_vencimiento"]  # Servirá como fecha_vencimiento_original en el INSERT inicial
        ))
        
    cursor.executemany(upsert_query, records)
    conn.commit()
    conn.close()
    print(f"Se insertaron/actualizaron {len(records)} tareas en la base de datos.")

def run_etl():
    """Ejecuta el proceso completo de ETL."""
    print("Iniciando extracción optimizada y en paralelo desde Asana...")
    
    # Obtener equipos desde variables de entorno con fallback
    teams_env = os.getenv("ASANA_TEAMS")
    if teams_env:
        equipos_interes = [t.strip() for t in teams_env.split(",") if t.strip()]
    else:
        equipos_interes = [
            '1213716338728426', 
            '1213716338728417', 
            '1213716338728432', 
            '1213716338728439'
        ]
    
    start_time = time.time()
    try:
        df = get_tasks_by_teams(equipos_interes, headers)
        print(f"Extracción completada en {time.time() - start_time:.2f} segundos. Tareas encontradas en esta corrida: {len(df)}")
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
