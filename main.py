import os
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
import uvicorn

from db.queries import (
    get_dashboard_metrics,
    get_overdue_tasks,
    get_inactive_tasks,
    get_strategic_tasks,
    search_tasks_by_term,
    get_task_by_gid,
    get_all_teams
)
from etl.asana_extractor import run_etl
from ai.engine import ejecutar_consulta_chat, generar_reporte_semanal, generar_insight_tarea

load_dotenv()

app = FastAPI(
    title="Asistente Asana Executive",
    description="Capa de inteligencia ejecutiva sobre la información estructurada de Asana"
)

# Servir archivos estáticos e index.html
# Creamos las carpetas si no existen
os.makedirs("static/css", exist_ok=True)
os.makedirs("static/js", exist_ok=True)
os.makedirs("templates", exist_ok=True)

# Montar estáticos
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", response_class=HTMLResponse)
def read_root():
    template_path = os.path.join("templates", "index.html")
    if not os.path.exists(template_path):
        raise HTTPException(status_code=404, detail="index.html no encontrado en templates")
    with open(template_path, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

# --- ENDPOINTS API ---

@app.get("/api/metrics")
def api_metrics(team: str = Query(None, description="Filtrar métricas por equipo")):
    return get_dashboard_metrics(team)

@app.get("/api/tasks/overdue")
def api_overdue(team: str = Query(None, description="Filtrar tareas por equipo")):
    return get_overdue_tasks(team)

@app.get("/api/tasks/inactive")
def api_inactive(
    days: int = Query(7, description="Días de inactividad mínimos"),
    team: str = Query(None, description="Filtrar por equipo")
):
    return get_inactive_tasks(days, team)

@app.get("/api/tasks/strategic")
def api_strategic(team: str = Query(None, description="Filtrar por equipo")):
    return get_strategic_tasks(team)

@app.get("/api/tasks/search")
def api_search(
    q: str = Query(..., description="Término de búsqueda"),
    team: str = Query(None, description="Filtrar por equipo")
):
    if len(q.strip()) < 3:
        return []
    return search_tasks_by_term(q, team)

@app.post("/api/sync")
def api_sync():
    """Ejecuta el proceso de sincronización (ETL) bajo demanda."""
    success = run_etl()
    if not success:
        raise HTTPException(status_code=500, detail="Error durante la sincronización con Asana.")
    return {"status": "success", "message": "Sincronización completada con éxito."}

@app.post("/api/chat")
def api_chat(payload: dict):
    """
    Motor de Inteligencia interactivo (Fase 2).
    Conecta al modelo Gemini con Function Calling para resolver consultas del Director.
    """
    mensaje_usuario = payload.get("message", "").strip()
    team = payload.get("team")
    
    if not mensaje_usuario:
        return {"response": "Por favor escribe una consulta para poder ayudarte."}
        
    respuesta = ejecutar_consulta_chat(mensaje_usuario, team)
    return {"response": respuesta}

@app.get("/api/report")
def api_report(team: str = Query(None, description="Filtrar reporte estratégico por equipo")):
    """Genera el reporte ejecutivo semanal proactivo de tareas EE."""
    reporte = generar_reporte_semanal(team)
    return {"reporte": reporte}

@app.get("/api/tasks/{gid}/insight")
def api_task_insight(gid: str):
    """Genera un análisis ejecutivo proactivo (insight) para una sola tarea estratégica."""
    tarea = get_task_by_gid(gid)
    if not tarea:
        raise HTTPException(status_code=404, detail="Tarea estratégica no encontrada en la base de datos local.")
    insight = generar_insight_tarea(tarea)
    return {"insight": insight}

@app.get("/api/teams")
def api_teams():
    """Retorna la lista de equipos reales existentes en la base de datos."""
    return get_all_teams()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    print(f"Iniciando servidor FastAPI en puerto {port}...")
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
