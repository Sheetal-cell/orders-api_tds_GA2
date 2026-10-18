from fastapi import FastAPI, Header, HTTPException, status, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict
import time
import uuid

app = FastAPI()

# Enable CORS for browser verification
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Assigned values
TOTAL_ORDERS = 51
RATE_LIMIT = 19
WINDOW_SECONDS = 10

# In-memory storage for stateful patterns
idempotency_store: Dict[str, dict] = {}
orders_db: Dict[int, dict] = {i: {"id": i, "item": f"Item {i}", "price": i * 10.0} for i in range(1, TOTAL_ORDERS + 1)}

# Rate limiting storage: {client_id: [timestamp1, timestamp2, ...]}
rate_limit_store: Dict[str, List[float]] = {}

def check_rate_limit(client_id: str):
    now = time.time()
    if client_id not in rate_limit_store:
        rate_limit_store[client_id] = []
    
    # Filter out timestamps outside the 10-second window
    window_start = now - WINDOW_SECONDS
    rate_limit_store[client_id] = [t for t in rate_limit_store[client_id] if t > window_start]
    
    if len(rate_limit_store[client_id]) >= RATE_LIMIT:
        return False
    
    rate_limit_store[client_id].append(now)
    return True

class OrderCreate(BaseModel):
    item_name: Optional[str] = "Default Item"

@app.post("/orders", status_code=status.HTTP_201_CREATED)
def create_order(
    order_in: OrderCreate,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    x_client_id: Optional[str] = Header("default-client", alias="X-Client-Id")
):
    if not check_rate_limit(x_client_id):
        return Response(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            headers={"Retry-After": str(WINDOW_SECONDS)},
            content="Rate limit exceeded"
        )
    
    if idempotency_key and idempotency_key in idempotency_store:
        return idempotency_store[idempotency_key]
    
    # Create new order
    new_id = len(orders_db) + 1
    order_data = {"id": new_id, "item": order_in.item_name, "status": "created"}
    orders_db[new_id] = order_data
    
    response_payload = {"id": str(new_id), "item": order_in.item_name, "status": "created"}
    
    if idempotency_key:
        idempotency_store[idempotency_key] = response_payload
        
    return response_payload

@app.get("/orders")
def get_orders(
    limit: int = Query(10, ge=1, le=100),
    cursor: Optional[str] = Query(None),
    x_client_id: Optional[str] = Header("default-client", alias="X-Client-Id")
):
    if not check_rate_limit(x_client_id):
        return Response(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            headers={"Retry-After": str(WINDOW_SECONDS)},
            content="Rate limit exceeded"
        )
    
    # Cursor represents the last served order ID (or integer offset)
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