from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import List
import json

from app import models, schemas, auth
from app.database import engine, get_db

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="API Volquetes MVP")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        # Limpia automáticamente conexiones cerradas para no congelar las transmisiones
        desconectados = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                desconectados.append(connection)
        
        for conn in desconectados:
            self.disconnect(conn)

manager = ConnectionManager()

app.include_router(auth.router, prefix="/api/auth", tags=["Autenticación"])

@app.get("/")
def read_root():
    return {"mensaje": "API Volquetes Activa"}

@app.post("/api/orders/publicar", tags=["Fletes"])
async def publicar_flete(quarry_name: str, delivery_address: str, total_price: float, db: Session = Depends(get_db)):
    nueva_orden = models.Order(
        quarry_name=quarry_name,
        delivery_address=delivery_address,
        price=total_price,
        status="pending"
    )
    db.add(nueva_orden)
    db.commit()
    db.refresh(nueva_orden)

    await manager.broadcast({
        "evento": "NUEVO_FLETE",
        "order_id": nueva_orden.id,
        "cantera": nueva_orden.quarry_name,
        "destino": nueva_orden.delivery_address,
        "precio": nueva_orden.price
    })
    return {"mensaje": "Flete publicado con éxito", "order_id": nueva_orden.id}

@app.post("/api/orders/{order_id}/aceptar", tags=["Fletes"])
async def aceptar_flete(order_id: int, db: Session = Depends(get_db)):
    orden = db.query(models.Order).filter(models.Order.id == order_id).first()
    if orden:
        orden.status = "assigned"
        db.commit()

    await manager.broadcast({
        "evento": "CAMBIO_ESTADO",
        "order_id": order_id,
        "nuevo_estado": "assigned"
    })
    return {"mensaje": f"Flete #{order_id} asignado", "order_id": order_id}

@app.post("/api/orders/{order_id}/iniciar-viaje", tags=["Fletes"])
async def iniciar_viaje(order_id: int, db: Session = Depends(get_db)):
    orden = db.query(models.Order).filter(models.Order.id == order_id).first()
    if orden:
        orden.status = "in_transit"
        db.commit()

    await manager.broadcast({
        "evento": "CAMBIO_ESTADO",
        "order_id": order_id,
        "nuevo_estado": "in_transit"
    })
    return {"mensaje": "Viaje iniciado"}

@app.post("/api/orders/{order_id}/completar-viaje", tags=["Fletes"])
async def completar_viaje(order_id: int, db: Session = Depends(get_db)):
    orden = db.query(models.Order).filter(models.Order.id == order_id).first()
    if orden:
        orden.status = "completed"
        db.commit()

    await manager.broadcast({
        "evento": "CAMBIO_ESTADO",
        "order_id": order_id,
        "nuevo_estado": "completed"
    })
    return {"mensaje": "Viaje completado"}

@app.websocket("/ws/fletes")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                mensaje = json.loads(data)
            except Exception:
                continue  # Si el mensaje no es JSON válido, ignora y NO desconecta al usuario

            evento = mensaje.get("evento")
            if evento == "ACTUALIZAR_UBICACION":
                await manager.broadcast({
                    "evento": "UBICACION_CONDUCTOR",
                    "order_id": mensaje.get("order_id"),
                    "lat": mensaje.get("lat"),
                    "lng": mensaje.get("lng")
                })
            elif evento == "CAMBIO_ESTADO":
                await manager.broadcast({
                    "evento": "CAMBIO_ESTADO",
                    "order_id": mensaje.get("order_id"),
                    "nuevo_estado": mensaje.get("nuevo_estado")
                })
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)

# Guardar última ubicación reportada en memoria
ultimas_ubicaciones = {}

@app.get("/api/orders/{order_id}/estado", tags=["Fletes"])
def obtener_estado_flete(order_id: int, db: Session = Depends(get_db)):
    orden = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not orden:
        raise HTTPException(status_code=404, detail="Flete no encontrado")
    
    pos = ultimas_ubicaciones.get(order_id, {"lat": None, "lng": None})
    return {
        "order_id": orden.id,
        "status": orden.status,
        "lat": pos["lat"],
        "lng": pos["lng"]
    }

@app.post("/api/orders/{order_id}/ubicacion", tags=["Fletes"])
async def actualizar_ubicacion_rest(order_id: int, lat: float, lng: float):
    ultimas_ubicaciones[order_id] = {"lat": lat, "lng": lng}
    await manager.broadcast({
        "evento": "UBICACION_CONDUCTOR",
        "order_id": order_id,
        "lat": lat,
        "lng": lng
    })
    return {"status": "ok"}