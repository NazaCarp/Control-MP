import os
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse

app = FastAPI(title="Control de transferencias MP")

MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN")
MP_API_URL = "https://api.mercadopago.com"

# Se usa como almacenamiento temporal mientras la app está corriendo
transacciones_memoria = []


def get_incoming_transfers(payload):
    if not isinstance(payload, dict):
        return []

    results = payload.get("results") or []
    transfers = []

    for item in results:
        payment_id = str(item.get("id") or "sin_id")
        amount = item.get("transaction_amount") or item.get("amount") or 0
        payer = item.get("payer") or {}
        remitente = payer.get("email") or payer.get("first_name") or "Mercado Pago"
        status = item.get("status") or "unknown"

        transfer = {
            "id": payment_id,
            "monto": float(amount),
            "remitente": remitente,
            "estado": status,
            "fecha": item.get("date_created") or datetime.now(timezone.utc).isoformat(),
            "metodo": item.get("payment_method_id") or "unknown",
            "entregado": False,
        }

        existing = next((t for t in transacciones_memoria if t["id"] == transfer["id"]), None)
        if existing is not None:
            transfer["entregado"] = existing.get("entregado", False)

        transfers.append(transfer)

    return transfers


async def fetch_mp_incoming_transfers():
    if not MP_ACCESS_TOKEN:
        return []

    headers = {"Authorization": f"Bearer {MP_ACCESS_TOKEN}"}
    params = {
        "sort": "date_desc",
        "criteria": "desc",
        "limit": 10,
    }

    try:
        response = await httpx.get(
            f"{MP_API_URL}/v1/payments/search",
            headers=headers,
            params=params,
            timeout=20,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Error consultando Mercado Pago: {exc}") from exc

    payload = response.json()
    return get_incoming_transfers(payload)


async def sync_mp_transfers():
    remote = await fetch_mp_incoming_transfers() if MP_ACCESS_TOKEN else []
    if not remote:
        return list(transacciones_memoria)

    merged = []
    seen = set()

    for item in remote:
        merged.append(item)
        seen.add(item["id"])

    for item in transacciones_memoria:
        if item["id"] not in seen:
            merged.append(item)

    transacciones_memoria.clear()
    transacciones_memoria.extend(merged)
    return merged


@app.get("/", response_class=HTMLResponse)
async def home():
    try:
        transfers = await sync_mp_transfers()
    except HTTPException:
        transfers = list(transacciones_memoria)

    if not transfers:
        transfers = [
            {
                "id": "demo-001",
                "monto": 1500.0,
                "remitente": "Demo - Juan Pérez",
                "estado": "approved",
                "fecha": (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat(),
                "metodo": "account_money",
                "entregado": False,
            }
        ]

    html = """
    <html>
        <head>
            <title>Control de Transferencias - Mercado Pago</title>
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <style>
                body { font-family: Arial; margin: 24px; background: #f4f4f9; color: #222; }
                .card { background: white; padding: 18px; margin-bottom: 12px; border-radius: 10px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }
                .btn { background: #009ee3; color: white; border: none; padding: 10px 16px; border-radius: 6px; cursor: pointer; font-size: 15px; }
                .btn-done { background: #2d9a4b; }
                .muted { color: #666; }
            </style>
        </head>
        <body>
            <h1>Transferencias entrantes</h1>
            <p class="muted">Mercado Pago · listado para marcar como entregadas</p>
            <button class="btn" onclick="location.reload()">Actualizar</button>
    """

    for t in transfers:
        estado = "Entregada" if t.get("entregado") else "Pendiente"
        boton = "Entregada" if t.get("entregado") else "Marcar como entregada"
        boton_class = "btn btn-done" if t.get("entregado") else "btn"
        html += f"""
        <div class="card">
            <h3>{t['remitente']}</h3>
            <p><strong>ID:</strong> {t['id']}</p>
            <p><strong>Monto:</strong> ${t['monto']:.2f}</p>
            <p><strong>Estado:</strong> {t['estado']}</p>
            <p><strong>Fecha:</strong> {t['fecha']}</p>
            <p><strong>Estado local:</strong> {estado}</p>
            <button class="{boton_class}" onclick="entregar('{t['id']}')">{boton}</button>
        </div>
        """

    html += """
        <script>
            async function entregar(id) {
                const res = await fetch('/marcar-entregado/' + encodeURIComponent(id), { method: 'POST' });
                if (res.ok) {
                    location.reload();
                } else {
                    alert('No se pudo actualizar la transferencia');
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
    payment_id = str(data.get("data", {}).get("id", "sin_id"))
    tipo_evento = data.get("type", "desconocido")

    registro = {
        "id": f"{payment_id} ({tipo_evento})",
        "monto": 0.0,
        "remitente": f"EVENTO: {tipo_evento}",
        "estado": tipo_evento,
        "fecha": datetime.now(timezone.utc).isoformat(),
        "metodo": "webhook",
        "entregado": False,
    }

    if not any(t["id"] == registro["id"] for t in transacciones_memoria):
        transacciones_memoria.append(registro)

    return {"status": "ok"}


@app.post("/simular-pago")
def simular_pago(id: str, monto: float, remitente: str):
    transacciones_memoria.append(
        {
            "id": id,
            "monto": monto,
            "remitente": remitente,
            "estado": "approved",
            "fecha": datetime.now(timezone.utc).isoformat(),
            "metodo": "simulado",
            "entregado": False,
        }
    )
    return {"message": "Simulado"}


@app.post("/marcar-entregado/{payment_id}")
def marcar_entregado(payment_id: str):
    for t in transacciones_memoria:
        if t["id"] == payment_id:
            t["entregado"] = True
            return {"message": "Marcado como entregado"}

    raise HTTPException(status_code=404, detail="No encontrado")


@app.get("/health")
def health_check():
    return {"status": "ok", "token_configured": bool(MP_ACCESS_TOKEN), "count": len(transacciones_memoria)}