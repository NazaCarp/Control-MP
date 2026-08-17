import os
import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
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

TZ_ARG = ZoneInfo("America/Argentina/Buenos_Aires")

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
                    statusDiv.innerHTML = '<p><b>⏳ Consultando pagos en tiempo real... Esperá un momento...</b></p>';

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
            "Accept": "application/json",
        }

        # Consultamos directamente la API de pagos en tiempo real (últimos 3 días)
        async with httpx.AsyncClient(timeout=30.0) as client:
            params = {
                "limit": 30,
                "sort": "date_approved",
                "criteria": "desc"
            }
            
            try:
                resp = await client.get(f"{API_BASE}/v1/payments/search", params=params, headers=headers)
            except httpx.RequestError as req_err:
                logger.error(f"Fallo de conexión con Mercado Pago (payments): {str(req_err)}")
                raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="No se pudo conectar con los servidores de Mercado Pago.")
            
            if resp.status_code in (401, 403):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Token no autorizado o vencido. Verificá tus credenciales.")
            
            if resp.status_code != 200:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Error al consultar pagos (Código {resp.status_code}).")

            data = resp.json()
            results = data.get("results", [])

            nuevas_cantidades = 0
            for p in results:
                try:
                    # Filtramos solo pagos aprobados
                    if p.get("status") != "approved":
                        continue

                    p_id = str(p.get("id"))
                    monto = float(p.get("transaction_amount", 0))
                    
                    # Fecha de aprobación
                    fecha_bruta = p.get("date_approved") or p.get("date_created") or ""
                    if fecha_bruta:
                        try:
                            dt_parsed = datetime.fromisoformat(fecha_bruta.replace("Z", "+00:00"))
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
                except Exception as row_err:
                    logger.warning(f"Error procesando un pago: {str(row_err)}")
                    continue

        return {"message": f"Sincronización exitosa. Se encontraron {nuevas_cantidades} transferencias nuevas en tiempo real."}

    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Error crítico en sincronización: {str(e)}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Ocurrió un error inesperado al procesar la sincronización.")

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