import sqlite3
import os
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

DB_PATH = os.getenv("DATABASE_PATH", "asana_data.db")

def get_db_connection():
    """Retorna una conexión a la base de datos SQLite."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Crea la tabla de tareas con los campos necesarios si no existe."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Crear tabla de tareas
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tareas (
            gid_tarea TEXT PRIMARY KEY,
            nombre_tarea TEXT,
            descripcion TEXT,
            equipo TEXT,
            gid_equipo TEXT,
            proyecto_origen TEXT,
            gid_proyecto TEXT,
            asignado TEXT,
            completada BOOLEAN,
            atrasada BOOLEAN,
            fecha_inicio TEXT,
            fecha_vencimiento TEXT,
            fecha_completada TEXT,
            avance TEXT,
            etapa TEXT,
            comentarios_texto TEXT,
            fecha_ultimo_comentario TEXT,
            dias_sin_movimiento INTEGER,
            last_updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Intentar agregar la columna gid_proyecto de forma dinámica si la tabla ya existía
    try:
        cursor.execute("ALTER TABLE tareas ADD COLUMN gid_proyecto TEXT")
    except sqlite3.OperationalError:
        # La columna ya existe, ignoramos el error
        pass

    # Intentar agregar la columna fecha_completada de forma dinámica si la tabla ya existía
    try:
        cursor.execute("ALTER TABLE tareas ADD COLUMN fecha_completada TEXT")
    except sqlite3.OperationalError:
        # La columna ya existe, ignoramos el error
        pass

    # Crear tabla de estados de sincronización de proyectos
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS etl_sync_state (
            proyecto_gid TEXT PRIMARY KEY,
            last_sync_time TEXT
        )
    """)
    
    # Crear índices para acelerar búsquedas deterministas de la IA
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tareas_equipo ON tareas(equipo)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tareas_asignado ON tareas(asignado)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tareas_completada ON tareas(completada)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tareas_fecha_vencimiento ON tareas(fecha_vencimiento)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tareas_gid_proyecto ON tareas(gid_proyecto)")
    
    conn.commit()
    conn.close()
    print(f"Base de datos inicializada en {DB_PATH}")

if __name__ == "__main__":
    init_db()
