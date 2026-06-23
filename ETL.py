import requests
import pandas as pd
from datetime import datetime
import os 

TOKEN = os.getenv("ASANA_TOKEN")

headers = {
    "Authorization": f"Bearer {TOKEN}"
}

url = "https://app.asana.com/api/1.0/workspaces"

response = requests.get(url, headers=headers)

data = response.json()

def get_task_comments(task_gid, headers):

    url = f"https://app.asana.com/api/1.0/tasks/{task_gid}/stories"

    response = requests.get(url, headers=headers)

    if response.status_code != 200:
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


# =========================================================
# OBTENER PROYECTOS DE UN EQUIPO
# =========================================================

def get_team_projects(team_gid, headers):

    url = f"https://app.asana.com/api/1.0/teams/{team_gid}/projects"

    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        return []

    return response.json().get("data", [])


# =========================================================
# FUNCIÓN PRINCIPAL
# =========================================================

def get_tasks_by_teams(
    team_gids,
    headers,
    nombre_asignado=None,
    include_comments=True,
    completed_since=None
):

    if isinstance(team_gids, str):
        team_gids = [team_gids]

    todas_las_tareas = []

    # =====================================================
    # RECORRER EQUIPOS
    # =====================================================

    for team_gid in team_gids:

        # Obtener nombre del equipo
        team_url = f"https://app.asana.com/api/1.0/teams/{team_gid}"

        team_response = requests.get(
            team_url,
            headers=headers
        )

        nombre_equipo = None

        if team_response.status_code == 200:
            nombre_equipo = (
                team_response.json()
                .get("data", {})
                .get("name")
            )

        # Obtener proyectos del equipo
        proyectos = get_team_projects(
            team_gid,
            headers
        )

        # =================================================
        # RECORRER PROYECTOS
        # =================================================

        for proyecto in proyectos:

            project_gid = proyecto["gid"]

            offset = None

            while True:

                url = (
                    f"https://app.asana.com/api/1.0/projects/"
                    f"{project_gid}/tasks"
                )

                params = {
                    "limit": 100,
                    "opt_fields": ",".join([
                        "gid",
                        "name",
                        "notes",
                        "completed",
                        "created_at",
                        "completed_at",
                        "start_on",
                        "start_at",
                        "due_on",
                        "assignee.name",
                        "projects.name",
                        "custom_fields.name",
                        "custom_fields.display_value",
                        "custom_fields.enum_value.name"
                    ])
                }

                if completed_since:
                    params["completed_since"] = completed_since

                if offset:
                    params["offset"] = offset

                response = requests.get(
                    url,
                    headers=headers,
                    params=params
                )

                data = response.json()

                tareas = data.get("data", [])

                for tarea in tareas:

                    asignado = (
                        tarea.get("assignee", {}) or {}
                    ).get("name")

                    # =============================
                    # FILTRO OPCIONAL DE ASIGNADO
                    # =============================

                    if (
                        nombre_asignado
                        and asignado != nombre_asignado
                    ):
                        continue

                    # =============================
                    # FECHA VENCIMIENTO
                    # =============================

                    fecha_vencimiento = tarea.get("due_on")

                    atrasada = False

                    if (
                        fecha_vencimiento
                        and not tarea.get("completed")
                    ):

                        atrasada = (
                            pd.to_datetime(fecha_vencimiento)
                            <
                            pd.Timestamp.today().normalize()
                        )

                    # =============================
                    # PROYECTOS
                    # =============================

                    nombres_proyectos = [
                        p.get("name")
                        for p in tarea.get("projects", [])
                    ]

                    # =============================
                    # FECHA INICIO
                    # =============================

                    fecha_inicio = (
                        tarea.get("start_on")
                        or tarea.get("start_at")
                    )

                    # =============================
                    # COMENTARIOS
                    # =============================

                    comentarios = []

                    if include_comments:

                        comentarios = get_task_comments(
                            tarea["gid"],
                            headers
                        )

                    # =============================
                    # REGISTRO FINAL
                    # =============================

                    todas_las_tareas.append({

                        "gid_tarea":
                            tarea.get("gid"),

                        "nombre_tarea":
                            tarea.get("name"),

                        "descripcion":
                            tarea.get("notes"),

                        "equipo":
                            nombre_equipo,

                        "gid_equipo":
                            team_gid,

                        "proyecto_origen":
                            proyecto.get("name"),

                        "completada":
                            tarea.get("completed"),

                        "atrasada":
                            atrasada,

                        "fecha_inicio":
                            fecha_inicio,

                        "fecha_vencimiento":
                            fecha_vencimiento,

                        "asignado":
                            asignado,

                        "proyectos":
                            nombres_proyectos,

                        "comentarios":
                            comentarios,

                        "campos_personalizados":
                            tarea.get(
                                "custom_fields",
                                []
                            )
                    })

                next_page = data.get("next_page")

                if not next_page:
                    break

                offset = next_page.get("offset")

    return pd.DataFrame(todas_las_tareas)

df_tareas = get_tasks_by_teams(
    team_gids=['1213716338728426', '1213716338728417', '1213716338728432', '1213716338728439'],
    headers=headers
)