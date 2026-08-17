import os
from datetime import datetime
from zoneinfo import ZoneInfo
from fastapi import FastAPI, HTTPException, Request, Form, status
from fastapi.responses import HTMLResponse, JSONResponse
import httpx
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

API_BASE = "https://api.mercadopago.com"

# Almacenamiento en memoria de las transferencias notificadas
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
                .info-box {{ background: #e7f3fe; border-left: 5px solid #2196F3; padding: 15px; margin-bottom: 20px; border-radius: 8px; }}
                .btn {{ background: #009ee3; color: white; border: none; padding: 10px 15px; border-radius: 5px; cursor: pointer; font-size: 16px; text-decoration: none; display: inline-block; }}
                .btn-success {{ background: #28a745; }}
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

            <div class="info-box">
                <h3>📢 Configuración de Webhooks en Mercado Pago</h3>
                <p>Para recibir transferencias por CVU/Alias automáticamente en tiempo real, configurá en tu panel de desarrollador de Mercado Pago la URL de notificación (Webhook) apuntando a:</p>
                <p><b>https://tu-dominio.vercel.app/webhook</b></p>
                <p><i>(Tipos de eventos a suscribir: <code>payment</code>)</i></p>
            </div>
            
            <h3>📋 Transferencias Registradas</h3>
    """
    
    if not transacciones_memoria:
        html += "<p>No hay transferencias registradas todavía. Las transferencias aparecerán aquí automáticamente en cuanto lleguen las notificaciones de Mercado Pago.</p>"
    
    for t in transacciones_memoria:
        estado = "✅ ENTREGADO" if t["entregado"] else "⏳ DISPONIBLE PARA RETIRAR"
        boton = f'<button class="btn btn-disabled" disabled>Ya entregado</button>' if t["entregado"] else f'<button class="btn" onclick="entregar(\'{t["id"]}\')">Marcar como Entregado</button>'
        
        html += f"""
        <div class="card">
            <p>ID / Operación: <b>{t["id"]}</b></p>
            <p>Fecha: <b>{t["fecha"]}</b></p>
            <p>Monto: <b>${t["monto"]}</b></p>
            <p>Estado: {estado}</p>
            {boton}
        </div>
        """

    html += """
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
                            alert('Error: ' + (data.detail || 'Token inválido.'));
                        }
                    } catch (err) {
                        alert('Error de red al guardar el token.');
                    }
                }

                async function entregar(id) {
                    try {
                        let res = await fetch('/marcar-entregado/' + id, { method: 'POST' });
                        let data = await res.json();
                        if(res.ok) { 
                            location.reload(); 
                        } else { 
                            alert('Error: ' + (data.detail || 'No se pudo actualizar')); 
                        }
                    } catch (err) {
                        alert('Error de red.');
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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Token no válido.")

    headers = {"Authorization": f"Bearer {token_limpio}", "Accept": "application/json"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            test_resp = await client.get(f"{API_BASE}/users/me", headers=headers)
            if test_resp.status_code != 200:
                raise HTTPException(status_code=400, detail="Token rechazado por Mercado Pago.")
        except httpx.RequestError:
            raise HTTPException(status_code=503, detail="Error de conexión con Mercado Pago.")

    config_memoria["mp_access_token"] = token_limpio
    return {"message": "Token verificado y guardado exitosamente."}

@app.post("/webhook")
async def recibir_webhook(request: Request):
    """Endpoint oficial que recibe las notificaciones instantáneas de Mercado Pago"""
    try:
        body = await request.json()
        logger.info(f"Webhook recibido de MP: {body}")

        action = body.get("action")
        data = body.get("data", {})
        payment_id = data.get("id")

        # Si el evento es de pago creado/actualizado
        if payment_id and (action == "payment.created" or action == "payment.updated" or body.get("type") == "payment"):
            token_actual = config_memoria.get("mp_access_token")
            if not token_actual:
                return {"status": "ignored_no_token"}

            # Consultamos los detalles específicos de ese pago mediante la API
            async with httpx.AsyncClient(timeout=10.0) as client:
                headers = {"Authorization": f"Bearer {token_actual}", "Accept": "application/json"}
                resp = await client.get(f"{API_BASE}/v1/payments/{payment_id}", headers=headers)
                
                if resp.status_code == 200:
                    p = resp.json()
                    if p.get("status") == "approved":
                        p_id = str(p.get("id"))
                        monto = float(p.get("transaction_amount", 0))
                        
                        fecha_bruta = p.get("date_approved") or p.get("date_created") or ""
                        try:
                            dt_parsed = datetime.fromisoformat(fecha_bruta.replace("Z", "+00:00"))
                            dt_arg = dt_parsed.astimezone(TZ_ARG)
                            fecha_limpia = dt_arg.strftime("%Y-%m-%d %H:%M:%S")
                        except Exception:
                            fecha_limpia = fecha_bruta.split(".")[0].replace("T", " ")

                        # Evitar duplicados
                        if p_id and not any(t["id"] == p_id for t in transacciones_memoria):
                            transacciones_memoria.append({
                                "id": p_id,
                                "monto": abs(monto),
                                "fecha": fecha_limpia or "Hace un momento",
                                "entregado": False
                            })
                            logger.info(f"¡Transferencia registrada exitosamente! ID: {p_id} - Monto: ${monto}")

        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Error procesando webhook: {str(e)}")
        return {"status": "error"}

@app.post("/marcar-entregado/{payment_id}")
def marcar_entregado(payment_id: str):
    for t in transacciones_memoria:
        if t["id"] == payment_id:
            if t["entregado"]:
                raise HTTPException(status_code=400, detail="Ya fue entregado.")
            t["entregado"] = True
            return {"message": "Actualizado correctamente."}
    raise HTTPException(status_code=404, detail="No encontrado.")