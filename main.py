import os
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
import httpx

app = FastAPI()

# Leemos el Access Token desde las variables de entorno de Vercel
MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN")

# Lista temporal en memoria
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
            </style>
        </head>
        <body>
            <h1>Control de Transferencias (Vercel) 💸</h1>
            <p>Monitoreando eventos en tiempo real:</p>
    """
    if not transacciones_memoria:
        html += "<p>Esperando notificaciones de Mercado Pago...</p>"
    
    for t in transacciones_memoria:
        html += f"""
        <div class="card">
            <h3>{t["remitente"]}</h3>
            <p>ID: {t["id"]}</p>
            <p>Monto: <b>${t["monto"]}</b></p>
            <button class="btn" onclick="entregar('{t["id"]}')">Marcar como Entregado</button>
        </div>
        """

    html += """
            <script>
                async function entregar(id) {
                    let res = await fetch('/marcar-entregado/' + id, { method: 'POST' });
                    if(res.ok) { location.reload(); }
                }
            </script>
        </body>
    </html>
    """
    return html

@app.post("/webhook")
async def recibir_webhook(request: Request):
    data = await request.json()
    
    # Extraemos info básica para diagnóstico
    payment_id = str(data.get("data", {}).get("id", "sin_id"))
    tipo_evento = data.get("type", "desconocido")
    
    # Registramos todo lo que llegue para ver qué pasa en tu transferencia real
    # Usamos un identificador claro para saber qué está llegando
    registro = {
        "id": f"{payment_id} ({tipo_evento})",
        "monto": 0.0,
        "remitente": f"EVENTO: {tipo_evento}",
        "entregado": False,
    }
    
    # Solo agregamos si no es un duplicado exacto
    if not any(t["id"] == registro["id"] for t in transacciones_memoria):
        transacciones_memoria.append(registro)
            
    return {"status": "ok_diagnostic"}

@app.post("/simular-pago")
def simular_pago(id: str, monto: float, remitente: str):
    transacciones_memoria.append({"id": id, "monto": monto, "remitente": remitente, "entregado": False})
    return {"message": "Simulado"}

@app.post("/marcar-entregado/{payment_id}")
def marcar_entregado(payment_id: str):
    # Lógica simplificada para marcar entregado
    for t in transacciones_memoria:
        if t["id"] == payment_id:
            t["entregado"] = True
            return {"message": "Marcado"}
    raise HTTPException(status_code=404, detail="No encontrado")