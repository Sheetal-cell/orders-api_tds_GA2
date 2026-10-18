from fastapi import FastAPI, Request, HTTPException, status, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, List, Dict
import time

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TOTAL_ORDERS = 51
RATE_LIMIT = 19
WINDOW_SECONDS = 10

orders_db: Dict[int, dict] = {i: {"id": i, "item": f"Item {i}", "price": i * 10.0} for i in range(1, TOTAL_ORDERS + 1)}
idempotency_store: Dict[str, dict] = {}
rate_limit_store: Dict[str, List[float]] = {}

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    # Only rate-limit orders endpoints
    if request.url.path.startswith("/orders"):
        # Case-insensitive header check for X-Client-Id
        client_id = request.headers.get("x-client-id") or request.headers.get("X-Client-Id") or "default-client"
        
        now = time.time()
        if client_id not in rate_limit_store:
            rate_limit_store[client_id] = []
        
        window_start = now - WINDOW_SECONDS
        rate_limit_store[client_id] = [t for t in rate_limit_store[client_id] if t > window_start]
        
        if len(rate_limit_store[client_id]) >= RATE_LIMIT:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"detail": "Rate limit exceeded"},
                headers={"Retry-After": str(WINDOW_SECONDS)}
            )
        
        rate_limit_store[client_id].append(now)
        
    response = await call_next(request)
    return response

class OrderCreate(BaseModel):
    item_name: Optional[str] = "Default Item"

@app.post("/orders", status_code=status.HTTP_201_CREATED)
def create_order(
    order_in: OrderCreate,
    idempotency_key: Optional[str] = None,
):
    # Retrieve idempotency key from headers case-insensitively via request if needed, 
    # but FastAPI query/header mapping can also capture Idempotency-Key:
    pass

# Alternative proper signature for POST with headers:
@app.post("/orders", status_code=status.HTTP_201_CREATED)
def create_order_endpoint(
    request: Request,
    order_in: OrderCreate,
):
    idempotency_key = request.headers.get("idempotency-key") or request.headers.get("Idempotency-Key")
    
    if idempotency_key and idempotency_key in idempotency_store:
        return idempotency_store[idempotency_key]
    
    new_id = len(orders_db) + 1
    response_payload = {"id": str(new_id), "item": order_in.item_name, "status": "created"}
    orders_db[new_id] = {"id": new_id, "item": order_in.item_name, "price": 100.0}
    
    if idempotency_key:
        idempotency_store[idempotency_key] = response_payload
        
    return response_payload

@app.get("/orders")
def get_orders(
    request: Request,
    limit: int = Query(10, ge=1, le=100),
    cursor: Optional[str] = Query(None),
):
    start_id = 1
    if cursor:
        try:
            start_id = int(cursor) + 1
        except ValueError:
            start_id = 1
            
    items = []
    current_id = start_id
    while current_id <= TOTAL_ORDERS and len(items) < limit:
        if current_id in orders_db:
            items.append(orders_db[current_id])
        current_id += 1
        
    next_cursor = str(items[-1]["id"]) if items and items[-1]["id"] < TOTAL_ORDERS else None
    
    return {
        "items": items,
        "next_cursor": next_cursor
    }