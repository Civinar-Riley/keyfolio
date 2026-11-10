"""FastAPI 应用装配：路由挂载、静态托管、定时任务生命周期。"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import db, paths
from .routers import auth_routes, backup, channels, dashboard, models, quickadd, settings, templates
from .scheduler import run_loop

log = logging.getLogger("keyfolio")

db.init(paths.DB_PATH)


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(run_loop())
    log.info("Keyfolio 服务就绪：http://%s:%d", paths.HOST, paths.PORT)
    if paths.HOST in ("0.0.0.0", "::"):
        log.info("监听所有网卡：局域网内可访问，请确保主密码强度足够")
    yield
    task.cancel()


app = FastAPI(title="Keyfolio", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

app.include_router(auth_routes.router)
app.include_router(channels.router)
app.include_router(models.router)
app.include_router(dashboard.router)
app.include_router(templates.router)
app.include_router(backup.router)
app.include_router(quickadd.router)
app.include_router(settings.router)


@app.get("/api/health")
def health():
    from . import auth

    return {"ok": True, "app": "keyfolio", **auth.status()}


app.mount("/", StaticFiles(directory=str(paths.STATIC_DIR), html=True), name="static")
