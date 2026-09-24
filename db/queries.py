import sqlite3
import os
import unicodedata
from dotenv import load_dotenv

load_dotenv()
DB_PATH = os.getenv("DATABASE_PATH", "asana_data.db")

def normalizar_texto(texto):
    if not texto:
        return ""
    # Remover acentos (diacríticos) y pasar a minúsculas
    texto_norm = "".join(
        c for c in unicodedata.normalize("NFD", str(texto))
        if unicodedata.category(c) != "Mn"
    )
    return texto_norm.lower()

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.create_function("normalize", 1, normalizar_texto)
    conn.row_factory = sqlite3.Row
    return conn

def get_temporality_clause_positional(start_date=None, end_date=None, date_type="delivery"):
    """
    Retorna una tupla (sql_clause, params_list) para filtrar tareas por un rango de fechas.
    - date_type == "creation": se filtra por created_at.
    - date_type == "delivery" (o cualquier otro): se filtra por fecha_completada (concluidas) o fecha_vencimiento (pendientes),
      con fallbacks apropiados.
    """
    clauses = []
    params = []
    
    if not start_date and not end_date:
        return "", []
        
    if date_type == "creation":
        ref_date_expr = "created_at"
    else:
        # delivery/completion:
        # - completada = 1: fecha_completada, fallback fecha_vencimiento, fallback created_at
        # - completada = 0: fecha_vencimiento, fallback fecha_inicio, fallback created_at
        ref_date_expr = """
            CASE 
                WHEN completada = 1 THEN COALESCE(date(fecha_completada), date(fecha_vencimiento), date(created_at))
                ELSE COALESCE(date(fecha_vencimiento), date(fecha_inicio), date(created_at))
            END
        """
        
    if start_date:
        clauses.append(f"date({ref_date_expr}) >= date(?)")
        params.append(start_date)
        
    if end_date:
        clauses.append(f"date({ref_date_expr}) <= date(?)")
        params.append(end_date)
        
    return " AND ".join(clauses), params

def search_tasks_by_term(term, team=None, start_date=None, end_date=None, date_type="delivery"):
    """Busca tareas que contengan el término en el nombre, descripción o comentarios."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query_parts = ["(normalize(nombre_tarea) LIKE ? OR normalize(descripcion) LIKE ? OR normalize(comentarios_texto) LIKE ?)"]
    params = [f"%{normalizar_texto(term)}%", f"%{normalizar_texto(term)}%", f"%{normalizar_texto(term)}%"]
    
    if team:
        query_parts.append("normalize(equipo) LIKE ?")
        params.append(f"%{normalizar_texto(team)}%")
        
    date_clause, date_params = get_temporality_clause_positional(start_date, end_date, date_type)
    if date_clause:
        query_parts.append(date_clause)
        params.extend(date_params)
        
    query = "SELECT * FROM tareas WHERE " + " AND ".join(query_parts)
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_tasks_by_assignee(assignee_name, team=None, only_pending=True, start_date=None, end_date=None, date_type="delivery"):
    """Obtiene tareas asignadas a una persona específica."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query_parts = ["normalize(asignado) LIKE ?"]
    params = [f"%{normalizar_texto(assignee_name)}%"]
    
    if only_pending:
        query_parts.append("completada = 0")
        
    if team:
        query_parts.append("normalize(equipo) LIKE ?")
        params.append(f"%{normalizar_texto(team)}%")
        
    date_clause, date_params = get_temporality_clause_positional(start_date, end_date, date_type)
    if date_clause:
        query_parts.append(date_clause)
        params.extend(date_params)
        
    query = "SELECT * FROM tareas WHERE " + " AND ".join(query_parts)
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_tasks_by_project(project_name, only_pending=True, start_date=None, end_date=None, date_type="delivery"):
    """Obtiene tareas pertenecientes a un proyecto específico."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query_parts = ["normalize(proyecto_origen) LIKE ?"]
    params = [f"%{normalizar_texto(project_name)}%"]
    
    if only_pending:
        query_parts.append("completada = 0")
        
    date_clause, date_params = get_temporality_clause_positional(start_date, end_date, date_type)
    if date_clause:
        query_parts.append(date_clause)
        params.extend(date_params)
        
    query = "SELECT * FROM tareas WHERE " + " AND ".join(query_parts)
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_overdue_tasks(team=None, start_date=None, end_date=None, date_type="delivery"):
    """Obtiene las tareas vencidas y pendientes."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query_parts = ["atrasada = 1", "completada = 0"]
    params = []
    
    if team:
        query_parts.append("normalize(equipo) LIKE ?")
        params.append(f"%{normalizar_texto(team)}%")
        
    date_clause, date_params = get_temporality_clause_positional(start_date, end_date, date_type)
    if date_clause:
        query_parts.append(date_clause)
        params.extend(date_params)
        
    query = "SELECT * FROM tareas WHERE " + " AND ".join(query_parts)
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_inactive_tasks(days=7, team=None, start_date=None, end_date=None, date_type="delivery"):
    """Obtiene tareas pendientes que no han tenido movimiento en N días."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query_parts = ["dias_sin_movimiento >= ?", "completada = 0"]
    params = [days]
    
    if team:
        query_parts.append("normalize(equipo) LIKE ?")
        params.append(f"%{normalizar_texto(team)}%")
        
    date_clause, date_params = get_temporality_clause_positional(start_date, end_date, date_type)
    if date_clause:
        query_parts.append(date_clause)
        params.extend(date_params)
        
    query = "SELECT * FROM tareas WHERE " + " AND ".join(query_parts) + " ORDER BY dias_sin_movimiento DESC"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_strategic_tasks(team=None, start_date=None, end_date=None, date_type="delivery"):
    """Obtiene las tareas estratégicas (que contienen 'EE' o son marcadas como prioritarias) activas o recientemente actualizadas/completadas."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Trae tareas estratégicas que no están completadas, O que están completadas pero con actividad en los últimos 14 días (dias_sin_movimiento <= 14)
    query_parts = [
        "(nombre_tarea LIKE 'EE %' OR nombre_tarea LIKE '% EE %' OR etapa LIKE '%Crítica%')",
        "(completada = 0 OR (completada = 1 AND dias_sin_movimiento <= 14))"
    ]
    params = []
    
    if team:
        query_parts.append("normalize(equipo) LIKE ?")
        params.append(f"%{normalizar_texto(team)}%")
        
    date_clause, date_params = get_temporality_clause_positional(start_date, end_date, date_type)
    if date_clause:
        query_parts.append(date_clause)
        params.extend(date_params)
        
    query = "SELECT * FROM tareas WHERE " + " AND ".join(query_parts)
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_dashboard_metrics(team=None, start_date=None, end_date=None, date_type="delivery"):
    """Calcula y retorna las métricas agregadas para el dashboard general."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    where_parts = []
    params = []
    if team:
        where_parts.append("normalize(equipo) LIKE ?")
        params.append(f"%{normalizar_texto(team)}%")
        
    date_clause, date_params = get_temporality_clause_positional(start_date, end_date, date_type)
    if date_clause:
        where_parts.append(date_clause)
        params.extend(date_params)
        
    where_clause = "WHERE " + " AND ".join(where_parts) if where_parts else ""
    
    # Total de tareas
    cursor.execute(f"SELECT COUNT(*) FROM tareas {where_clause}", params)
    total = cursor.fetchone()[0]
    
    # Completadas
    completed_parts = ["completada = 1"]
    completed_params = []
    if team:
        completed_parts.append("normalize(equipo) LIKE ?")
        completed_params.append(f"%{normalizar_texto(team)}%")
    if date_clause:
        completed_parts.append(date_clause)
        completed_params.extend(date_params)
    completed_where = "WHERE " + " AND ".join(completed_parts)
    cursor.execute(f"SELECT COUNT(*) FROM tareas {completed_where}", completed_params)
    completadas = cursor.fetchone()[0]
    
    # Pendientes
    pending_parts = ["completada = 0"]
    pending_params = []
    if team:
        pending_parts.append("normalize(equipo) LIKE ?")
        pending_params.append(f"%{normalizar_texto(team)}%")
    if date_clause:
        pending_parts.append(date_clause)
        pending_params.extend(date_params)
    pending_where = "WHERE " + " AND ".join(pending_parts)
    cursor.execute(f"SELECT COUNT(*) FROM tareas {pending_where}", pending_params)
    pendientes = cursor.fetchone()[0]
    
    # Atrasadas (pendientes y vencidas)
    overdue_parts = ["atrasada = 1", "completada = 0"]
    overdue_params = []
    if team:
        overdue_parts.append("normalize(equipo) LIKE ?")
        overdue_params.append(f"%{normalizar_texto(team)}%")
    if date_clause:
        overdue_parts.append(date_clause)
        overdue_params.extend(date_params)
    overdue_where = "WHERE " + " AND ".join(overdue_parts)
    cursor.execute(f"SELECT COUNT(*) FROM tareas {overdue_where}", overdue_params)
    atrasadas = cursor.fetchone()[0]
    
    # Sin movimiento (> 7 días)
    inactive_parts = ["dias_sin_movimiento >= 7", "completada = 0"]
    inactive_params = []
    if team:
        inactive_parts.append("normalize(equipo) LIKE ?")
        inactive_params.append(f"%{normalizar_texto(team)}%")
    if date_clause:
        inactive_parts.append(date_clause)
        inactive_params.extend(date_params)
    inactive_where = "WHERE " + " AND ".join(inactive_parts)
    cursor.execute(f"SELECT COUNT(*) FROM tareas {inactive_where}", inactive_params)
    sin_movimiento = cursor.fetchone()[0]
    
    # Estratégicas (EE)
    ee_parts = ["(nombre_tarea LIKE 'EE %' OR nombre_tarea LIKE '% EE %')", "completada = 0"]
    ee_params = []
    if team:
        ee_parts.append("normalize(equipo) LIKE ?")
        ee_params.append(f"%{normalizar_texto(team)}%")
    if date_clause:
        ee_parts.append(date_clause)
        ee_params.extend(date_params)
    ee_where = "WHERE " + " AND ".join(ee_parts)
    cursor.execute(f"SELECT COUNT(*) FROM tareas {ee_where}", ee_params)
    estrategicas = cursor.fetchone()[0]
    
    # Estado por Proyecto (Top 10 proyectos con más tareas pendientes)
    project_parts = ["completada = 0"]
    project_params = []
    if team:
        project_parts.append("normalize(equipo) LIKE ?")
        project_params.append(f"%{normalizar_texto(team)}%")
    if date_clause:
        project_parts.append(date_clause)
        project_params.extend(date_params)
    project_where = "WHERE " + " AND ".join(project_parts)
    
    project_query = f"""
        SELECT proyecto_origen, COUNT(*) as pendientes_count 
        FROM tareas 
        {project_where}
        GROUP BY proyecto_origen 
        ORDER BY pendientes_count DESC 
        LIMIT 10
    """
    cursor.execute(project_query, project_params)
    proyectos = [dict(r) for r in cursor.fetchall()]
    
    # Estado por Responsable (Top 10 responsables con más pendientes)
    assignee_parts = ["completada = 0", "asignado IS NOT NULL"]
    assignee_params = []
    if team:
        assignee_parts.append("normalize(equipo) LIKE ?")
        assignee_params.append(f"%{normalizar_texto(team)}%")
    if date_clause:
        assignee_parts.append(date_clause)
        assignee_params.extend(date_params)
    assignee_where = "WHERE " + " AND ".join(assignee_parts)
    
    assignee_query = f"""
        SELECT asignado, COUNT(*) as pendientes_count 
        FROM tareas 
        {assignee_where}
        GROUP BY asignado 
        ORDER BY pendientes_count DESC 
        LIMIT 10
    """
    cursor.execute(assignee_query, assignee_params)
    responsables = [dict(r) for r in cursor.fetchall()]

    conn.close()
    
    return {
        "total_tareas": total,
        "completadas": completadas,
        "pendientes": pendientes,
        "atrasadas": atrasadas,
        "sin_movimiento_7d": sin_movimiento,
        "estrategicas_ee": estrategicas,
        "proyectos": proyectos,
        "responsables": responsables
    }

def get_task_by_gid(gid_tarea):
    """Obtiene una tarea por su identificador único (gid_tarea)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tareas WHERE gid_tarea = ?", (gid_tarea,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_all_teams():
    """Obtiene todos los equipos únicos de la base de datos local."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT equipo FROM tareas WHERE equipo IS NOT NULL AND equipo != ''")
    teams = [row[0] for row in cursor.fetchall() if row[0]]
    conn.close()
    return sorted(teams)

def get_teams_ee_summary(start_date=None, end_date=None, date_type="delivery"):
    """Calcula y retorna un resumen ejecutivo de entregables estratégicos (EE) por equipo, incluyendo vacíos."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Obtener todos los equipos configurados
    cursor.execute("SELECT gid_equipo, nombre_equipo FROM equipos")
    teams_list = [dict(row) for row in cursor.fetchall()]
    
    # Obtener todas las tareas de entregables estratégicos con filtro de fecha
    query_parts = ["(nombre_tarea LIKE 'EE %' OR nombre_tarea LIKE '% EE %')"]
    params = []
    
    date_clause, date_params = get_temporality_clause_positional(start_date, end_date, date_type)
    if date_clause:
        query_parts.append(date_clause)
        params.extend(date_params)
        
    query = "SELECT * FROM tareas WHERE " + " AND ".join(query_parts)
    cursor.execute(query, params)
    tareas = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    # Agrupar tareas por gid_equipo
    tareas_por_equipo = {}
    for t in tareas:
        gid_eq = t.get("gid_equipo")
        if gid_eq:
            if gid_eq not in tareas_por_equipo:
                tareas_por_equipo[gid_eq] = []
            tareas_por_equipo[gid_eq].append(t)
            
    result = []
    for team in teams_list:
        gid_eq = team["gid_equipo"]
        team_tareas = tareas_por_equipo.get(gid_eq, [])
        
        ee_totales = len(team_tareas)
        ee_activos = sum(1 for t in team_tareas if t.get("completada") == 0)
        ee_en_plazo = sum(1 for t in team_tareas if t.get("completada") == 0 and t.get("atrasada") == 0)
        ee_vencidos = sum(1 for t in team_tareas if t.get("completada") == 0 and t.get("atrasada") == 1)
        ee_actualizados_semana = sum(1 for t in team_tareas if t.get("dias_sin_movimiento") is not None and t.get("dias_sin_movimiento") <= 7)
        ee_completados = sum(1 for t in team_tareas if t.get("completada") == 1)
        
        # Calcular fichas incompletas usando la función unificada
        ee_completados_sin_ficha = 0
        ee_activos_sin_ficha = 0
        for t in team_tareas:
            scf, _ = calcular_completitud_tarea(t)
            if scf < 100:
                if t.get("completada") == 1:
                    ee_completados_sin_ficha += 1
                else:
                    ee_activos_sin_ficha += 1
                    
        result.append({
            "gid_equipo": gid_eq,
            "nombre_equipo": team["nombre_equipo"],
            "ee_totales": ee_totales,
            "ee_activos": ee_activos,
            "ee_en_plazo": ee_en_plazo,
            "ee_vencidos": ee_vencidos,
            "ee_actualizados_semana": ee_actualizados_semana,
            "ee_completados": ee_completados,
            "ee_completados_sin_ficha": ee_completados_sin_ficha,
            "ee_activos_sin_ficha": ee_activos_sin_ficha
        })
        
    return sorted(result, key=lambda x: x["nombre_equipo"])

# =====================================================================
# NUEVAS FUNCIONES DE APOYO PARA KRs E INTERVENCIONES
# =====================================================================

def registrar_intervencion(gid_tarea, canal, mensaje_enviado):
    """Inserta un nuevo registro de intervención para una tarea."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO intervenciones (gid_tarea, canal, mensaje_enviado)
        VALUES (?, ?, ?)
    """, (gid_tarea, canal, mensaje_enviado))
    conn.commit()
    conn.close()
    return True

def obtener_intervenciones_tarea(gid_tarea):
    """Obtiene el historial de intervenciones de una tarea."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM intervenciones 
        WHERE gid_tarea = ? 
        ORDER BY fecha_intervencion DESC
    """, (gid_tarea,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def calcular_completitud_tarea(t):
    """Calcula el Score de Completitud de Ficha (SCF) de 0 a 100."""
    detalles = {
        "asignado": bool(t.get("asignado")),
        "fecha_vencimiento": bool(t.get("fecha_vencimiento")),
        "descripcion": bool(t.get("descripcion") and len(t.get("descripcion").strip()) > 30),
        "evidencia": bool(t.get("fecha_ultimo_comentario") or (t.get("comentarios_texto") and len(t.get("comentarios_texto").strip()) > 10))
    }
    score = 0
    score += 25 if detalles["asignado"] else 0
    score += 25 if detalles["fecha_vencimiento"] else 0
    score += 25 if detalles["descripcion"] else 0
    score += 25 if detalles["evidencia"] else 0
    return score, detalles

def obtener_riesgo_tarea(t, scf=None):
    """Calcula la categoría de riesgo ponderado (IRP) de una tarea: 'Crítico', 'Medio', 'En Plazo'."""
    if t.get("completada") == 1:
        return "En Plazo"
        
    avance_num = 0
    avance_str = t.get("avance") or "0"
    try:
        avance_num = int(''.join(filter(str.isdigit, avance_str))) if any(c.isdigit() for c in avance_str) else 0
    except ValueError:
        pass
        
    # Crítico: vencida (atrasada) O con inactividad extrema (>= 14 días) y avance < 90%
    if t.get("atrasada") == 1:
        return "Crítico"
    if (t.get("dias_sin_movimiento") or 0) >= 14 and avance_num < 90:
        return "Crítico"
        
    # Medio: dias_sin_movimiento >= 7 OR SCF < 80%
    if scf is None:
        scf, _ = calcular_completitud_tarea(t)
    if (t.get("dias_sin_movimiento") or 0) >= 7 or scf < 80:
        return "Medio"
        
    return "En Plazo"

def get_weekly_update_metrics_by_team():
    """Calcula para cada equipo si cumple con el mínimo de 3 EEs actualizados semanalmente."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Obtener todas las tareas estratégicas activas o completadas recientemente (últimos 7 días)
    cursor.execute("""
        SELECT * FROM tareas 
        WHERE (nombre_tarea LIKE 'EE %' OR nombre_tarea LIKE '% EE %' OR etapa LIKE '%Crítica%')
        AND (completada = 0 OR (completada = 1 AND dias_sin_movimiento <= 7))
    """)
    tareas = [dict(r) for r in cursor.fetchall()]
    conn.close()
    
    # Agrupar por equipo
    equipos_data = {}
    for t in tareas:
        equipo = t.get("equipo") or "Sin Equipo"
        if equipo not in equipos_data:
            equipos_data[equipo] = {
                "ee_totales_pendientes": 0,
                "ee_actualizados_esta_semana": 0
            }
        
        # Solo se suman a pendientes si la tarea NO está completada
        if t.get("completada") == 0:
            equipos_data[equipo]["ee_totales_pendientes"] += 1
            
        # Se considera actualizado si tiene actividad o fue concluido en los últimos 7 días
        if (t.get("dias_sin_movimiento") or 0) <= 7:
            equipos_data[equipo]["ee_actualizados_esta_semana"] += 1
            
    # Formatear reporte de equipos y calcular cumplimiento
    equipos_list = []
    equipos_cumplen = 0
    
    for equipo, data in equipos_data.items():
        cumple = data["ee_actualizados_esta_semana"] >= 3
        if cumple:
            equipos_cumplen += 1
        equipos_list.append({
            "equipo": equipo,
            "ee_totales_pendientes": data["ee_totales_pendientes"],
            "ee_actualizados_esta_semana": data["ee_actualizados_esta_semana"],
            "cumple_minimo_3": cumple
        })
        
    total_equipos = len(equipos_list)
    porcentaje_cumplimiento = (equipos_cumplen / total_equipos * 100) if total_equipos > 0 else 100.0
    
    return {
        "porcentaje_cumplimiento": round(porcentaje_cumplimiento, 1),
        "equipos_cumplen": equipos_cumplen,
        "total_equipos": total_equipos,
        "equipos_detalle": sorted(equipos_list, key=lambda x: x["equipo"])
    }

def get_kr_dashboard_metrics(team=None, start_date=None, end_date=None, date_type="delivery"):
    """Calcula y consolida las métricas específicas de los KRs de seguimiento ejecutivo."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    where_clause = ""
    params = []
    if team:
        where_clause = "AND normalize(equipo) LIKE ?"
        params.append(f"%{normalizar_texto(team)}%")
        
    # 1. Obtener todas las tareas estratégicas activas de este equipo/organización
    query_parts = [
        "(nombre_tarea LIKE 'EE %' OR nombre_tarea LIKE '% EE %' OR etapa LIKE '%Crítica%')",
        "completada = 0"
    ]
    active_params = []
    if team:
        query_parts.append("normalize(equipo) LIKE ?")
        active_params.append(f"%{normalizar_texto(team)}%")
        
    date_clause, date_params = get_temporality_clause_positional(start_date, end_date, date_type)
    if date_clause:
        query_parts.append(date_clause)
        active_params.extend(date_params)
        
    query = "SELECT * FROM tareas WHERE " + " AND ".join(query_parts)
    cursor.execute(query, active_params)
    tareas_activas = [dict(r) for r in cursor.fetchall()]
    
    # 2. Obtener todas las intervenciones de la semana actual (últimos 7 días)
    cursor.execute("""
        SELECT gid_tarea, COUNT(*) as qty 
        FROM intervenciones 
        WHERE datetime(fecha_intervencion) >= datetime('now', '-7 days')
        GROUP BY gid_tarea
    """)
    intervenciones_recientes = {row["gid_tarea"]: row["qty"] for row in cursor.fetchall()}
    
    # 3. Calcular métricas por tarea
    total_ee = len(tareas_activas)
    completitud_acumulada = 0
    tareas_riesgo = 0
    tareas_riesgo_intervenidas = 0
    
    distribucion_riesgo = {"Crítico": 0, "Medio": 0, "En Plazo": 0}
    
    for t in tareas_activas:
        scf, _ = calcular_completitud_tarea(t)
        completitud_acumulada += scf
        
        riesgo = obtener_riesgo_tarea(t, scf)
        distribucion_riesgo[riesgo] += 1
        
        if riesgo in ["Crítico", "Medio"]:
            tareas_riesgo += 1
            if t["gid_tarea"] in intervenciones_recientes:
                tareas_riesgo_intervenidas += 1
                
    # 4. Calcular métricas concluidas sin reprogramaciones en el periodo (o últimos 90 días por defecto)
    concluidas_parts = [
        "completada = 1",
        "(nombre_tarea LIKE 'EE %' OR nombre_tarea LIKE '% EE %' OR etapa LIKE '%Crítica%')"
    ]
    concluidas_params = []
    if team:
        concluidas_parts.append("normalize(equipo) LIKE ?")
        concluidas_params.append(f"%{normalizar_texto(team)}%")
        
    if date_clause:
        concluidas_parts.append(date_clause)
        concluidas_params.extend(date_params)
    else:
        concluidas_parts.append("datetime(fecha_completada) >= datetime('now', '-90 days')")
        
    query_concluidas = f"""
        SELECT COUNT(*) as concluidas_total,
               SUM(CASE WHEN reprogramada = 0 THEN 1 ELSE 0 END) as sin_reprogramar
        FROM tareas
        WHERE {" AND ".join(concluidas_parts)}
    """
    cursor.execute(query_concluidas, concluidas_params)
    res_concluidas = cursor.fetchone()
    concluidas_total = res_concluidas["concluidas_total"] or 0
    sin_reprogramar = res_concluidas["sin_reprogramar"] or 0
    
    # Obtener entregables estratégicos activos que ya están vencidos y cuyo vencimiento cae en el periodo
    vencidos_parts = [
        "completada = 0",
        "atrasada = 1",
        "(nombre_tarea LIKE 'EE %' OR nombre_tarea LIKE '% EE %' OR etapa LIKE '%Crítica%')",
        "fecha_vencimiento IS NOT NULL"
    ]
    vencidos_params = []
    if team:
        vencidos_parts.append("normalize(equipo) LIKE ?")
        vencidos_params.append(f"%{normalizar_texto(team)}%")
        
    if date_clause:
        vencidos_parts.append(date_clause)
        vencidos_params.extend(date_params)
    else:
        vencidos_parts.append("datetime(fecha_vencimiento) >= datetime('now', '-90 days')")
        
    query_vencidos_activos = f"""
        SELECT COUNT(*) as vencidos_activos_total
        FROM tareas
        WHERE {" AND ".join(vencidos_parts)}
    """
    cursor.execute(query_vencidos_activos, vencidos_params)
    res_vencidos = cursor.fetchone()
    vencidos_activos = res_vencidos["vencidos_activos_total"] or 0
    
    denominador_total = concluidas_total + vencidos_activos
    porcentaje_ee_a_tiempo = (sin_reprogramar / denominador_total * 100) if denominador_total > 0 else 0.0
    
    conn.close()
    
    # Tasa de completitud promedio
    scf_promedio = (completitud_acumulada / total_ee) if total_ee > 0 else 100.0
    
    # Tasa de intervención en riesgo
    tasa_intervencion = (tareas_riesgo_intervenidas / tareas_riesgo * 100) if tareas_riesgo > 0 else 100.0
    
    # Obtener el cumplimiento semanal de equipos (Iniciativa 1)
    metrica_equipos = get_weekly_update_metrics_by_team()
    
    return {
        "iniciativa_1_equipos_compliance": metrica_equipos["porcentaje_cumplimiento"] if not team else (100.0 if (metrica_equipos["porcentaje_cumplimiento"] > 0) else 0.0),
        "iniciativa_1_equipos_detalle": metrica_equipos["equipos_detalle"],
        "iniciativa_2_completeness_score": round(scf_promedio, 1),
        "iniciativa_3_distribucion_riesgo": distribucion_riesgo,
        "iniciativa_3_total_riesgos": tareas_riesgo,
        "iniciativa_4_tasa_intervencion": round(tasa_intervencion, 1),
        "iniciativa_4_riesgos_intervenidos": tareas_riesgo_intervenidas,
        "kr_principal_ee_concluidos_total": concluidas_total,
        "kr_principal_ee_concluidos_sin_repro": sin_reprogramar,
        "kr_principal_ee_vencidos_activos": vencidos_activos,
        "kr_principal_porcentaje_a_tiempo": round(porcentaje_ee_a_tiempo, 1)
    }
