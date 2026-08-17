import os
import csv
import io
import asyncio
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, HTTPException, Request, Form, status
from fastapi.responses import HTMLResponse
import httpx
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

API_BASE = "https://api.mercadopago.com"

transacciones_memoria = []
config_memoria = {"mp_access_token": ""}

def iso_utc(dt: datetime) -> str:
    # Convierte a UTC exacto exigido por la API de Mercado Pago (terminado en 'Z')[cite: 3]
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

@app.get("/", response_class=HTMLResponse)
def home():
    token_actual = config_memoria.get("mp_access_token", "")

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
                input[type="text"] {{ padding: 8px; width: 450px; border: 1px solid #ccc; border-radius: 4px; font-size: 14px; }}
            </style>
        </head>
        <body>
            <h1>Control de Transferencias (CVU/Alias) 💸</h1>
            
            <div class="config-box">
                <h3>⚙️ Configuración de Credenciales</h3>
                <form onsubmit="guardarToken(event)">
                    <label for="token">Access Token de Mercado Pago:</label><br><br>
                    <input type="text" id="token" value="{token_actual}" placeholder="APP_USR-..." required>
                    <button type="submit" class="btn">Guardar Token</button>
                </form>
            </div>

            <button id="btn-sync" class="btn btn-success" onclick="sincronizar()">🔄 Buscar Nuevas Transferencias</button>
            <div id="status-sync"></div>
            <div id="panel">
    """
    
    if not transacciones_memoria:
        html += "<p>No hay transferencias cargadas. Configurá tu token y hacé clic en 'Buscar Nuevas Transferencias'.</p>"
    
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
                async function guardarToken(event) {
                    event.preventDefault();
                    let tokenVal = document.getElementById('token').value;
                    try {
                        let res = await fetch('/configurar-token', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                            body: 'token=' + encodeURIComponent(tokenVal)
                        });
                        let data = await res.json();
                        if(res.ok) {
                            alert(data.message);
                            location.reload();
                        } else {
                            alert('Error: ' + (data.detail || 'Token inválido o no se pudo verificar.'));
                        }
                    } catch (err) {
                        alert('Error de red al intentar guardar el token.');
                    }
                }

                async function sincronizar() {
                    let btn = document.getElementById('btn-sync');
                    let statusDiv = document.getElementById('status-sync');
                    
                    btn.disabled = true;
                    btn.style.background = '#ccc';
                    statusDiv.innerHTML = '<p><b>⏳ Consultando a Mercado Pago (generando reporte release_report)... Esperá unos segundos...</b></p>';

                    let intentos = 4;
                    let exito = false;

                    for (let i = 0; i < intentos; i++) {
                        try {
                            let res = await fetch('/sincronizar-reportes', { method: 'POST' });
                            let data = await res.json();
                            
                            if (res.ok) {
                                alert(data.message);
                                location.reload();
                                exito = true;
                                break;
                            } else {
                                if (i < intentos - 1) {
                                    statusDiv.innerHTML = `<p><b>⏳ El reporte se está procesando en Mercado Pago. Reintentando automáticamente (${i + 2}/${intentos})...</b></p>`;
                                    await new Promise(r => setTimeout(r, 6000));
                                } else {
                                    alert('Aviso: ' + (data.detail || 'Error al sincronizar'));
                                }
                            }
                        } catch (e) {
                            if (i === intentos - 1) {
                                alert('Error de red o timeout. Intentá de nuevo.');
                            }
                        }
                    }

                    if (!exito) {
                        statusDiv.innerHTML = '';
                        btn.disabled = false;
                        btn.style.background = '#28a745';
                    }
                }

                async function entregar(id) {
                    try {
                        let res = await fetch('/marcar-entregado/' + id, { method: 'POST' });
                        let data = await res.json();
                        if(res.ok) { 
                            location.reload(); 
                        } else { 
                            alert('Error: ' + (data.detail || 'No se pudo marcar como entregado')); 
                        }
                    } catch (err) {
                        alert('Error de red al intentar actualizar el estado.');
                    }
                }
            </script>
        </body>
    </html>
    """
    return html

@app.post("/configurar-token")
async def configurar_token(token: str = Form(...)):
    token_limpio = token.strip()
    if not token_limpio or len(token_limpio) < 10:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El token ingresado no tiene un formato válido.")

    headers = {
        "Authorization": f"Bearer {token_limpio}",
        "Accept": "application/json",
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            test_resp = await client.get(f"{API_BASE}/users/me", headers=headers)
            if test_resp.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, 
                    detail="Token inválido o rechazado por Mercado Pago. Verificá tus credenciales."
                )
        except httpx.RequestError:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, 
                detail="No se pudo conectar con Mercado Pago para validar el token."
            )

    config_memoria["mp_access_token"] = token_limpio
    logger.info("Token validado y guardado exitosamente.")
    return {"message": "Token verificado y guardado exitosamente."}

@app.post("/sincronizar-reportes")
async def sincronizar_reportes():
    try:
        token_actual = config_memoria.get("mp_access_token")
        if not token_actual:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Primero debés configurar tu Access Token de Mercado Pago en la interfaz.")

        headers = {
            "Authorization": f"Bearer {token_actual}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        # Generar rango de fechas en UTC con sufijo Z tal como exige /v1/account/release_report[cite: 3]
        now_utc = datetime.now(timezone.utc)
        begin_utc = now_utc - timedelta(days=7) # Ampliamos a 7 días para asegurar captura de transferencias recientes

        payload = {
            "begin_date": iso_utc(begin_utc),
            "end_date": iso_utc(now_utc)
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            # 1. Crear el reporte usando release_report según la documentación oficial[cite: 3]
            try:
                post_resp = await client.post(f"{API_BASE}/v1/account/release_report", json=payload, headers=headers)
                if post_resp.status_code in (401, 403):
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Token no autorizado para solicitar reportes de liberación.")
                if post_resp.status_code == 400:
                    err_data = post_resp.json() if post_resp.content else {}
                    logger.warning(f"Error 400 desde release_report: {err_data}")
            except HTTPException as he:
                raise he
            except Exception as post_err:
                logger.error(f"Excepción al solicitar release_report: {str(post_err)}")

            # 2. Buscar/Listar los reportes generados para obtener el nombre de archivo (file_name)
            file_name = None
            try:
                search_resp = await client.get(f"{API_BASE}/v1/account/settlement_report/search", headers=headers)
                if search_resp.status_code == 200:
                    reports = search_resp.json()
                    # Si devuelve una lista o un diccionario con resultados
                    lista_reports = reports if isinstance(reports, list) else (reports.get("results") or reports.get("data") or [])
                    for r in lista_reports:
                        if r.get("file_name"):
                            file_name = r["file_name"]
                            break
            except Exception as search_err:
                logger.error(f"Error al buscar reportes disponibles: {str(search_err)}")

            if not file_name:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El reporte de liberación se está generando en Mercado Pago. Volvé a reintentar en unos segundos.")

            # 3. Descargar el reporte usando el endpoint oficial GET /v1/account/settlement_report/{file_name}[cite: 4]
            try:
                download_resp = await client.get(f"{API_BASE}/v1/account/settlement_report/{file_name}", headers=headers)
            except httpx.RequestError as down_err:
                logger.error(f"Fallo de red al descargar reporte: {str(down_err)}")
                raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Error de red al intentar descargar el reporte.")

            if download_resp.status_code != 200:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No se pudo descargar el archivo de reporte. Verificá que tu token sea correcto.")

            text = download_resp.content.decode("utf-8", errors="replace")
            reader = csv.DictReader(io.StringIO(text), delimiter=',')
            
            nuevas_cantidades = 0
            for row in reader:
                try:
                    p_id = str(row.get("SOURCE_ID") or row.get("ID") or "")
                    monto_str = row.get("TRANSACTION_AMOUNT") or row.get("NET_CREDIT_AMOUNT") or row.get("GROSS_AMOUNT") or "0"
                    
                    try:
                        monto = float(monto_str)
                    except ValueError:
                        monto = 0.0

                    fecha_bruta = row.get("TRANSACTION_DATE") or row.get("DATE") or ""
                    fecha_limpia = fecha_bruta.replace("T", " ").replace("Z", "") if fecha_bruta else "Sin fecha"

                    if p_id and monto > 0 and not any(t["id"] == p_id for t in transacciones_memoria):
                        transacciones_memoria.append({
                            "id": p_id,
                            "monto": abs(monto),
                            "fecha": fecha_limpia,
                            "entregado": False
                        })
                        nuevas_cantidades += 1
                except Exception as row_err:
                    logger.warning(f"Error procesando fila del CSV: {str(row_err)}")
                    continue

        return {"message": f"Sincronización exitosa. Se encontraron {nuevas_cantidades} transferencias nuevas."}

    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Error crítico en sincronización: {str(e)}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Ocurrió un error inesperado al procesar la sincronización con Mercado Pago.")

@app.post("/marcar-entregado/{payment_id}")
def marcar_entregado(payment_id: str):
    try:
        for t in transacciones_memoria:
            if t["id"] == payment_id:
                if t["entregado"]:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La transacción ya figura como entregada.")
                t["entregado"] = True
                return {"message": "Marcado como entregado correctamente."}
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transacción no encontrada.")
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Error al marcar como entregado ({payment_id}): {str(e)}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Error interno al actualizar el estado de la transacción.")