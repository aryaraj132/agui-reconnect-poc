from fastapi import APIRouter, HTTPException

from stream_reconnection_demo.core.history import thread_store

router = APIRouter(prefix="/api/v1")


@router.get("/threads")
async def list_threads(agent_type: str | None = None):
    return thread_store.list_threads(agent_type=agent_type)


@router.get("/threads/{thread_id}")
async def get_thread(thread_id: str):
    thread = thread_store.get_thread(thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    return thread


@router.get("/threads/{thread_id}/messages")
async def get_thread_messages(thread_id: str):
    thread = thread_store.get_thread(thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    return thread["messages"]
