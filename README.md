# MiProyecto

Aplicación inicial con Flask, Flask-SQLAlchemy y soporte para PostgreSQL. En desarrollo local usa SQLite por defecto; en Render se configura la conexión mediante variables de entorno.

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

## Base de datos

La configuración local usa `sqlite:///mi_proyecto.db` (archivo en `instance/`). Para PostgreSQL, define `DATABASE_URL` en `.env`; por ejemplo, `postgresql://usuario:contraseña@localhost:5432/mi_proyecto`.

El modelo de ejemplo está en `app/models.py`. Para un proyecto real, añade migraciones con Flask-Migrate antes de gestionar cambios de esquema; no se crean tablas automáticamente al arrancar.

## Despliegue en Render

El archivo `render.yaml` configura el servicio web, Gunicorn y la ruta de salud. Al crear el servicio, proporciona `DATABASE_URL` de una base PostgreSQL y define `CORS_ORIGINS` con los orígenes permitidos separados por comas. Render genera `SECRET_KEY` automáticamente. No uses el servidor de desarrollo en producción.

## Estructura

- `app/`: fábrica Flask, rutas, modelos y extensión de base de datos.
- `templates/` y `static/`: interfaz web.
- `config.py`: configuración desde variables de entorno.
- `main.py`: punto de entrada local y WSGI.
