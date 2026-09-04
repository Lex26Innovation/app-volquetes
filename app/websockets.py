from fastapi import WebSocket

class ConnectionManager:
    def __init__(self):
        # Diccionario para guardar los volqueteros conectados: {driver_id: WebSocket}
        self.active_connections: dict[int, WebSocket] = {}

    async def connect(self, websocket: WebSocket, driver_id: int):
        await websocket.accept()
        self.active_connections[driver_id] = websocket
        print(f"Volquetero {driver_id} conectado.")

    def disconnect(self, driver_id: int):
        if driver_id in self.active_connections:
            del self.active_connections[driver_id]
            print(f"Volquetero {driver_id} desconectado.")

    async def broadcast_alert(self, message: dict):
        # Envía la alerta de flete a todos los volqueteros disponibles
        for connection in self.active_connections.values():
            await connection.send_json(message)

# Instancia global del gestor
manager = ConnectionManager()