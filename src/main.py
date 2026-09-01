from fastapi import FastAPI

from src.audit.routes import router as audit_router
from src.notifications.routes import router as notifications_router
from src.projects.routes import router as projects_router


app = FastAPI()

app.include_router(audit_router)
app.include_router(notifications_router)
app.include_router(projects_router)
