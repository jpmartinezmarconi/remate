# Remate Martínez Online

Plataforma web de subastas construida con Flask, SQLAlchemy y PostgreSQL. Incluye registro e inicio de sesión, sesiones seguras, listado de lotes activos y pujas autenticadas con validación del precio actual. En local puede usarse SQLite; en producción se configura PostgreSQL por variables de entorno.

## Requisitos

- Python 3.10 o posterior
- PostgreSQL para producción (opcional en local)

## Desarrollo local

1. Crea y activa un entorno virtual:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

   En Windows PowerShell, activa con `.venv\\Scripts\\Activate.ps1`.

2. Instala dependencias:

   ```bash
   pip install -r requirements.txt
   ```

3. Revisa `.env` y sustituye los valores locales si lo necesitas. No guardes secretos reales en Git.

4. Inicia el servidor de desarrollo:

   ```bash
   python main.py
   ```

   Abre `http://127.0.0.1:5000`. El endpoint de comprobación está en `/api/health`.

## Base de datos y migraciones

La conexión a la base de datos se configura mediante `DATABASE_URL` en `.env`. También puedes usar `sqlite:///app.db` para desarrollo local con SQLite.

El esquema de la aplicación está versionado en `MiProyecto/migrations/`. En local, aplica las migraciones:

```bash
flask --app main db upgrade --directory MiProyecto/migrations
```

Para cambios posteriores, genera una migración con `flask --app main db migrate --directory MiProyecto/migrations -m "Descripción del cambio"` y luego aplica `flask --app main db upgrade --directory MiProyecto/migrations`. El punto de entrada WSGI de Render aplica las migraciones pendientes al iniciar.

Los modelos están en `models/`. El inicio muestra un máximo de cinco grupos y cinco lotes destacados por grupo; `/subastas-activas` muestra las subastas activas y las próximas. Las pujas por unidades se expresan por unidad y adjudican toda la cantidad al ganador. Las ofertas actuales se muestran cuando un lote ya recibió pujas.

## Mi cuenta y pagos

Las cuentas nuevas registran nombre completo, teléfono, dirección de envío, ciudad y código postal; los usuarios existentes pueden completar sus datos en `/cuenta`. El perfil completo es necesario para ofertar. El panel incluye el historial de participación y las subastas ganadas. Tras el cierre, el ganador puede registrar tarjeta, transferencia o MercadoPago como método elegido. El estado permanece pendiente de confirmación: esta versión no procesa cargos ni almacena datos de tarjetas. El total mostrado suma la comisión del lote a la oferta ganadora, multiplicando por la cantidad si se subasta por unidades.

## Área privada

`/area-privada` permite crear lotes, asignar número, grupo, precio base, comisión porcentual, modalidad de venta, cantidad, duración, fotos y fecha de inicio. Las fechas se ingresan en hora de Uruguay. Los artículos futuros se publican como “Próximamente”; las cuentas registradas pueden pedir un recordatorio por email 24 horas antes. Si se suscriben dentro de las últimas 24 horas, el aviso se envía en el siguiente ciclo programado. Desde el panel se eligen los lotes destacados de cada grupo. Configura `PASSWORD_AREA_PRIVADA` como variable de entorno local o de Render; no guardes contraseñas en Git. Las fotos se almacenan en la base de datos para persistir con Neon, sin límite de cantidad y con un máximo de 8 MB por archivo. Solo se aceptan JPG, PNG, GIF y WebP.

## Despliegue en Render

El archivo `MiProyecto/render.yaml` configura el servicio Render que utiliza `MiProyecto` como Root Directory y un Cron Job que revisa recordatorios cada cinco minutos. El punto de entrada WSGI aplica las migraciones pendientes antes de aceptar solicitudes y el servicio comprueba `/api/health`. Proporciona `DATABASE_URL` de Neon y `PASSWORD_AREA_PRIVADA` como variables del servicio web. Configura `SMTP_HOST`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL` y `PUBLIC_BASE_URL` en el Cron Job. El puerto SMTP predeterminado es 587 (STARTTLS). Render genera `SECRET_KEY` automáticamente. No uses el servidor de desarrollo en producción.

## Estructura

- `app/`: fábrica Flask, rutas, modelos y extensión de base de datos.
- `templates/` y `static/`: interfaz web adaptable a móviles y recursos gráficos, incluido el logo de Remate Martínez y un QR de muestra no escaneable para el futuro bot de Telegram.
- `config.py`: configuración desde variables de entorno.
- `main.py`: punto de entrada local y WSGI.
