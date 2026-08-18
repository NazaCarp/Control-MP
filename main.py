import os
import csv
import io
import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
import httpx

app = FastAPI()

# Leemos el token directamente desde las variables de entorno de Vercel
MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN", "")
API_BASE = "https://api.mercadopago.com"

transacciones_memoria = []
TZ_ARG = ZoneInfo("America/Argentina/Buenos_Aires")

def iso_arg(dt: datetime) -> str:
    # Genera el string con la zona horaria correcta para la API de MP (-03:00)
    return dt.astimezone(TZ_ARG).isoformat(timespec='seconds')

@app.get("/", response_class=HTMLResponse)
def home():
    # Mostramos en el input el token que viene de la variable de entorno de Vercel
    token_actual = MP_ACCESS_TOKEN

    html = f"""
    <html>
        <head>
            <title>Control de Transferencias - MP</title>
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <style>
                body {{ font-family: Arial; margin: 20px; background: #f4f4f9; color: #333; }}
                .card {{ background: white; padding: 15px; margin-bottom: 10px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
                .config-box {{ background: white; padding: 15px; margin-bottom: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); border-left: 5px solid #009ee3; }}
                .btn {{ background: #009ee3; color: white; border: none; padding: 10px 15px; border-radius: 5px; cursor: pointer; font-size: 16px; }}
                .btn-success {{ background: #28a745; margin-bottom: 20px; }}
                .btn-disabled {{ background: #ccc; cursor: not-allowed; }}
                input[type="text"] {{ padding: 8px; width: 450px; border: 1px solid #ccc; border-radius: 4px; font-size: 14px; background-color: #e9ecef; color: #495057; }}
            </style>
        </head>
        <body>
            <h1>Control de Transferencias (CVU/Alias) 💸</h1>
            
            <div class="config-box">
                <h3>⚙️ Credenciales (Variables de Entorno de Vercel)</h3>
                <label for="token">Access Token configurado:</label><br><br>
                <input type="text" id="token" value="{token_actual}" placeholder="No configurado en Vercel..." readonly>
                <p style="font-size: 13px; color: #666; margin-top: 5px;"><i>Este valor se carga automáticamente desde las Environment Variables de tu proyecto en Vercel.</i></p>
            </div>

            <button id="btn-sync" class="btn btn-success" onclick="sincronizar()">🔄 Buscar Nuevas Transferencias</button>
            <div id="status-sync"></div>
            <div id="panel">
    """
    
    if not transacciones_memoria:
        html += "<p>No hay transferencias cargadas. Hacé clic en 'Buscar Nuevas Transferencias'.</p>"
    
    for t in transacciones_memoria:
        estado = "✅ ENTREGADO" if t["entregado"] else "⏳ DISPONIBLE PARA RETIRAR"
        boton = f'<button class="btn btn-disabled" disabled>Ya entregado</button>' if t["entregado"] else f'<button class="btn" onclick="entregar(\'{t["id"]}\')">Marcar como Entregado</button>'
        
        html += f"""
        <div class="card">
            <p>ID: {t["id"]}</p>
            <p>Fecha: <b>{t["fecha"]}</b></p>
            <p>Monto: <b>${t["monto"]}</b></p>
            <p>Estado: {estado}</p>
            {boton}
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
                    statusDiv.innerHTML = '<p><b>⏳ Consultando a Mercado Pago... Por favor esperá unos segundos...</b></p>';

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

                async function entregar(id) {
                    let res = await fetch('/marcar-entregado/' + id, { method: 'POST' });
                    if(res.ok) { location.reload(); } else { alert('Error al marcar'); }
                }
            </script>
        </body>
    </html>
    """
    return html

@app.post("/sincronizar-reportes")
async def sincronizar_reportes():
    if not MP_ACCESS_TOKEN:
        raise HTTPException(status_code=500, detail="Falta configurar la variable de entorno MP_ACCESS_TOKEN en Vercel")

    headers = {
        "Authorization": f"Bearer {MP_ACCESS_TOKEN}",
        "Accept": "application/json",
    }

    # Tomamos el tiempo actual de Argentina y ampliamos el rango a 24 horas para asegurar que no se pierda nada del día
    now_arg = datetime.now(TZ_ARG)
    begin_arg = now_arg - timedelta(hours=24)

    async with httpx.AsyncClient(timeout=30.0) as client:
        params = {"begin_date": iso_arg(begin_arg), "end_date": iso_arg(now_arg), "created_from": "manual", "limit": 10}
        
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
            payload = {"begin_date": iso_arg(begin_arg), "end_date": iso_arg(now_arg)}
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
            raise HTTPException(status_code=400, detail="El reporte se está generando en Mercado Pago. Volvé a hacer clic en unos segundos.")

        download_resp = await client.get(f"{API_BASE}/v1/account/settlement_report/{file_name}", headers=headers)
        if download_resp.status_code != 200:
            raise HTTPException(status_code=400, detail="No se pudo descargar el archivo de reporte.")

        text = download_resp.content.decode("utf-8", errors="replace")
        reader = csv.DictReader(io.StringIO(text), delimiter=';')
        
        nuevas_cantidades = 0
        for row in reader:
            p_id = str(row.get("SOURCE_ID") or "")
            monto_str = row.get("TRANSACTION_AMOUNT") or row.get("REAL_AMOUNT") or "0"
            
            try:
                monto = float(monto_str)
            except ValueError:
                monto = 0.0

            fecha_bruta = row.get("TRANSACTION_DATE") or ""
            
            # Convertimos la fecha cruda de Mercado Pago al huso horario de Argentina para que coincida con tu reloj
            if fecha_bruta:
                try:
                    # Parseamos la fecha que viene del CSV (remplazando la Z o interpretándola como UTC)
                    dt_parsed = datetime.fromisoformat(fecha_bruta.replace("Z", "+00:00"))
                    # La pasamos a hora Argentina
                    dt_arg = dt_parsed.astimezone(TZ_ARG)
                    fecha_limpia = dt_arg.strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    fecha_limpia = fecha_bruta.split(".")[0].replace("T", " ")
            else:
                fecha_limpia = "Sin fecha"

            if p_id and monto > 0 and not any(t["id"] == p_id for t in transacciones_memoria):
                transacciones_memoria.append({
                    "id": p_id,
                    "monto": abs(monto),
                    "fecha": fecha_limpia,
                    "entregado": False
                })
                nuevas_cantidades += 1

    return {"message": f"Sincronización exitosa. Se encontraron {nuevas_cantidades} transferencias nuevas."}

@app.post("/marcar-entregado/{payment_id}")
def marcar_entregado(payment_id: str):
    for t in transacciones_memoria:
        if t["id"] == payment_id:
            if t["entregado"]:
                raise HTTPException(status_code=400, detail="Ya entregado.")
            t["entregado"] = True
            return {"message": "Marcado como entregado"}
    raise HTTPException(status_code=404, detail="No encontrado")