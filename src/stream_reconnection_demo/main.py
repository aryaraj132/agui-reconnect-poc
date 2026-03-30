import logging
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.memory import MemorySaver

from stream_reconnection_demo.agent.segment.graph import build_segment_graph
from stream_reconnection_demo.agent.segment.routes import router as segment_router
from stream_reconnection_demo.agent.stateful_segment.routes import router as stateful_segment_router
from stream_reconnection_demo.core.pubsub import RedisPubSubManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Build agent graph with MemorySaver checkpointer
    logger.info("Building segment graph with checkpointer...")
    checkpointer = MemorySaver()
    app.state.segment_graph = build_segment_graph(checkpointer=checkpointer)
    logger.info("Segment graph ready")

    # Build a separate graph for stateful-segment (own checkpointer namespace)
    stateful_checkpointer = MemorySaver()
    app.state.stateful_segment_graph = build_segment_graph(checkpointer=stateful_checkpointer)
    logger.info("Stateful segment graph ready")

    # Initialize Redis Pub/Sub manager
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    logger.info("Connecting to Redis at %s", redis_url)
    try:
        app.state.pubsub = RedisPubSubManager(redis_url)
        logger.info("Redis Pub/Sub manager initialized")
    except Exception:
        logger.warning("Redis initialization failed, running without persistence")
        app.state.pubsub = RedisPubSubManager(redis_url)

    yield

    # Cleanup
    try:
        await app.state.pubsub.close()
        logger.info("Redis connection closed")
    except Exception:
        logger.warning("Redis cleanup failed")


app = FastAPI(
    title="AG-UI Stream Reconnection Demo",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Single router — all reconnection logic handled within
app.include_router(segment_router)
app.include_router(stateful_segment_router)


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
