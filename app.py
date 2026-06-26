import threading

from fastapi import FastAPI
from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import signal
import main
import state

from soap import (
    obter_token,
    marcar_pendente
)

import time

app = FastAPI()

app.mount(
    "/static",
    StaticFiles(directory="static"),
    name="static"
)

templates = Jinja2Templates(
    directory="templates"
)

daemon_started = False


@app.on_event("startup")
def startup():

    global daemon_started

    if daemon_started:
        return

    daemon_started = True

    threading.Thread(
        target=main.main,
        daemon=True
    ).start()

    print("[WEB] Daemon iniciado")


@app.get("/", response_class=HTMLResponse)
def index(request: Request):

    return templates.TemplateResponse(
        "index.html",
        {"request": request}
    )


@app.get("/api/jobs")
def jobs():

    with state.lock:

        return list(
            state.jobs.values()
        )


@app.get("/api/history")
def history():

    with state.lock:

        return state.historico[-100:]


@app.get("/api/stats")
def stats():

    with state.lock:

        concluidos = sum(
            1
            for h in state.historico
            if h.get("resultado") == "Concluído"
        )

        erros = sum(
            1
            for h in state.historico
            if h.get("resultado") == "Erro"
        )

        return {
            "workers": main.MAX_WORKERS,
            "ativos": len(state.jobs),
            "concluidos": concluidos,
            "erros": erros
        }
        
@app.post(
    "/api/job/{media_id}/cancel"
)
def cancelar_job(media_id: str):

    with state.lock:

        proc = state.processos.get(
            media_id
        )

    if not proc:

        return {
            "ok": False,
            "erro": "Job não encontrado"
        }

    try:

        proc.kill()

    except Exception:
        pass

    try:

        token = obter_token(
            media_id
        )

        marcar_pendente(
            media_id,
            token
        )

    except Exception as ex:

        print(
            f"[SOAP] erro ao cancelar "
            f"{media_id}: {ex}"
        )

    with state.lock:

        state.processos.pop(
            media_id,
            None
        )

        state.jobs.pop(
            media_id,
            None
        )

        state.historico.append({

            "media_id": media_id,

            "resultado": "Cancelado",

            "horario": time.strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        })

    return {
        "ok": True
    }