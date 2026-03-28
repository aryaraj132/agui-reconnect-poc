import logging
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from stream_reconnection_demo.agent.segment.graph import build_segment_graph
from stream_reconnection_demo.agent.segment.routes import router as segment_router
from stream_reconnection_demo.api.reconnect import router as reconnect_router
from stream_reconnection_demo.api.threads import router as threads_router
from stream_reconnection_demo.core.redis_stream import RedisStreamManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Build agent graph
    logger.info("Building segment graph...")
    app.state.segment_graph = build_segment_graph()
    logger.info("Segment graph ready")

    # Initialize Redis connection
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    logger.info("Connecting to Redis at %s", redis_url)
    app.state.redis_manager = RedisStreamManager(redis_url)
    logger.info("Redis connected")

    yield

    # Cleanup
    await app.state.redis_manager.close()
    logger.info("Redis connection closed")


app = FastAPI(
    title="AG-UI Stream Reconnection Demo",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(segment_router)
app.include_router(threads_router)
app.include_router(reconnect_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(
        "stream_reconnection_demo.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
