from app.routers.agenda import router as agenda_router
from app.routers.create import router as create_router
from app.routers.events import router as events_router
from app.routers.fallback import router as fallback_router
from app.routers.group import router as group_router
from app.routers.mine import router as mine_router
from app.routers.start import router as start_router


def assemble_root_router() -> Router:
    root = Router(name="root")
    root.include_router(start_router)
    root.include_router(create_router)     # FSM — до общих
    root.include_router(mine_router)       # FSM edit — до общих
    root.include_router(agenda_router)
    root.include_router(events_router)
    root.include_router(group_router)
    root.include_router(fallback_router)
    return root