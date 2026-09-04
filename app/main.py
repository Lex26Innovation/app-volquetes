from fastapi.middleware.cors import CORSMiddleware
import jwt
from typing import List
from fastapi import FastAPI, Depends, HTTPException, status, WebSocket, WebSocketDisconnect
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from sqlalchemy.orm import Session
from .database import engine, get_db
from . import models, schemas, auth

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="API Volquetes MVP")

# Permitir peticiones desde el navegador (CORS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# --- GESTOR DE WEBSOCKETS (ALERTAS EN TIEMPO REAL) ---

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
        for connection in self.active_connections:
            await connection.send_json(message)

manager = ConnectionManager()

@app.websocket("/ws/fletes")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# --- SEGURIDAD Y AUTENTICACIÓN ---

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

def obtener_conductor_actual(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    excepcion_credenciales = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Credenciales inválidas o token expirado",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, auth.SECRET_KEY, algorithms=[auth.ALGORITHM])
        telefono: str = payload.get("sub")
        if telefono is None:
            raise excepcion_credenciales
    except jwt.InvalidTokenError:
        raise excepcion_credenciales
    
    conductor = db.query(models.Driver).filter(models.Driver.contact_phone == telefono).first()
    if conductor is None:
        raise excepcion_credenciales
    return conductor

@app.post("/api/auth/registrar", tags=["Seguridad"])
def registrar_conductor(driver: schemas.DriverCreate, db: Session = Depends(get_db)):
    db_user = db.query(models.Driver).filter(models.Driver.contact_phone == driver.contact_phone).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Este número de teléfono ya está registrado")
    
    nuevo_conductor = models.Driver(
        full_name=driver.full_name,
        contact_phone=driver.contact_phone,
        plate=driver.plate,
        capacity_m3=driver.capacity_m3,
        hashed_password=auth.obtener_password_hash(driver.password)
    )
    db.add(nuevo_conductor)
    db.commit()
    db.refresh(nuevo_conductor)
    return {"mensaje": "Conductor registrado exitosamente", "driver_id": nuevo_conductor.id}

@app.post("/api/auth/login", tags=["Seguridad"])
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    conductor = db.query(models.Driver).filter(models.Driver.contact_phone == form_data.username).first()
    if not conductor or not auth.verificar_password(form_data.password, conductor.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Teléfono o contraseña incorrectos")
    
    token = auth.crear_token_acceso(data={"sub": conductor.contact_phone})
    return {"access_token": token, "token_type": "bearer"}

@app.get("/api/conductores/mi-perfil", response_model=schemas.DriverResponse, tags=["Conductores"])
def ver_mi_perfil(conductor_actual: models.Driver = Depends(obtener_conductor_actual)):
    return conductor_actual

# --- FLETES Y OPERACIONES ---

@app.post("/api/orders/publicar", tags=["Fletes"])
async def publicar_flete(
quarry_name: str,
    delivery_address: str,
    total_price: float,
    origin_lat: float = -16.3533,
    origin_lng: float = -71.5831,
    dest_lat: float = -16.3683,
    dest_lng: float = -71.5458,
    db: Session = Depends(get_db)
):
    orden = models.Order(
        quarry_name=quarry_name,
        delivery_address=delivery_address,
        total_price=total_price,
        origin_lat=origin_lat,
        origin_lng=origin_lng,
        dest_lat=dest_lat,
        dest_lng=dest_lng,
        status="pending_payment"
    )
    db.add(orden)
    db.commit()
    db.refresh(orden)
    
    # Alerta WebSocket con coordenadas para el mapa interactivo
    await manager.broadcast({
        "evento": "NUEVO_FLETE",
        "order_id": orden.id,
        "cantera": orden.quarry_name,
        "destino": orden.delivery_address,
        "precio": orden.total_price,
        "origin_lat": orden.origin_lat,
        "origin_lng": orden.origin_lng,
        "dest_lat": orden.dest_lat,
        "dest_lng": orden.dest_lng
    })
    
    return {"mensaje": "Flete publicado con mapa", "order_id": orden.id}

@app.post("/api/orders/{order_id}/aceptar", tags=["Fletes"])
def aceptar_flete(order_id: int, db: Session = Depends(get_db), conductor_actual: models.Driver = Depends(obtener_conductor_actual)):
    orden = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not orden:
        raise HTTPException(status_code=404, detail="Flete no encontrado")
    if orden.driver_id is not None:
        raise HTTPException(status_code=400, detail="Este flete ya fue asignado")
    
    orden.driver_id = conductor_actual.id
    orden.status = "assigned"
    db.commit()
    return {"mensaje": f"Flete #{order_id} asignado a {conductor_actual.full_name}", "order_id": orden.id}

@app.get("/api/orders/{order_id}", response_model=schemas.OrderResponse, tags=["Fletes"])
def ver_detalle_flete(order_id: int, db: Session = Depends(get_db)):
    orden = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not orden:
        raise HTTPException(status_code=404, detail="Flete no encontrado")

    driver_data = None
    if orden.driver:
        if orden.status in ["escrow_paid", "in_transit", "completed"]:
            nombre_mostrar = orden.driver.full_name
            telefono_mostrar = orden.driver.contact_phone
        else:
            nombre_mostrar = "*** PROTEGIDO ***"
            telefono_mostrar = "*** PROTEGIDO ***"

        driver_data = schemas.DriverResponse(
            id=orden.driver.id,
            plate=orden.driver.plate,
            capacity_m3=orden.driver.capacity_m3,
            full_name=nombre_mostrar,
            contact_phone=telefono_mostrar
        )

    return schemas.OrderResponse(
        id=orden.id,
        quarry_name=orden.quarry_name,
        delivery_address=orden.delivery_address,
        total_price=orden.total_price,
        status=orden.status,
        driver=driver_data
    )

@app.post("/api/orders/{order_id}/pagar-garantia", tags=["Fletes"])
def simular_pago_garantia(order_id: int, db: Session = Depends(get_db)):
    orden = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not orden:
        raise HTTPException(status_code=404, detail="Flete no encontrado")
    
    orden.status = "escrow_paid"
    db.commit()
    return {"mensaje": "Pago en garantía exitoso. Datos del conductor liberados."}

@app.post("/api/orders/{order_id}/iniciar-viaje", tags=["Fletes"])
async def iniciar_viaje(
    order_id: int, 
    db: Session = Depends(get_db), 
    conductor_actual: models.Driver = Depends(obtener_conductor_actual)
):
    orden = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not orden:
        raise HTTPException(status_code=404, detail="Flete no encontrado")
    if orden.driver_id != conductor_actual.id:
        raise HTTPException(status_code=403, detail="No estás asignado a este flete")
    
    orden.status = "in_transit"
    db.commit()

    await manager.broadcast({
        "evento": "CAMBIO_ESTADO",
        "order_id": orden.id,
        "nuevo_estado": "in_transit"
    })
    return {"mensaje": f"Flete #{order_id} en ruta", "estado": orden.status}

@app.post("/api/orders/{order_id}/completar-viaje", tags=["Fletes"])
async def completar_viaje(
    order_id: int, 
    db: Session = Depends(get_db), 
    conductor_actual: models.Driver = Depends(obtener_conductor_actual)
):
    orden = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not orden:
        raise HTTPException(status_code=404, detail="Flete no encontrado")
    if orden.driver_id != conductor_actual.id:
        raise HTTPException(status_code=403, detail="No estás asignado a este flete")
    
    orden.status = "completed"
    db.commit()

    await manager.broadcast({
        "evento": "CAMBIO_ESTADO",
        "order_id": orden.id,
        "nuevo_estado": "completed"
    })
    return {"mensaje": f"Flete #{order_id} completado con éxito", "estado": orden.status}