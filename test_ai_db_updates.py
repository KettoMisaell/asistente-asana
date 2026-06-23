import unittest
import sqlite3
import os
from db.queries import normalizar_texto, get_db_connection
from ai.engine import obtener_ultimos_comentarios

class TestAIDBUpdates(unittest.TestCase):
    
    def test_normalizar_texto(self):
        # Probar remoción de acentos y conversión a minúsculas
        self.assertEqual(normalizar_texto("César"), "cesar")
        self.assertEqual(normalizar_texto("Dirección Técnico-Operativa"), "direccion tecnico-operativa")
        self.assertEqual(normalizar_texto("ÁÉÍÓÚáéíóú Ññ"), "aeiouaeiou nn")
        self.assertEqual(normalizar_texto(""), "")
        self.assertEqual(normalizar_texto(None), "")
        
    def test_sqlite_normalize_function(self):
        # Probar la integración de la función 'normalize' con una base de datos SQLite en memoria
        conn = sqlite3.connect(":memory:")
        conn.create_function("normalize", 1, normalizar_texto)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("CREATE TABLE test_table (id INTEGER, nombre TEXT)")
        cursor.execute("INSERT INTO test_table VALUES (1, 'César Hipólito')")
        cursor.execute("INSERT INTO test_table VALUES (2, 'Dirección General')")
        
        # Probar búsqueda por coincidencia parcial insensible a acentos y mayúsculas
        cursor.execute("SELECT id FROM test_table WHERE normalize(nombre) LIKE ?", [f"%{normalizar_texto('cesar')}%"])
        rows = cursor.fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], 1)
        
        cursor.execute("SELECT id FROM test_table WHERE normalize(nombre) LIKE ?", [f"%{normalizar_texto('direccion')}%"])
        rows = cursor.fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], 2)
        
        conn.close()
        
    def test_obtener_ultimos_comentarios(self):
        # Caso 1: Comentarios vacíos
        self.assertEqual(obtener_ultimos_comentarios(None), "Ninguno")
        self.assertEqual(obtener_ultimos_comentarios(""), "Ninguno")
        
        # Caso 2: Comentarios de una sola línea
        comentarios_1 = "[Juan] (2026-06-15T10:00:00Z): Comentario 1\n[Pedro] (2026-06-16T12:00:00Z): Comentario 2"
        resultado_1 = obtener_ultimos_comentarios(comentarios_1, n=1)
        self.assertEqual(resultado_1, "[Pedro] (2026-06-16T12:00:00Z): Comentario 2")
        
        # Caso 3: Comentarios multilinea
        comentarios_2 = (
            "[Juan] (2026-06-15T10:00:00Z): Comentario de Juan\n"
            "con varias lineas de texto\n"
            "interesantes.\n"
            "[Pedro] (2026-06-16T12:00:00Z): Comentario de Pedro\n"
            "que termina aqui."
        )
        
        # Obtener el último comentario completo
        resultado_2_n1 = obtener_ultimos_comentarios(comentarios_2, n=1)
        self.assertEqual(resultado_2_n1, "[Pedro] (2026-06-16T12:00:00Z): Comentario de Pedro\nque termina aqui.")
        
        # Obtener los últimos dos comentarios completos
        resultado_2_n2 = obtener_ultimos_comentarios(comentarios_2, n=2)
        esperado_2_n2 = (
            "[Juan] (2026-06-15T10:00:00Z): Comentario de Juan\ncon varias lineas de texto\ninteresantes.\n"
            "---\n"
            "[Pedro] (2026-06-16T12:00:00Z): Comentario de Pedro\nque termina aqui."
        )
        self.assertEqual(resultado_2_n2, esperado_2_n2)

    def test_get_task_by_gid_none(self):
        from db.queries import get_task_by_gid
        # Probar que retorna None para una tarea inexistente
        self.assertIsNone(get_task_by_gid("nonexistent_gid_12345"))

    def test_generar_insight_tarea_simulation(self):
        from ai.engine import generar_insight_tarea
        # Probar la simulación o el retorno de insight de tarea bajo un mock dictionary
        mock_task = {
            "gid_tarea": "123",
            "nombre_tarea": "EE Compilar reportes",
            "proyecto_origen": "Estrategia",
            "equipo": "Dirección",
            "asignado": "Misael",
            "atrasada": 1,
            "fecha_vencimiento": "2026-06-20",
            "avance": "50%",
            "dias_sin_movimiento": 8,
            "descripcion": "Reunir la información de todos los planteles.",
            "comentarios_texto": "Esperando aprobación del Director"
        }
        
        insight = generar_insight_tarea(mock_task)
        # Debe contener información clave de la tarea
        self.assertIsNotNone(insight)
        self.assertTrue("EE Compilar reportes" in insight or "DIAGNÓSTICO" in insight)

if __name__ == "__main__":
    unittest.main()
