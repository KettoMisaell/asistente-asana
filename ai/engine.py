import os
from datetime import datetime
import google.generativeai as genai
from dotenv import load_dotenv

from db.queries import (
    search_tasks_by_term,
    get_tasks_by_assignee,
    get_tasks_by_project,
    get_overdue_tasks,
    get_inactive_tasks,
    get_strategic_tasks
)

# Cargar variables de entorno
load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")
MODEL_NAME = "gemini-2.5-flash"  # Modelo rápido, económico y excelente para RAG y Tool Use

# Configurar API Key si es válida
is_ai_configured = False
if API_KEY and API_KEY != "YOUR_GEMINI_API_KEY_HERE":
    genai.configure(api_key=API_KEY)
    is_ai_configured = True
else:
    print("\n⚠️ ADVERTENCIA: GEMINI_API_KEY no está configurada o contiene el placeholder en el archivo .env.")
    print("El Motor de Inteligencia (IA) correrá en modo Mock (de simulación) hasta que se configure una clave real.\n")


# =====================================================================
# FUNCIONES AUXILIARES (HELPERS)
# =====================================================================

def obtener_ultimos_comentarios(comentarios_texto, n=2):
    """
    Parsea el string de comentarios agrupados y retorna los últimos n comentarios completos.
    Mantiene el nombre del autor, la fecha y el comentario multilinea intactos.
    """
    if not comentarios_texto:
        return "Ninguno"
    
    lineas = comentarios_texto.splitlines()
    comentarios = []
    comentario_actual = []
    
    for linea in lineas:
        # Detectar el inicio de un nuevo comentario, ej: [Juan] (2026-06-15T10:00:00Z): ...
        if linea.startswith("[") and "]" in linea and "(" in linea and "):" in linea:
            if comentario_actual:
                comentarios.append("\n".join(comentario_actual))
                comentario_actual = []
            comentario_actual.append(linea)
        else:
            if comentario_actual:
                comentario_actual.append(linea)
            elif linea.strip():
                # Por si la primera línea por alguna razón extraña no coincide con el patrón
                comentarios.append(linea)
                
    if comentario_actual:
        comentarios.append("\n".join(comentario_actual))
        
    ultimos = comentarios[-n:]
    return "\n---\n".join(ultimos) if ultimos else "Ninguno"


# =====================================================================
# HERRAMIENTAS (TOOLS) DETERMINISTAS EXPUESTAS A GEMINI
# Los docstrings son metadatos que Gemini lee para decidir qué llamar.
# =====================================================================

def buscar_tareas(termino: str, equipo: str = None) -> list:
    """
    Busca tareas en la base de datos local que coincidan con un término de búsqueda.
    El término se busca en el nombre de la tarea, su descripción o los comentarios.
    
    Args:
        termino: El texto, palabra clave o término a buscar (ej: "IEBEM", "escuelas", "ciberseguridad").
        equipo: Opcional. Filtra para buscar únicamente en este equipo (ej: "Dirección", "Operaciones", "Desarrollo", "Soporte").
        
    Returns:
        Una lista de tareas con toda su información estructurada.
    """
    print(f"[IA Tool Use] Buscando tareas por término: '{termino}' (Equipo: {equipo})")
    return search_tasks_by_term(termino, team=equipo)

def obtener_tareas_por_asignado(responsable: str, equipo: str = None) -> list:
    """
    Obtiene todas las tareas pendientes asignadas a un responsable específico en la base de datos local.
    
    Args:
        responsable: Nombre o correo del responsable asignado (ej: "geobdz@gmail.com", "César", "Misael").
        equipo: Opcional. Filtra para buscar únicamente dentro de este equipo.
        
    Returns:
        Una lista de tareas pendientes asignadas a la persona.
    """
    print(f"[IA Tool Use] Obteniendo tareas para asignado: '{responsable}' (Equipo: {equipo})")
    return get_tasks_by_assignee(responsable, team=equipo, only_pending=True)

def obtener_tareas_por_proyecto(nombre_proyecto: str) -> list:
    """
    Obtiene todas las tareas pendientes asociadas a un proyecto de origen específico.
    
    Args:
        nombre_proyecto: Nombre del proyecto en Asana (ej: 'Implementación "La Tierra Que Nos Une"').
        
    Returns:
        Una lista de tareas pendientes pertenecientes a ese proyecto.
    """
    print(f"[IA Tool Use] Obteniendo tareas para el proyecto: '{nombre_proyecto}'")
    return get_tasks_by_project(nombre_proyecto, only_pending=True)

def obtener_tareas_vencidas(equipo: str = None) -> list:
    """
    Obtiene todas las tareas pendientes que ya se encuentran vencidas (atrasadas) en la base de datos local.
    
    Args:
        equipo: Opcional. Filtra las tareas vencidas de un equipo específico.
        
    Returns:
        Una lista de tareas vencidas and pendientes.
    """
    print(f"[IA Tool Use] Obteniendo tareas vencidas (Equipo: {equipo})")
    return get_overdue_tasks(team=equipo)

def obtener_tareas_inactivas(dias: int = 7, equipo: str = None) -> list:
    """
    Obtiene las tareas pendientes que no han registrado movimiento (comentarios ni modificaciones) en N días.
    
    Args:
        dias: Número mínimo de días de inactividad (por defecto 7).
        equipo: Opcional. Filtra para buscar únicamente en este equipo.
        
    Returns:
        Una lista de tareas sin movimiento ordenadas de mayor a menor inactividad.
    """
    print(f"[IA Tool Use] Obteniendo tareas inactivas por >= {dias} días (Equipo: {equipo})")
    return get_inactive_tasks(days=dias, team=equipo)

def obtener_tareas_estrategicas(equipo: str = None) -> list:
    """
    Obtiene las tareas consideradas estratégicas en la base de datos local (comienzan con 'EE' o etapa 'Crítica').
    
    Args:
        equipo: Opcional. Filtra las tareas estratégicas de un equipo específico.
        
    Returns:
        Una lista de tareas estratégicas pendientes.
    """
    print(f"[IA Tool Use] Obteniendo tareas estratégicas 'EE' (Equipo: {equipo})")
    return get_strategic_tasks(team=equipo)


# Lista de herramientas disponibles para Gemini
HERRAMIENTAS_IA = [
    buscar_tareas,
    obtener_tareas_por_asignado,
    obtener_tareas_por_proyecto,
    obtener_tareas_vencidas,
    obtener_tareas_inactivas,
    obtener_tareas_estrategicas
]


# =====================================================================
# CASO DE USO 1: CONSULTA EJECUTIVA EN CHAT (CON TOOL-USE)
# =====================================================================

def ejecutar_consulta_chat(mensaje_usuario: str, equipo_contexto: str = None) -> str:
    """
    Procesa una pregunta del usuario en el chat.
    Utiliza Gemini con Function Calling (Tool Use) automático para consultar la base de datos SQLite
    y redactar una respuesta sumamente profesional, ejecutiva y objetiva.
    """
    if not is_ai_configured:
        # Modo simulación (Mock) por falta de API Key
        print("[IA Mock] GEMINI_API_KEY no configurada. Simulando respuesta...")
        return (
            f"⚠️ **[Modo Simulación]** Para obtener una respuesta real de Gemini, configura tu `GEMINI_API_KEY` en el archivo `.env`.\n\n"
            f"Si la clave estuviera configurada, Gemini habría analizado tu pregunta: \"*{mensaje_usuario}*\", "
            f"ejecutado búsquedas sobre el equipo *'{equipo_contexto or 'Todos'}'* usando las herramientas SQL deterministas de la base de datos "
            f"y redactado un reporte ejecutivo sin inventar datos."
        )

    # Formatear la fecha actual de forma sumamente ejecutiva y amigable en español
    dias_semana = {
        "Monday": "lunes", "Tuesday": "martes", "Wednesday": "miércoles",
        "Thursday": "jueves", "Friday": "viernes", "Saturday": "sábado", "Sunday": "domingo"
    }
    meses = {
        1: "enero", 2: "febrero", 3: "marzo", 4: "abril", 5: "mayo", 6: "junio",
        7: "julio", 8: "agosto", 9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre"
    }
    ahora = datetime.now()
    dia_sem = dias_semana.get(ahora.strftime("%A"), ahora.strftime("%A"))
    mes = meses.get(ahora.month, ahora.strftime("%B"))
    fecha_formateada = f"{dia_sem}, {ahora.day} de {mes} de {ahora.year}"
    hora_formateada = ahora.strftime("%H:%M")

    # Definir el contexto del sistema y reglas de comportamiento del asistente
    system_instruction = (
        "Eres un Asistente Ejecutivo de Inteligencia para la Dirección de la organización.\n"
        "Tu única fuente de verdad es la base de datos local de Asana, a la que tienes acceso estricto a través de tus herramientas (funciones de Python).\n\n"
        f"CONTEXTO TEMPORAL ACTUAL:\n"
        f"La fecha de hoy en el servidor es: {fecha_formateada}.\n"
        f"La hora actual es: {hora_formateada}.\n"
        "Usa esta fecha para calcular días de retraso, antigüedad de comentarios, inactividad o proximidad de vencimientos de forma exacta y coherente.\n\n"
        "REGLAS DE OBLIGATORIO CUMPLIMIENTO:\n"
        "1. Para responder cualquier pregunta del usuario sobre tareas, proyectos, responsables o estado, DEBES llamar a tus herramientas. No respondas desde tu conocimiento general.\n"
        f"2. El usuario actualmente está viendo/filtrando el equipo: '{equipo_contexto or 'Todos los Equipos'}'. "
        "Cuando llames a funciones que acepten el parámetro 'equipo', usa este valor por defecto para afinar la búsqueda, a menos que el usuario indique buscar globalmente o en otro equipo en su pregunta.\n"
        "3. Formula las llamadas a funciones de manera inteligente. Si el usuario pregunta por 'escuelas de IEBEM', llama a `buscar_tareas(termino='IEBEM')` o `buscar_tareas(termino='escuelas')`.\n"
        "4. Si la consulta no arroja resultados, puedes intentar ampliar la búsqueda buscando un sinónimo o término más corto relevante, o informar de forma transparente que no se encontraron coincidencias en el caché local de Asana.\n"
        "5. Redacta tus respuestas con un tono sumamente ejecutivo, profesional, directo y al grano. El Director no tiene tiempo de leer relleno. Usa Markdown (negritas, viñetas).\n"
        "6. Identifica proactivamente riesgos (ej. tareas vencidas o con muchos días sin movimiento) y bloqueos evidentes basándote en la fecha de vencimiento y el último comentario registrado.\n"
        "7. NUNCA inventes tareas, nombres de personas, fechas o comentarios que no existan en los resultados devueltos por tus herramientas.\n"
        "8. IMPORTANTE: No expongas identificadores técnicos como el GID de Asana en tus respuestas bajo ningún motivo, ya que son confusos para la Dirección. Refiérete a las tareas únicamente por su Nombre o Título."
    )

    try:
        # Inicializar modelo con herramientas
        model = genai.GenerativeModel(
            model_name=MODEL_NAME,
            tools=HERRAMIENTAS_IA,
            system_instruction=system_instruction
        )
        
        # Iniciar chat con resolución automática de llamadas a funciones (Automatic Function Calling)
        chat = model.start_chat(enable_automatic_function_calling=True)
        
        # Enviar el mensaje del usuario
        response = chat.send_message(mensaje_usuario)
        return response.text
        
    except Exception as e:
        print(f"Error en el motor de IA (Chat): {str(e)}")
        return f"❌ **Error en el Motor de Inteligencia (Gemini):** {str(e)}"


# =====================================================================
# CASO DE USO 2: MONITOREO PROACTIVO / REPORTE AUTOMÁTICO SEMANAL
# =====================================================================

def generar_reporte_semanal(equipo_contexto: str = None) -> str:
    """
    Genera un Reporte Semanal de Monitoreo Proactivo basado únicamente en las tareas estratégicas ('EE').
    Extrae la información determinista de la DB y se la inyecta a Gemini con un formato estructurado.
    """
    if not is_ai_configured:
        return (
            f"⚠️ **[Modo Simulación]** Configura tu `GEMINI_API_KEY` en el archivo `.env` para generar el reporte semanal proactivo real de la IA.\n\n"
            f"El reporte automático filtraría únicamente las tareas que contienen prefijo **'EE'** (Estratégicas) o etapa **'Crítica'** "
            f"para el equipo **'{equipo_contexto or 'Todos'}'**, detectaría bloqueos mediante los días sin movimiento e hitos en el último comentario, "
            f"y generaría alertas, riesgos, recomendaciones y personas clave a contactar."
        )

    # 1. Obtener datos deterministas de tareas estratégicas (EE)
    print(f"[IA Reporte] Obteniendo tareas estratégicas para el reporte semanal. Equipo: {equipo_contexto}")
    tareas_ee = get_strategic_tasks(team=equipo_contexto)
    
    if not tareas_ee:
        return f"### Reporte Semanal de Monitoreo Proactivo\n\nNo se encontraron tareas estratégicas (**EE** o etapa **Crítica**) pendientes para el equipo *'{equipo_contexto or 'Todos los Equipos'}'* en la sincronización actual."

    # Formatear la fecha de hoy para el reporte
    dias_semana = {
        "Monday": "lunes", "Tuesday": "martes", "Wednesday": "miércoles",
        "Thursday": "jueves", "Friday": "viernes", "Saturday": "sábado", "Sunday": "domingo"
    }
    meses = {
        1: "enero", 2: "febrero", 3: "marzo", 4: "abril", 5: "mayo", 6: "junio",
        7: "julio", 8: "agosto", 9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre"
    }
    ahora = datetime.now()
    dia_sem = dias_semana.get(ahora.strftime("%A"), ahora.strftime("%A"))
    mes = meses.get(ahora.month, ahora.strftime("%B"))
    fecha_hoy = f"{dia_sem}, {ahora.day} de {mes} de {ahora.year}"

    # 2. Formatear las tareas de forma sumamente compacta y estructurada para el prompt de Gemini
    bloque_tareas = []
    for i, t in enumerate(tareas_ee, 1):
        # Truncar la descripción a un tamaño razonable para optimizar contexto
        desc = t['descripcion'] or 'No especificada'
        if len(desc) > 400:
            desc = desc[:400] + "..."
            
        # Obtener comentarios formateados agrupando líneas
        ultimos_comentarios = obtener_ultimos_comentarios(t['comentarios_texto'], n=2)
        
        # NOTA: Omitimos por completo el GID para evitar que se exponga al Director General
        bloque_tareas.append(
            f"Tarea {i}:\n"
            f"  - Nombre: {t['nombre_tarea']}\n"
            f"  - Proyecto: {t['proyecto_origen']}\n"
            f"  - Equipo: {t['equipo']}\n"
            f"  - Asignado: {t['asignado'] or 'Sin Asignar'}\n"
            f"  - Estado: {'Pendiente Vencida (Atrasada)' if t['atrasada'] else 'Pendiente en Plazo'}\n"
            f"  - Fecha Inicio: {t['fecha_inicio'] or 'No especificada'}\n"
            f"  - Fecha Vencimiento: {t['fecha_vencimiento'] or 'No especificada'}\n"
            f"  - Avance: {t['avance'] or '0.0%'}\n"
            f"  - Etapa: {t['etapa'] or 'No especificada'}\n"
            f"  - Días Sin Movimiento: {t['dias_sin_movimiento']}\n"
            f"  - Descripción: {desc}\n"
            f"  - Últimos Comentarios:\n{ultimos_comentarios}\n"
        )
    
    texto_tareas = "\n".join(bloque_tareas)

    # 3. Prompt de sistema enfocado en análisis de riesgos ejecutivos
    prompt = (
        f"Actúa como un Analista Ejecutivo de Riesgos y Gestión de Proyectos de Alto Nivel.\n"
        f"Tu tarea es elaborar el **Reporte Semanal de Monitoreo Proactivo** de las tareas estratégicas para el Titular de la Dependencia.\n\n"
        f"La fecha actual de generación del reporte es: {fecha_hoy}.\n\n"
        f"A continuación tienes la lista completa de tareas estratégicas activas bajo el alcance del equipo: '{equipo_contexto or 'Todos los Equipos'}':\n"
        f"```\n{texto_tareas}\n```\n\n"
        "INSTRUCCIONES DE REDACCIÓN:\n"
        "1. Tu reporte debe ser extremadamente analítico, directo y libre de formalidades redundantes o introducciones largas, además lee el campo de descripción de la tarea para poder entender mejor las implicaciones de la tarea.\n"
        "2. Estructura el reporte exactamente en las siguientes secciones ejecutivas usando Markdown profesional:\n\n"
        "### 🚨 ALERTAS CRÍTICAS Y TAREAS VENCIDAS\n"
        "- Identifica las tareas estratégicas que están vencidas (atrasadas) o con inactividad extrema (>14 días). Lista un punto por tarea detallando el responsable, los días de retraso e implicación inmediata.\n\n"
        "### 📈 AVANCES Y ESTADO DE TAREAS ESTRATÉGICAS (ACTIVAS Y RECIENTES)\n"
        "- Detalla de forma ejecutiva el estado y avances de todas las tareas estratégicas activas (incluso las que están en tiempo) y aquellas completadas recientemente.\n"
        "- **Regla de Oro sobre Descripciones:** Apaláncate a fondo de la 'Descripción' de cada tarea para inferir su alcance, avance real e implicación del entregable con total precisión. Si una tarea estratégica tiene descripción 'No especificada', señálalo explícitamente como un riesgo de alineación, falta de claridad técnica o riesgo de ejecución.\n"
        "- Analiza con cuidado el contenido de los 'Últimos Comentarios' para diagnosticar hitos alcanzados, progreso real, o bloqueos técnicos (ej. si están esperando aprobación o respuesta de un tercero).\n\n"
        "### 👤 ACCIONES Y PERSONAS CLAVE A CONTACTAR\n"
        "- Genera una tabla de acción inmediata con las columnas: | Responsable | Tarea Crítica | Acción Recomendada / Qué Solicitar | para que el Director sepa exactamente con quién hablar y qué fecha compromiso solicitar para destrabar el avance. Recuerda no incluir campos técnicos ni GIDs.\n\n"
        "### 💡 RECOMENDACIONES EJECUTIVAS\n"
        "- Conclusiones breves o recomendaciones a nivel directivo sobre la salud general de este frente estratégico.\n\n"
        "REGLAS DE OBLIGATORIO CUMPLIMIENTO:\n"
        "- NUNCA expongas identificadores internos (como GIDs, hashes o números técnicos de tarea) en el reporte final para el Director General. Mantén el texto limpio y de alto nivel.\n"
        "- No alucines ni inventes tareas, personas, comentarios ni datos. Basas todo tu análisis rigurosamente en la lista provista arriba."
    )

    try:
        # Guardar el prompt en un archivo de depuración local para verificar lo enviado a la IA
        try:
            with open("ultimo_prompt_generado.txt", "w", encoding="utf-8") as f:
                f.write(prompt)
            print("[IA Reporte Debug] Prompt guardado con éxito en 'ultimo_prompt_generado.txt' para su inspección.")
        except Exception as log_err:
            print(f"[IA Reporte Debug] No se pudo guardar el archivo de depuración: {str(log_err)}")

        model = genai.GenerativeModel(model_name=MODEL_NAME)
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print(f"Error en el motor de IA (Reporte): {str(e)}")
        return f"❌ **Error al generar el reporte semanal con Gemini:** {str(e)}"
