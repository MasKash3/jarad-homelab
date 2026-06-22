from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import ALLOWED_ORIGINS, DNS_ACCESS_ENABLED
from .dns_access import sync_firewall_state
from .routes import router


async def dns_access_sync_loop() -> None:
    while True:
        await asyncio.sleep(60)
        await asyncio.to_thread(sync_firewall_state)


@asynccontextmanager
async def lifespan(app: FastAPI):
    dns_sync_task = asyncio.create_task(dns_access_sync_loop()) if DNS_ACCESS_ENABLED else None
    if DNS_ACCESS_ENABLED:
        await asyncio.to_thread(sync_firewall_state)
    try:
        yield
    finally:
        if dns_sync_task:
            dns_sync_task.cancel()
            with suppress(asyncio.CancelledError):
                await dns_sync_task


app = FastAPI(title="Jarad Backend", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
app.include_router(router)
