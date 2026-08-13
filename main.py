import os
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
import httpx

app = FastAPI()

# Leemos el Access Token desde las variables de entorno de Vercel
MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN")

# Lista temporal en memoria para demostración en Vercel
transacciones_memoria = []

@app.get("/", response_class=HTMLResponse)
def home():
    html = """
    <html>
        <head>
            <title>Control de Efectivo - MP</title>
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <style>
                body { font-family: Arial; margin: 20px; background: #f4f4f9; color: #333; }
                .card { background: white; padding: 15px; margin-bottom: 10px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
                .btn { background: #009ee3; color: white; border: none; padding: 10px 15px; border-radius: 5px; cursor: pointer; font-size: 16px; }
                .btn-disabled { background: #ccc; cursor: not-allowed; }
                .badge-ok { color: green; font-weight: bold; }
                .badge-no { color: red; font-weight: bold; }
            </style>
        </head>
        <body>
            <h1>Control de Transferencias (Vercel) 💸</h1>
            <p>Panel activo en la nube:</p>
    """
    if not transacciones_memoria:
        html += "<p>No hay transacciones registradas todavía.</p>"
    
    for t in transacciones_memoria:
        estado = "<span class='badge-ok'>ENTREGADO</span>" if t["entregado"] else "<span class='badge-no'>DISPONIBLE PARA RETIRAR</span>"
        boton = f'<button class="btn btn-disabled" disabled>Ya entregado</button>' if t["entregado"] else f'<button class="btn" onclick="entregar(\'{t["id"]}\')">Marcar como Entregado</button>'
        
        html += f"""
        <div class="card">
            <h3>Remitente: {t["remitente"]}</h3>
            <p>Monto: <b>${t["monto"]}</b></p>
            <p>Estado: {estado}</p>
            {boton}
        </div>
        """

    html += """
            <script>
                async function entregar(id) {
                    let res = await fetch('/marcar-entregado/' + id, { method: 'POST' });
                    if(res.ok) { location.reload(); } else { alert('Error al marcar'); }
                }
            </script>
        </body>
    </html>
    """
    return html

@app.post("/webhook")
async def recibir_webhook(request: Request):
    data = await request.json()
    
    # FORZAMOS el guardado de cualquier cosa que llegue
    # para ver si el problema es el filtro de 'status'
    payment_id = str(data.get("data", {}).get("id", "sin_id"))
    
    # Lo agregamos a la lista sin consultar nada a la API por ahora
    # para descartar problemas con el Access Token
    transacciones_memoria.append({
        "id": payment_id,
        "monto": 999999, # Monto falso para identificar que entró
        "remitente": f"DEBUG: {data.get('type')}",
        "entregado": False,
    })
    
    return {"status": "ok_debug"}

@app.post("/simular-pago")
def simular_pago(id: str, monto: float, remitente: str):
    if any(t["id"] == id for t in transacciones_memoria):
        raise HTTPException(status_code=400, detail="Ese ID de pago ya existe")
    transacciones_memoria.append({"id": id, "monto": monto, "remitente": remitente, "entregado": False})
    return {"message": "Pago simulado con éxito"}

@app.post("/marcar-entregado/{payment_id}")
def marcar_entregado(payment_id: str):
    for t in transacciones_memoria:
        if t["id"] == payment_id:
            if t["entregado"]:
                raise HTTPException(status_code=400, detail="Ya entregado.")
            t["entregado"] = True
            return {"message": "Marcado como entregado"}
    raise HTTPException(status_code=404, detail="No encontrado")