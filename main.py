import os
from datetime import datetime
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
import httpx

app = FastAPI()

# Leemos el Token de forma segura desde las variables de entorno de Vercel
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

  for t in transacciones_memoria:
    estado = (
        "<span class='badge-ok'>ENTREGADO</span>"
        if t["entregado"]
        else "<span class='badge-no'>DISPONIBLE PARA RETIRAR</span>"
    )
    boton = (
        f'<button class="btn btn-disabled" disabled>Ya entregado</button>'
        if t["entregado"]
        else (
            f'<button class="btn" onclick="entregar(\'{t["id"]}\')">Marcar'
            " como Entregado</button>"
        )
    )

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
                    let data = await res.json();
                    if(res.ok) {
                        location.reload();
                    } else {
                        alert(data.detail);
                    }
                }
            </script>
        </body>
    </html>
    """
  return html


@app.post("/webhook")
async def recibir_webhook(request: Request):
  data = await request.json()

  tipo_evento = data.get("type")
  payment_id = None
  monto = 0.0
  remitente = "Cliente de Transferencia"

  # Identificamos si es un pago directo o una orden comercial
  if tipo_evento == "payment":
    payment_id = str(data.get("data", {}).get("id"))
  elif tipo_evento == "order":
    payment_id = str(data.get("data", {}).get("id"))
    monto = float(data.get("data", {}).get("total_paid_amount", 0.0))

  # Si tenemos un ID válido, procedemos
  if payment_id:
    # Si es un evento de pago tradicional, consultamos los detalles reales a la API
    if tipo_evento == "payment" and MP_ACCESS_TOKEN:
      async with httpx.AsyncClient() as client:
        headers = {"Authorization": f"Bearer {MP_ACCESS_TOKEN}"}
        response = await client.get(
            f"https://api.mercadopago.com/v1/payments/{payment_id}",
            headers=headers,
        )

        if response.status_code == 200:
          pago_info = response.json()
          monto = pago_info.get("transaction_amount", 0.0)

          payer = pago_info.get("payer", {})
          nombre = payer.get("first_name", "")
          apellido = payer.get("last_name", "")
          if nombre or apellido:
            remitente = f"{nombre} {apellido}".strip()

    # Evitamos duplicados si el webhook se dispara dos veces
    for t in transacciones_memoria:
      if t["id"] == payment_id:
        return {"status": "already_exists"}

    # Insertamos en la lista de memoria
    transacciones_memoria.append({
        "id": payment_id,
        "monto": monto,
        "remitente": remitente,
        "entregado": False,
    })

  return {"status": "ok"}


@app.post("/simular-pago")
def simular_pago(id: str, monto: float, remitente: str):
  for t in transacciones_memoria:
    if t["id"] == id:
      raise HTTPException(status_code=400, detail="Ese ID de pago ya fue simulado")

  transacciones_memoria.append({
      "id": id,
      "monto": monto,
      "remitente": remitente,
      "entregado": False,
  })
  return {"message": "Pago simulado con éxito en Vercel"}


@app.post("/marcar-entregado/{payment_id}")
def marcar_entregado(payment_id: str):
  for t in transacciones_memoria:
    if t["id"] == payment_id:
      if t["entregado"]:
        raise HTTPException(
            status_code=400,
            detail="¡CUIDADO! Esta transferencia ya fue entregada anteriormente.",
        )
      t["entregado"] = True
      return {"message": "Marcado como entregado"}

  raise HTTPException(status_code=404, detail="Transferencia no encontrada")
  