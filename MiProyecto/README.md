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

El archivo `.env` contiene valores de desarrollo. `DATABASE_URL` admite SQLite para local y URLs PostgreSQL para producción. En Render, configura `DATABASE_URL` con una base PostgreSQL persistente de Neon en el servicio web. La aplicación se niega a iniciar en Render si falta la variable o apunta a SQLite, cuyo almacenamiento local puede perderse al desplegar. Configura `PASSWORD_AREA_PRIVADA` localmente y como variable de entorno en Render; no guardes contraseñas en Git. No uses la clave secreta de desarrollo en un entorno publicado.

## Base de datos

El esquema de la aplicación se aplica con `flask --app main db upgrade`. La configuración de SQLite local y PostgreSQL se lee desde el directorio raíz del repositorio. En Render, `wsgi.py` aplica las migraciones pendientes al iniciar. Las fotos de los lotes se guardan en la base de datos persistente, con un máximo de 8 MB por foto y sin límite en la cantidad.

El área privada `/area-privada` permite crear grupos de ventas independientes y asignarles lotes, administrar comisión, modalidad, cantidad, fotos e inicio programado en hora de Uruguay. Las subastas duran de 1 a 168 horas enteras (máximo 7 días) y sus fichas y tarjetas muestran una cuenta regresiva que se resalta en rojo durante el último minuto. Los grupos y lotes se pueden eliminar si no tienen pujas o pagos registrados, para conservar el historial. La primera oferta puede igualar el precio base o superar ese monto libremente; desde la segunda puja se aplican incrementos de $U 50 hasta $U 500, $U 100 hasta $U 2.000, $U 500 hasta $U 10.000 y $U 1.000 por encima de ese valor, según el precio actual. Al finalizar un lote con historial, se puede relanzar desde su edición con un nuevo número, descripción y precio, eligiendo publicarlo ahora o programarlo para que aparezca como “Próximamente”; la nueva ronda tiene cuenta regresiva propia y conserva el historial anterior. La portada admite hasta cinco grupos y cinco lotes destacados por grupo; `/subastas-activas` muestra solo lotes en curso y `/proximas-subastas` los que aún no comenzaron. Los lotes cerrados que recibieron ofertas se conservan en la sección «Lotes subastados» de la página activa. Las cuentas registradas pueden suscribirse a recordatorios por correo 24 horas antes. La Neon Function `auctionreminders` llama al endpoint privado de Render cada cinco minutos para procesar recordatorios, avisos de cierre y avisos de pujas superadas.

El área privada también incluye secciones para consultar todas las pujas con los datos de contacto de cada participante y todas las cuentas de clientes registradas. El acceso a ambas requiere autenticarse en `/area-privada`.

El panel de usuario `/cuenta` permite actualizar sus datos, revisar las subastas en que participó y las ganadas, y registrar una forma de pago para los lotes adjudicados. Los usuarios pueden marcar artículos favoritos y verlos en Inicio; también se muestran los últimos ocho artículos visitados en el mismo navegador. Tras pujar correctamente se recomiendan hasta cuatro lotes del mismo grupo, completados con otros disponibles. Si otra persona supera una oferta, se avisa por correo al participante desplazado; la Neon Function procesa esos avisos cada cinco minutos. También avisa por correo a cada participante cuando faltan entre 25 y 30 minutos para el cierre, una sola vez por lote y usuario. El ganador puede elegir transferencia al BROU (cuenta Nº 001901236, JUAN MARTINEZ) o a Mi Dinero Red Pagos (cuenta Nº 9102129); el pago queda pendiente de confirmación.

Si un cliente olvida su contraseña, puede solicitar desde Ingresar un enlace firmado de recuperación por correo; vence en una hora y es de un solo uso. Requiere la configuración SMTP del servicio.

Si un cliente olvida su contraseña, puede solicitar desde Ingresar un enlace firmado de recuperación por correo; vence en una hora y es de un solo uso. Requiere la configuración SMTP del servicio.

La portada explica el funcionamiento del remate, incluyendo la comisión general del 20% (se verifica el porcentaje propio de cada lote), la modalidad por lote o por unidad, y las opciones de envío y retiro. El menú principal presenta Inicio, Ingresar/Crear cuenta (o Mi cuenta), Subastas activas, Próximas subastas, Cómo funciona, Contacto y Área privada, en ese orden. Su barra utiliza cristal translúcido con reflejos neón azules y rojos.

El botón «¿Necesitás ayuda?» abre un asistente de preguntas frecuentes que responde con información del sitio y consulta los lotes publicados en la base de datos. No utiliza servicios de IA externos.

El bot `@rematemartinezbot` comparte esas respuestas mediante el webhook HTTPS `/telegram/webhook`. Configura `TELEGRAM_BOT_TOKEN` (token de BotFather) y `TELEGRAM_WEBHOOK_SECRET` como secretos del servicio web de Render. Tras desplegar y configurar ambas variables, ejecuta `python set_telegram_webhook.py` desde este directorio para registrar el webhook y los comandos `/start` y `/help`. No publiques el token ni lo envíes por chat.

## Desplegar en Render

1. Selecciona el repositorio `jpmartinezmarconi/remate`.
2. Configura **Root Directory** como `MiProyecto`.
3. Usa `pip install -r requirements.txt` para compilar y `gunicorn wsgi:app` para iniciar.
4. Configura `DATABASE_URL`, `REMINDER_TRIGGER_SECRET`, `PASSWORD_AREA_PRIVADA`, `TELEGRAM_BOT_TOKEN` y `TELEGRAM_WEBHOOK_SECRET` como variables del servicio web. Para enviar recordatorios y avisos de pujas superadas, configura `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL` y `PUBLIC_BASE_URL` en ese mismo servicio. El punto de entrada WSGI aplica las migraciones pendientes antes de aceptar solicitudes. La Neon Function y su disparador se despliegan con `deploy_neon_reminders.ps1`.

No guardes secretos ni valores reales de conexión en el repositorio.

## Estructura

- `main.py`: adapta la configuración de Root Directory de Render a la aplicación del repositorio.
- `wsgi.py`: punto de entrada WSGI para Gunicorn.
- `render.yaml`: dependencias, migraciones y comprobación de salud del servicio.
- `render.yaml`: configuración de servicio independiente.
