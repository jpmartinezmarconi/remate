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

La conexión a la base de datos se configura mediante `DATABASE_URL` en `.env`. El valor local actual apunta a PostgreSQL; sustituye `host` por el hostname real de tu servidor. También puedes usar `sqlite:///app.db` para desarrollo local con SQLite.

El esquema inicial de la aplicación está versionado en `MiProyecto/migrations/`. Aplica las migraciones:

```bash
flask --app main db upgrade --directory MiProyecto/migrations
```

Para cambios posteriores, genera una migración con `flask --app main db migrate --directory MiProyecto/migrations -m "Descripción del cambio"` y luego aplica `flask --app main db upgrade --directory MiProyecto/migrations`. No se crean tablas automáticamente al arrancar.

Los modelos están en `models/`. Las rutas de autenticación están bajo `/auth/`; el inicio lista las subastas con fecha de cierre futura y cada detalle permite ofertar tras iniciar sesión.

## Despliegue en Render

El archivo `MiProyecto/render.yaml` configura el servicio Render que utiliza `MiProyecto` como Root Directory. El punto de entrada WSGI aplica las migraciones pendientes antes de aceptar solicitudes y el servicio comprueba `/api/health`. La aplicación y la interfaz siguen viviendo en la raíz del repositorio. Proporciona `DATABASE_URL` de una base PostgreSQL persistente y define `CORS_ORIGINS` con los orígenes permitidos separados por comas. Render genera `SECRET_KEY` automáticamente. No uses el servidor de desarrollo en producción.

## Estructura

- `app/`: fábrica Flask, rutas, modelos y extensión de base de datos.
- `templates/` y `static/`: interfaz web adaptable a móviles y recursos gráficos, incluido el logo de Remate Martínez y un QR de muestra no escaneable para el futuro bot de Telegram.
- `config.py`: configuración desde variables de entorno.
- `main.py`: punto de entrada local y WSGI.
