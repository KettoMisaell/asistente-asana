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
