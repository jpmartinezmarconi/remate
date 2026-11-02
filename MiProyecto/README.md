# Remate Martínez Online

Entrada de despliegue para la aplicación Flask del repositorio. La fábrica, las rutas, los modelos, las plantillas y los recursos estáticos se mantienen en el directorio raíz; `main.py` carga esa aplicación para conservar la configuración actual de Render con `MiProyecto` como Root Directory.

## Requisitos

- Python 3.10 o superior
- `pip`

## Ejecutar localmente

Desde esta carpeta, crea y activa un entorno virtual, instala las dependencias y ejecuta la aplicación compartida:

```sh
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
flask --app main init-db
flask --app main run --debug
```

Abre <http://127.0.0.1:5000>. La ruta `/api/health` devuelve el estado de salud en JSON.

El archivo `.env` contiene valores de desarrollo. `DATABASE_URL` admite SQLite para local y URLs PostgreSQL para producción. Configura `PRIVATE_AREA_PASSWORD` localmente y también como variable de entorno en Render; no guardes contraseñas en Git. No uses la clave secreta de desarrollo en un entorno publicado.

## Base de datos

El esquema de la aplicación se aplica con `flask --app main db upgrade`. La configuración de SQLite local y PostgreSQL se lee desde el directorio raíz del repositorio. En Render, `wsgi.py` aplica las migraciones pendientes al iniciar. Las fotos de los lotes se guardan en la base de datos persistente, con un máximo de 8 MB por foto y sin límite en la cantidad.

El área privada `/area-privada` permite administrar los lotes, grupos, comisión, modalidad de venta, cantidad, fotos, duración e inicio programado en hora de Uruguay. La portada admite hasta cinco grupos y cinco lotes destacados por grupo; `/subastas-activas` lista lotes activos y próximos. Las cuentas registradas pueden suscribirse a recordatorios por correo 24 horas antes. El Cron Job definido en `render.yaml` ejecuta `send_auction_reminders.py` cada cinco minutos; configura allí `SMTP_HOST`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL` y `PUBLIC_BASE_URL`.

El panel de usuario `/cuenta` permite actualizar sus datos, revisar las subastas en que participó y las ganadas, y registrar una forma de pago para los lotes adjudicados. Tarjeta, transferencia y MercadoPago quedan como solicitudes pendientes; no se procesan cobros ni se guardan datos de tarjetas.

## Desplegar en Render

1. Selecciona el repositorio `jpmartinezmarconi/remate`.
2. Configura **Root Directory** como `MiProyecto`.
3. Usa `pip install -r requirements.txt` para compilar y `gunicorn wsgi:app` para iniciar.
4. Configura `DATABASE_URL` con una URL de PostgreSQL y `PRIVATE_AREA_PASSWORD` con la clave elegida. Para crear recordatorios, configura las credenciales SMTP y `PUBLIC_BASE_URL` en el Cron Job. El punto de entrada WSGI aplica las migraciones pendientes antes de aceptar solicitudes.

No guardes secretos ni valores reales de conexión en el repositorio.

## Estructura

- `main.py`: adapta la configuración de Root Directory de Render a la aplicación del repositorio.
- `wsgi.py`: punto de entrada WSGI para Gunicorn.
- `render.yaml`: dependencias, migraciones y comprobación de salud del servicio.
- `render.yaml`: configuración de servicio independiente.
