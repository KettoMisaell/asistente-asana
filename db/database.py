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
            created_at TEXT,
            modified_at TEXT,
            fecha_vencimiento_original TEXT,
            reprogramada BOOLEAN DEFAULT 0,
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

    # Intentar agregar la columna created_at de forma dinámica si la tabla ya existía
    try:
        cursor.execute("ALTER TABLE tareas ADD COLUMN created_at TEXT")
    except sqlite3.OperationalError:
        pass

    # Intentar agregar la columna modified_at de forma dinámica si la tabla ya existía
    try:
        cursor.execute("ALTER TABLE tareas ADD COLUMN modified_at TEXT")
    except sqlite3.OperationalError:
        pass

    # Intentar agregar la columna fecha_vencimiento_original de forma dinámica si la tabla ya existía
    try:
        cursor.execute("ALTER TABLE tareas ADD COLUMN fecha_vencimiento_original TEXT")
    except sqlite3.OperationalError:
        pass

    # Intentar agregar la columna reprogramada de forma dinámica si la tabla ya existía
    try:
        cursor.execute("ALTER TABLE tareas ADD COLUMN reprogramada BOOLEAN DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    # Crear tabla de estados de sincronización de proyectos
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS etl_sync_state (
            proyecto_gid TEXT PRIMARY KEY,
            last_sync_time TEXT
        )
    """)

    # Crear tabla de intervenciones de tareas en riesgo
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS intervenciones (
            id_intervencion INTEGER PRIMARY KEY AUTOINCREMENT,
            gid_tarea TEXT,
            canal TEXT,
            mensaje_enviado TEXT,
            fecha_intervencion DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(gid_tarea) REFERENCES tareas(gid_tarea)
        )
    """)

    # Crear tabla de equipos configurados
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS equipos (
            gid_equipo TEXT PRIMARY KEY,
            nombre_equipo TEXT,
            last_sync_time TEXT
        )
    """)
    
    # Crear índices para acelerar búsquedas deterministas de la IA
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_intervenciones_gid_tarea ON intervenciones(gid_tarea)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tareas_equipo ON tareas(equipo)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tareas_asignado ON tareas(asignado)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tareas_completada ON tareas(completada)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tareas_fecha_vencimiento ON tareas(fecha_vencimiento)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tareas_gid_proyecto ON tareas(gid_proyecto)")
    
    # Insertar equipos semilla si la tabla está vacía
    cursor.execute("SELECT COUNT(*) FROM equipos")
    if cursor.fetchone()[0] == 0:
        seed_teams = [
            ('1213716338728426', 'Acceso a internet'),
            ('1213716338728417', 'Confianza Ciudadana'),
            ('1213716338728432', 'Infraestructura digital'),
            ('1213716338728439', 'Trabajo predecible')
        ]
        cursor.executemany("INSERT INTO equipos (gid_equipo, nombre_equipo) VALUES (?, ?)", seed_teams)
        
    conn.commit()
    conn.close()
    print(f"Base de datos inicializada en {DB_PATH}")

if __name__ == "__main__":
    init_db()
