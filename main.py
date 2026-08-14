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
                .card { background: white; padding: 15px; margin-bottom: 10px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
                .btn { background: #009ee3; color: white; border: none; padding: 10px 15px; border-radius: 5px; cursor: pointer; font-size: 16px; }
                .btn-success { background: #28a745; margin-bottom: 20px; }
            </style>
        </head>
        <body>
            <h1>Control de Transferencias (Modo Debug Total) 💸</h1>
            <button id="btn-sync" class="btn btn-success" onclick="sincronizar()">🔄 Descargar TODO el reporte (10hs)</button>
            <div id="status-sync"></div>
            <div id="panel">
    """
    
    if not transacciones_memoria:
        html += "<p>No hay registros cargados. Hacé clic en el botón para inspeccionar el reporte.</p>"
    
    for t in transacciones_memoria:
        html += f"""
        <div class="card">
            <h3>Remitente / Tipo: {t["remitente"]}</h3>
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
                    statusDiv.innerHTML = '<p><b>⏳ Descargando y leyendo reporte de Mercado Pago...</b></p>';

                    try {
                        let res = await fetch('/sincronizar-reportes', { method: 'POST' });
                        let data = await res.json();
                        if(res.ok) {
                            alert(data.message);
                            location.reload();
                        } else {
                            alert('Aviso: ' + (data.detail || 'Error al sincronizar'));
                            statusDiv.innerHTML = '';
                            btn.disabled = false;
                            btn.style.background = '#28a745';
                        }
                    } catch (e) {
                        alert('Error de red o timeout. Intentá de nuevo.');
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
        raise HTTPException(status_code=500, detail="Falta configurar el MP_ACCESS_TOKEN en Vercel")

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
            raise HTTPException(status_code=400, detail="El reporte se está generando. Volvé a intentarlo en unos segundos.")

        download_resp = await client.get(f"{API_BASE}/v1/account/settlement_report/{file_name}", headers=headers)
        if download_resp.status_code != 200:
            raise HTTPException(status_code=400, detail="No se pudo descargar el archivo de reporte.")

        text = download_resp.content.decode("utf-8", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        
        registros_agregados = 0
        for row in reader:
            # SIN FILTROS: Capturamos cualquier columna disponible para ver qué trae el CSV
            p_id = str(row.get("PAYMENT_ID") or row.get("id") or row.get("reference_id") or row.get("EXTERNAL_REFERENCE") or "id_desconocido")
            monto = float(row.get("AMOUNT") or row.get("transaction_amount") or row.get("monto") or 0.0)
            
            # Intentamos leer el tipo de movimiento y contraparte de cualquier columna posible
            tipo = row.get("MOVEMENT_TYPE") or row.get("tipo_movimiento") or row.get("OPERATION_TYPE") or "Tipo genérico"
            contraparte = row.get("COUNTERPART_NAME") or row.get("payer_name") or row.get("DESCRIPTION") or "Sin detalle"
            
            remitente_texto = f"[{tipo}] - {contraparte}"

            if not any(t["id"] == p_id for t in transacciones_memoria):
                transacciones_memoria.append({
                    "id": p_id,
                    "monto": monto,
                    "remitente": remitente_texto,
                    "entregado": False
                })
                registros_agregados += 1

    return {"message": f"Lectura completa. Se cargaron {registros_agregados} registros encontrados en el reporte."}