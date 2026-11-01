# MiProyecto

Aplicación web mínima con Flask y Flask-SQLAlchemy, preparada para desarrollo local y despliegue en Render.

## Requisitos

- Python 3.10 o superior
- `pip`

## Ejecutar localmente

Desde esta carpeta, crea y activa un entorno virtual, instala las dependencias y ejecuta la aplicación:

```sh
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
flask --app main init-db
flask --app main run --debug
```

Abre <http://127.0.0.1:5000>. La ruta `/health` devuelve el estado de salud en JSON.

El archivo `.env` contiene valores de desarrollo. `DATABASE_URL` admite SQLite para local y URLs PostgreSQL para producción. No uses la clave secreta de desarrollo en un entorno publicado.

## Base de datos

El modelo de ejemplo `Task` está en `app/models.py`. Las tablas se crean con `flask --app main init-db`; este comando es idempotente y no borra los datos existentes. Si no se define `DATABASE_URL`, se usa un archivo SQLite local. Los esquemas PostgreSQL `postgres://` y `postgresql://` se adaptan automáticamente a Psycopg 3.

## Desplegar en Render

1. Selecciona el repositorio `jpmartinezmarconi/remate` al crear el servicio.
2. Configura **Root Directory** como `MiProyecto`.
3. Usa `pip install -r requirements.txt` para compilar y `gunicorn wsgi:app` para iniciar.
4. Configura `DATABASE_URL` con una URL de PostgreSQL y comprueba la ruta `/health`.

No guardes secretos ni valores reales de conexión en el repositorio.

## Estructura

- `app/__init__.py`: fábrica de aplicación y comando de inicialización de base de datos.
- `app/routes.py`: rutas web y comprobación de salud.
- `app/models.py`: modelo de ejemplo `Task`.
- `app/database.py`: instancia compartida de SQLAlchemy.
- `config.py`: carga de `.env` y configuración de la aplicación.
- `main.py`: punto de entrada local.
- `wsgi.py`: punto de entrada WSGI para Gunicorn.
- `static/` y `templates/`: recursos estáticos y plantilla principal.
- `render.yaml`: configuración de servicio independiente.
