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
            <h1>Control de Transferencias (Inspección de Claves) 💸</h1>
            <button id="btn-sync" class="btn btn-success" onclick="sincronizar()">🔄 Sincronizar y Ver Datos</button>
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
            <hr>
            <small style="color: #666;"><b>Debug Row Keys:</b> {t["keys_raw"]}</small>
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
                    statusDiv.innerHTML = '<p><b>⏳ Analizando estructura del CSV...</b></p>';

                    try {
                        let res = await fetch('/sincronizar-reportes', { method: 'POST' });
                        let data = await res.json();
                        if(res.ok) {
                            alert(data.message);
                            location.reload();
                        } else {
                            alert('Aviso: ' + (data.detail || 'Error'));
                            statusDiv.innerHTML = '';
                            btn.disabled = false;
                            btn.style.background = '#28a745';
                        }
                    } catch (e) {
                        alert('Error de red.');
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
        raise HTTPException(status_code=500, detail="Falta el token")

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
            raise HTTPException(status_code=400, detail="El reporte se está procesando.")

        download_resp = await client.get(f"{API_BASE}/v1/account/settlement_report/{file_name}", headers=headers)
        if download_resp.status_code != 200:
            raise HTTPException(status_code=400, detail="No se pudo descargar.")

        text = download_resp.content.decode("utf-8", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        
        transacciones_memoria.clear()
        registros_agregados = 0

        # Tomamos solo los primeros 5 para inspeccionar en pantalla las columnas exactas que trae el CSV
        for row in reader:
            if registros_agregados >= 5:
                break
                
            # Extraemos las llaves reales del diccionario para mostrarlas en la tarjeta
            keys_str = ", ".join(list(row.keys())[:10]) # Muestra las primeras 10 columnas del CSV

            transacciones_memoria.append({
                "id": "Inspeccionando",
                "monto": 0.0,
                "remitente": "Fila de prueba CSV",
                "keys_raw": keys_str,
                "entregado": False
            })
            registros_agregados += 1

    return {"message": "Inspección completada. Mirá las columnas en pantalla."}