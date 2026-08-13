import os
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
import httpx

app = FastAPI()

MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN")

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
    
    payment_id = str(data.get("data", {}).get("id"))
    tipo_evento = data.get("type")
    
    if payment_id:
        monto = 0.0
        remitente = "Transferencia Mercado Pago"

        # Intentamos consultar la API oficial si tenemos el token para traer el monto real
        if MP_ACCESS_TOKEN and tipo_evento == "payment":
            try:
                async with httpx.AsyncClient() as client:
                    headers = {"Authorization": f"Bearer {MP_ACCESS_TOKEN}"}
                    response = await client.get(
                        f"https://api.mercadopago.com/v1/payments/{payment_id}",
                        headers=headers,
                    )
                    if response.status_code == 200:
                        pago_info = response.json()
                        monto = float(pago_info.get("transaction_amount", 0.0))
                        payer = pago_info.get("payer", {})
                        nombre = payer.get("first_name", "")
                        apellido = payer.get("last_name", "")
                        if nombre or apellido:
                            remitente = f"{nombre} {apellido}".strip()
            except Exception:
                pass # Si falla la consulta externa, evitamos que rompa el webhook

        # Evitamos duplicados
        existe = False
        for t in transacciones_memoria:
            if t["id"] == payment_id:
                existe = True
                break

        if not existe:
            transacciones_memoria.append({
                "id": payment_id,
                "monto": monto,
                "remitente": remitente,
                "entregado": False,
            })
            
    return {"status": "ok"}

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