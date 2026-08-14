import os
import csv
import io
import asyncio
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
import httpx

app = FastAPI()

MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN")
API_BASE = "https://api.mercadopago.com"

transacciones_memoria = []

def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

@app.get("/", response_class=HTMLResponse)
def home():
    html = """
    <html>
        <head>
            <title>Control de Transferencias - MP</title>
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <style>
                body { font-family: Arial; margin: 20px; background: #f4f4f9; color: #333; }
                .card { background: white; padding: 15px; margin-bottom: 10px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); word-break: break-all; }
                .btn { background: #009ee3; color: white; border: none; padding: 10px 15px; border-radius: 5px; cursor: pointer; font-size: 16px; }
                .btn-success { background: #28a745; margin-bottom: 20px; }
            </style>
        </head>
        <body>
            <h1>Control de Transferencias (Debug Response) 💸</h1>
            <button id="btn-sync" class="btn btn-success" onclick="sincronizar()">🔄 Sincronizar y Ver Debug</button>
            <div id="status-sync"></div>
            <div id="panel">
    """
    
    if not transacciones_memoria:
        html += "<p>No hay registros cargados.</p>"
    
    for t in transacciones_memoria:
        html += f"""
        <div class="card">
            <h3>Remitente: {t["remitente"]}</h3>
            <p>ID: {t["id"]}</p>
            <p>Monto: <b>${t["monto"]}</b></p>
        </div>
        """

    html += """
            </div>
            <script>
                async function sincronizar() {
                    let btn = document.getElementById('btn-sync');
                    let statusDiv = document.getElementById('status-sync');
                    
                    btn.disabled = true;
                    btn.style.background = '#ccc';
                    statusDiv.innerHTML = '<p><b>⏳ Consultando reporte...</b></p>';

                    try {
                        let res = await fetch('/sincronizar-reportes', { method: 'POST' });
                        let data = await res.json();
                        
                        // Imprimimos el JSON completo devuelto por el servidor en la alerta
                        alert("DEBUG RESPONSE: " + JSON.stringify(data, null, 2));
                        location.reload();
                    } catch (e) {
                        alert('Error de red o parseo.');
                        statusDiv.innerHTML = '';
                        btn.disabled = false;
                        btn.style.background = '#28a745';
                    }
                }
            </script>
        </body>
    </html>
    """
    return html

@app.post("/sincronizar-reportes")
async def sincronizar_reportes():
    if not MP_ACCESS_TOKEN:
        raise HTTPException(status_code=500, detail="Falta configurar el MP_ACCESS_TOKEN")

    headers = {
        "Authorization": f"Bearer {MP_ACCESS_TOKEN}",
        "Accept": "application/json",
    }

    now = datetime.now(timezone.utc)
    begin = now - timedelta(hours=10)

    async with httpx.AsyncClient(timeout=30.0) as client:
        params = {"begin_date": iso_z(begin), "end_date": iso_z(now), "created_from": "manual", "limit": 10}
        
        file_name = None
        search_resp = await client.get(f"{API_BASE}/v1/account/settlement_report/search", params=params, headers=headers)
        
        if search_resp.status_code == 200:
            data = search_resp.json()
            reports = data.get("results") or data.get("data") or []
            for r in reports:
                if r.get("status") == "processed" and r.get("file_name"):
                    file_name = r["file_name"]
                    break

        if not file_name:
            payload = {"begin_date": iso_z(begin), "end_date": iso_z(now)}
            await client.post(f"{API_BASE}/v1/account/settlement_report", json=payload, headers=headers)

        for _ in range(5):
            search_resp = await client.get(f"{API_BASE}/v1/account/settlement_report/search", params=params, headers=headers)
            if search_resp.status_code == 200:
                data = search_resp.json()
                reports = data.get("results") or data.get("data") or []
                for r in reports:
                    if r.get("status") == "processed" and r.get("file_name"):
                        file_name = r["file_name"]
                        break
            if file_name:
                break
            await asyncio.sleep(4)

        if not file_name:
            return {"status": "error", "mensaje": "El reporte aún se está generando en Mercado Pago."}

        download_resp = await client.get(f"{API_BASE}/v1/account/settlement_report/{file_name}", headers=headers)
        if download_resp.status_code != 200:
            return {"status": "error", "mensaje": "No se pudo descargar el archivo CSV."}

        text = download_resp.content.decode("utf-8", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        
        filas_muestra = []
        for i, row in enumerate(reader):
            if i < 5:  # Guardamos las primeras 5 filas completas para inspeccionarlas
                filas_muestra.append(row)
            
            p_id = str(row.get("SOURCE_ID") or row.get("PAYMENT_ID") or row.get("ID") or f"row_{i}")
            monto_str = row.get("TRANSACTION_AMOUNT") or row.get("REAL_AMOUNT") or row.get("AMOUNT") or "0"
            try:
                monto = float(monto_str)
            except ValueError:
                monto = 0.0

            tx_type = row.get("TRANSACTION_TYPE") or "movimiento"
            pm_type = row.get("PAYMENT_METHOD_TYPE") or ""
            
            if not any(t["id"] == p_id for t in transacciones_memoria):
                transacciones_memoria.append({
                    "id": p_id,
                    "monto": abs(monto),
                    "remitente": f"{tx_type} ({pm_type})",
                    "entregado": False
                })

    return {
        "status": "success", 
        "total_en_memoria": len(transacciones_memoria), 
        "primeras_filas_csv": filas_muestra
    }