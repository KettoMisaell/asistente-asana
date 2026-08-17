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

def search_tasks_by_term(term, team=None):
    """Busca tareas que contengan el término en el nombre, descripción o comentarios."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = """
        SELECT * FROM tareas 
        WHERE (normalize(nombre_tarea) LIKE ? OR normalize(descripcion) LIKE ? OR normalize(comentarios_texto) LIKE ?)
    """
    params = [f"%{normalizar_texto(term)}%", f"%{normalizar_texto(term)}%", f"%{normalizar_texto(term)}%"]
    
    if team:
        query += " AND normalize(equipo) LIKE ?"
        params.append(f"%{normalizar_texto(team)}%")
        
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_tasks_by_assignee(assignee_name, team=None, only_pending=True):
    """Obtiene tareas asignadas a una persona específica."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = "SELECT * FROM tareas WHERE normalize(asignado) LIKE ?"
    params = [f"%{normalizar_texto(assignee_name)}%"]
    
    if only_pending:
        query += " AND completada = 0"
        
    if team:
        query += " AND normalize(equipo) LIKE ?"
        params.append(f"%{normalizar_texto(team)}%")
        
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_tasks_by_project(project_name, only_pending=True):
    """Obtiene tareas pertenecientes a un proyecto específico."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = "SELECT * FROM tareas WHERE normalize(proyecto_origen) LIKE ?"
    params = [f"%{normalizar_texto(project_name)}%"]
    
    if only_pending:
        query += " AND completada = 0"
        
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_overdue_tasks(team=None):
    """Obtiene las tareas vencidas y pendientes."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = "SELECT * FROM tareas WHERE atrasada = 1 AND completada = 0"
    params = []
    
    if team:
        query += " AND normalize(equipo) LIKE ?"
        params.append(f"%{normalizar_texto(team)}%")
        
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_inactive_tasks(days=7, team=None):
    """Obtiene tareas pendientes que no han tenido movimiento en N días."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = "SELECT * FROM tareas WHERE dias_sin_movimiento >= ? AND completada = 0"
    params = [days]
    
    if team:
        query += " AND normalize(equipo) LIKE ?"
        params.append(f"%{normalizar_texto(team)}%")
        
    query += " ORDER BY dias_sin_movimiento DESC"
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_strategic_tasks(team=None):
    """Obtiene las tareas estratégicas (que contienen 'EE' o son marcadas como prioritarias) activas o recientemente actualizadas/completadas."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Trae tareas estratégicas que no están completadas, O que están completadas pero con actividad en los últimos 14 días (dias_sin_movimiento <= 14)
    query = """
        SELECT * FROM tareas 
        WHERE (nombre_tarea LIKE 'EE %' OR nombre_tarea LIKE '% EE %' OR etapa LIKE '%Crítica%')
        AND (completada = 0 OR (completada = 1 AND dias_sin_movimiento <= 14))
    """
    params = []
    
    if team:
        query += " AND normalize(equipo) LIKE ?"
        params.append(f"%{normalizar_texto(team)}%")
        
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_dashboard_metrics(team=None):
    """Calcula y retorna las métricas agregadas para el dashboard general."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    where_clause = ""
    params = []
    if team:
        where_clause = "WHERE normalize(equipo) LIKE ?"
        params.append(f"%{normalizar_texto(team)}%")
        
    # Total de tareas
    cursor.execute(f"SELECT COUNT(*) FROM tareas {where_clause}", params)
    total = cursor.fetchone()[0]
    
    # Completadas
    completed_where = f"WHERE completada = 1" if not team else f"WHERE completada = 1 AND normalize(equipo) LIKE ?"
    cursor.execute(f"SELECT COUNT(*) FROM tareas {completed_where}", params)
    completadas = cursor.fetchone()[0]
    
    # Pendientes
    pending_where = f"WHERE completada = 0" if not team else f"WHERE completada = 0 AND normalize(equipo) LIKE ?"
    cursor.execute(f"SELECT COUNT(*) FROM tareas {pending_where}", params)
    pendientes = cursor.fetchone()[0]
    
    # Atrasadas (pendientes y vencidas)
    overdue_where = f"WHERE atrasada = 1 AND completada = 0" if not team else f"WHERE atrasada = 1 AND completada = 0 AND normalize(equipo) LIKE ?"
    cursor.execute(f"SELECT COUNT(*) FROM tareas {overdue_where}", params)
    atrasadas = cursor.fetchone()[0]
    
    # Sin movimiento (> 7 días)
    inactive_where = f"WHERE dias_sin_movimiento >= 7 AND completada = 0" if not team else f"WHERE dias_sin_movimiento >= 7 AND completada = 0 AND normalize(equipo) LIKE ?"
    cursor.execute(f"SELECT COUNT(*) FROM tareas {inactive_where}", params)
    sin_movimiento = cursor.fetchone()[0]
    
    # Estratégicas (EE)
    ee_where = (
        f"WHERE (nombre_tarea LIKE 'EE %' OR nombre_tarea LIKE '% EE %') AND completada = 0"
        if not team else 
        f"WHERE (nombre_tarea LIKE 'EE %' OR nombre_tarea LIKE '% EE %') AND completada = 0 AND normalize(equipo) LIKE ?"
    )
    cursor.execute(f"SELECT COUNT(*) FROM tareas {ee_where}", params)
    estrategicas = cursor.fetchone()[0]
    
    # Estado por Proyecto (Top 10 proyectos con más tareas pendientes)
    project_query = f"""
        SELECT proyecto_origen, COUNT(*) as pendientes_count 
        FROM tareas 
        {where_clause if team else 'WHERE completada = 0'} 
        {"AND completada = 0" if team else ""}
        GROUP BY proyecto_origen 
        ORDER BY pendientes_count DESC 
        LIMIT 10
    """
    cursor.execute(project_query, params)
    proyectos = [dict(r) for r in cursor.fetchall()]
    
    # Estado por Responsable (Top 10 responsables con más pendientes)
    assignee_query = f"""
        SELECT asignado, COUNT(*) as pendientes_count 
        FROM tareas 
        {where_clause if team else 'WHERE completada = 0 AND asignado IS NOT NULL'} 
        {"AND completada = 0 AND asignado IS NOT NULL" if team else ""}
        GROUP BY asignado 
        ORDER BY pendientes_count DESC 
        LIMIT 10
    """
    cursor.execute(assignee_query, params)
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

def get_teams_ee_summary():
    """Calcula y retorna un resumen ejecutivo de entregables estratégicos (EE) por equipo, incluyendo vacíos."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = """
        SELECT 
            e.gid_equipo,
            e.nombre_equipo,
            COUNT(t.gid_tarea) AS ee_totales,
            SUM(CASE WHEN t.completada = 0 THEN 1 ELSE 0 END) AS ee_activos,
            SUM(CASE WHEN t.completada = 0 AND t.atrasada = 0 THEN 1 ELSE 0 END) AS ee_en_plazo,
            SUM(CASE WHEN t.completada = 0 AND t.atrasada = 1 THEN 1 ELSE 0 END) AS ee_vencidos,
            SUM(CASE WHEN t.dias_sin_movimiento <= 7 THEN 1 ELSE 0 END) AS ee_actualizados_semana
        FROM equipos e
        LEFT JOIN tareas t ON e.gid_equipo = t.gid_equipo 
            AND (t.nombre_tarea LIKE 'EE %' OR t.nombre_tarea LIKE '% EE %')
        GROUP BY e.gid_equipo, e.nombre_equipo
        ORDER BY e.nombre_equipo ASC
    """
    
    cursor.execute(query)
    rows = cursor.fetchall()
    conn.close()
    
    result = []
    for row in rows:
        item = dict(row)
        for key in ['ee_totales', 'ee_activos', 'ee_en_plazo', 'ee_vencidos', 'ee_actualizados_semana']:
            item[key] = item[key] or 0
        result.append(item)
        
    return result

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

def get_kr_dashboard_metrics(team=None):
    """Calcula y consolida las métricas específicas de los KRs de seguimiento ejecutivo."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    where_clause = ""
    params = []
    if team:
        where_clause = "AND normalize(equipo) LIKE ?"
        params.append(f"%{normalizar_texto(team)}%")
        
    # 1. Obtener todas las tareas estratégicas activas de este equipo/organización
    query = f"""
        SELECT * FROM tareas 
        WHERE (nombre_tarea LIKE 'EE %' OR nombre_tarea LIKE '% EE %' OR etapa LIKE '%Crítica%')
        AND completada = 0 {where_clause}
    """
    cursor.execute(query, params)
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
                
    # 4. Calcular métricas concluidas sin reprogramaciones en los últimos 3 meses
    # (KR principal: de 10% a 50%)
    query_concluidas = f"""
        SELECT COUNT(*) as concluidas_total,
               SUM(CASE WHEN reprogramada = 0 THEN 1 ELSE 0 END) as sin_reprogramar
        FROM tareas
        WHERE completada = 1 
        AND datetime(fecha_completada) >= datetime('now', '-90 days')
        {where_clause}
    """
    cursor.execute(query_concluidas, params)
    res_concluidas = cursor.fetchone()
    concluidas_total = res_concluidas["concluidas_total"] or 0
    sin_reprogramar = res_concluidas["sin_reprogramar"] or 0
    
    porcentaje_ee_a_tiempo = (sin_reprogramar / concluidas_total * 100) if concluidas_total > 0 else 0.0
    
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
        "kr_principal_porcentaje_a_tiempo": round(porcentaje_ee_a_tiempo, 1)
    }
