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

La conexión a la base de datos se configura mediante `DATABASE_URL` en `.env`. También puedes usar `sqlite:///app.db` para desarrollo local con SQLite. En Render configura `DATABASE_URL` con la URL PostgreSQL persistente de Neon en el servicio web. La aplicación se niega a iniciar en Render si falta esta variable o apunta a SQLite: el disco local de Render es efímero y puede perder los lotes al desplegar.

El esquema de la aplicación está versionado en `MiProyecto/migrations/`. En local, aplica las migraciones:

```bash
flask --app main db upgrade --directory MiProyecto/migrations
```

Para cambios posteriores, genera una migración con `flask --app main db migrate --directory MiProyecto/migrations -m "Descripción del cambio"` y luego aplica `flask --app main db upgrade --directory MiProyecto/migrations`. El punto de entrada WSGI de Render aplica las migraciones pendientes al iniciar.

Los modelos están en `models/`. La comisión general es del 20% y se propone como valor inicial para cada nuevo lote; el porcentaje se puede revisar para cada artículo y el valor publicado en su ficha es el aplicable. En el área privada se crean grupos de venta independientes y luego se asignan lotes a cada grupo; los grupos y lotes sin historial de pujas o pagos se pueden eliminar individualmente o en conjunto. La portada muestra un máximo de cinco grupos y cinco lotes destacados por grupo; `/subastas-activas` muestra solo las pujas en curso y `/proximas-subastas` lista los lotes que aún no comenzaron. Los lotes finalizados con ofertas aparecen como subastados en el archivo de la página de subastas activas.

Las subastas duran de 1 a 168 horas enteras (máximo 7 días). Las fichas y tarjetas de subastas activas muestran una cuenta regresiva que se resalta en rojo durante el último minuto. La primera oferta puede igualar el precio base o ser cualquier importe superior; desde la segunda puja se aplican incrementos según el precio actual: $U 50 hasta $U 500, $U 100 por encima de $U 500 y hasta $U 2.000, $U 500 por encima de $U 2.000 y hasta $U 10.000, y $U 1.000 por encima de $U 10.000. En ventas por unidades, estos importes son por unidad. Quien tenga la oferta más alta no puede volver a ofertar hasta que otro participante la supere.

## Mi cuenta y pagos

Si un cliente olvida su contraseña, puede solicitar un enlace de recuperación por correo desde la página de ingreso. El enlace firmado vence en una hora y solo puede usarse una vez; el envío requiere la configuración SMTP existente.

Las cuentas nuevas registran nombre completo, teléfono, dirección de envío, ciudad y código postal; los usuarios existentes pueden completar sus datos en `/cuenta`. El perfil completo es necesario para ofertar. El panel incluye el historial de participación y las subastas ganadas. Los usuarios pueden guardar artículos favoritos; la página principal presenta sus favoritos y los últimos ocho artículos vistos en ese navegador. Tras una puja exitosa se sugieren hasta cuatro lotes activos o próximos del mismo grupo y, si faltan, de otros grupos. Si otro participante supera una oferta, se envía un correo al usuario desplazado; los avisos se procesan cada cinco minutos. Quienes pujen reciben además un único correo cuando el cierre esté a entre 25 y 30 minutos, además del aviso de inicio de subasta al que se suscriban. Cada puja aceptada y cada compra registrada también generan un aviso inmediato a `CONTACT_EMAIL` (en Render, `inforemateonline@gmail.com`). Al finalizar cada subasta se envía un único correo a ese mismo destino, haya tenido ofertas o no. Si hubo ganador, el aviso incluye sus datos de contacto, la oferta y el estado del pago para coordinar la entrega; si no hubo ofertas, indica que se puede evaluar republicar el lote. Los cierres se procesan junto con los demás avisos programados cada cinco minutos. Tras el cierre, el ganador registra una transferencia al BROU (cuenta Nº 001901236, JUAN MARTINEZ) o a Mi Dinero Red Pagos (cuenta Nº 9102129). El pago queda pendiente hasta su confirmación. El total suma al precio final la comisión publicada para el lote (20% por defecto), multiplicando por la cantidad si se subasta por unidades.

## Área privada

El área privada incluye las secciones «Historial de pujas», con ofertas y datos de contacto de cada participante; «Ventas», con lotes cerrados que tuvieron pujas y sus ofertas ganadoras; y «Clientes registrados», con los datos de las cuentas. Todas requieren iniciar sesión en el área privada. La página «Ventas» también permite elegir el destinatario de un correo HTML de prueba de ganador, sin crear una subasta, puja ni pago.

`/area-privada` permite crear grupos de ventas independientes y asignarles lotes con número, precio base, comisión porcentual, modalidad de venta, cantidad, duración en horas enteras (máximo 168), fotos y fecha de inicio. Desde la lista de lotes se puede abrir cada uno para editar sus datos, sustituir o agregar fotos y guardar los cambios. Si un lote ya tiene pujas o pagos, se pueden corregir su título, descripción y fotos, pero se protegen los datos de la ronda anterior para conservar el historial. Una vez finalizado, también se puede volver a publicar desde su edición con número, descripción, precio y modalidad nuevos, eligiendo iniciar el remate ahora o programarlo para que aparezca como “Próximamente”. Se crea una nueva ronda independiente con cuenta regresiva e historial propios, copiando las fotos y manteniendo intacta la anterior. Se pueden eliminar grupos y lotes, salvo que tengan pujas o pagos asociados; el historial se conserva. Las fechas se ingresan en hora de Uruguay. Las cuentas registradas pueden pedir un recordatorio por email 24 horas antes; si se suscriben dentro de las últimas 24 horas, el aviso se envía en el siguiente ciclo programado. Desde el panel se eligen los lotes destacados de cada grupo. Configura `PASSWORD_AREA_PRIVADA` como variable de entorno local o de Render; no guardes contraseñas en Git. Las fotos se almacenan en la base de datos para persistir con Neon, sin límite de cantidad y con un máximo de 8 MB por archivo. Solo se aceptan JPG, PNG, GIF y WebP.

## Asistente de ayuda

El botón «¿Necesitás ayuda?» abre un asistente en el sitio. Responde preguntas frecuentes sobre cómo participar, plazos, comisión, pagos, dirección y contacto; también consulta las subastas activas y próximas y busca lotes por número. Las respuestas de subastas usan los datos publicados en la base de datos. Es un asistente guiado por temas, no utiliza un servicio de IA externo; si no reconoce una consulta, ofrece los canales de contacto.

## Bot de Telegram

El bot `@rematemartinezbot` usa un webhook HTTPS (`/telegram/webhook`) y el mismo asistente de ayuda del sitio. En Render, configura `TELEGRAM_BOT_TOKEN` con el token de BotFather y `TELEGRAM_WEBHOOK_SECRET` con un valor aleatorio de 1 a 256 letras, números, guiones o guiones bajos. Para recibir avisos al finalizar subastas, iniciá un chat privado con el bot, enviá `/id` y guardá el número que responde como `TELEGRAM_NOTIFICATION_CHAT_ID` en Render. No compartas ni guardes el token o el identificador de chat en Git. `PUBLIC_BASE_URL` debe apuntar a la URL HTTPS del servicio (Render la expone como `RENDER_EXTERNAL_URL` si no se define).

Después de desplegar y cargar esas variables, ejecuta desde el directorio `MiProyecto` en la consola de Render:

```bash
python set_telegram_webhook.py
```

El script registra la URL segura del webhook y los comandos `/start`, `/help` y `/id`. Para volver a registrar el webhook tras cambiar el dominio o el secreto, ejecuta el comando nuevamente.

## Despliegue en Render

Render sirve la aplicación web y Neon almacena la base de datos PostgreSQL. Configura `DATABASE_URL` y `REMINDER_TRIGGER_SECRET` en el servicio web de Render; no uses SQLite en producción. Para los avisos por email, una Neon Function llama al endpoint privado `/api/internal/process-reminders` cada cinco minutos. Configura `gmail_SMTP` en Render con la contraseña de aplicación de `inforematemartinez@gmail.com`; se utiliza SMTP de Gmail en el puerto `587` con STARTTLS. Esta variable tiene prioridad sobre la configuración SMTP anterior. El destino de los avisos de gestión se configura por separado en `CONTACT_EMAIL`. `PUBLIC_BASE_URL` se usa para los enlaces de recordatorios. No guardes contraseñas en el repositorio. Render genera `SECRET_KEY` automáticamente. No uses el servidor de desarrollo en producción.

### Programar avisos por email con Neon

Desde `MiProyecto`, instala la CLI de Neon (`npm install -g neon@latest`), inicia sesión con `neon login` y enlaza el proyecto con `neon link`. Crea un secreto aleatorio con `python -c "import secrets; print(secrets.token_urlsafe(32))"` y configura el mismo valor, sin publicarlo, como `REMINDER_TRIGGER_SECRET` en el servicio web de Render. En Render, configura `gmail_SMTP` con la contraseña de aplicación de Gmail y revisa `CONTACT_EMAIL`, `PUBLIC_BASE_URL` y `TELEGRAM_NOTIFICATION_CHAT_ID`.

Con el repositorio actualizado, ejecuta el script una vez desde PowerShell para desplegar la función y registrar el disparador cada cinco minutos (UTC). El script solicita el secreto de forma oculta:

```powershell
.\deploy_neon_reminders.ps1
```

No guardes la clave en Git ni la compartas por chat. La ruta rechaza solicitudes sin la clave válida y la función solo acepta invocaciones con el encabezado de Neon.

## Estructura

- `app/`: fábrica Flask, rutas, modelos y extensión de base de datos.
- `templates/` y `static/`: interfaz web adaptable a móviles y recursos gráficos, incluido el logo de Remate Martínez y el acceso al bot de Telegram.
- `config.py`: configuración desde variables de entorno.
- `main.py`: punto de entrada local y WSGI.
