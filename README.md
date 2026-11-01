# libra-backoffice

Backoffice de superadmin **compartido** por los seis productos de la familia
Libra: Contalibra, Restolibra, VentaLibra, Gestiolibra, MedLibra y LibraDesk.

**Una imagen Docker, seis contenedores.** Este repo produce un único artefacto.
Lo que distingue al backoffice de Gestiolibra del de Contalibra es su archivo
`.env`: el slug del producto, el branding y las features habilitadas. No hay
seis aplicaciones que mantener sincronizadas — que es el problema que
[`libra-ui`](https://github.com/marianocappucci/libra-ui) y
[`libracore`](https://github.com/marianocappucci/libracore) existen para evitar.

Cada despliegue vive en `admin.<producto>.com.ar`.

## Es un control plane

**Los seis productos son multi-instancia.** Cada uno corre N contenedores de
cliente bajo `clientes/<slug>/`, y el backoffice los administra a todos.

Eso obliga a una distinción que es el corazón del diseño:

| Plano | Cómo llega | Qué resuelve |
|---|---|---|
| **Instancias** | Filesystem + Docker del host, vía `libracore.admin.services` | listar, alta, plan, start/stop, backup, baja |
| **Configuración** | HTTP contra la API de cada instancia | correo saliente, usuarios |

> **Por qué el segundo plano va por HTTP y no abriendo la base de cada
> instancia**, que fue el primer diseño y se descartó: la contraseña SMTP se
> cifra con una clave derivada del `SECRET_KEY` **de la instancia**, y
> `libraauth.crypto` la lee del entorno del proceso. Un backoffice que
> administra N instancias no puede tener N secretos en un solo entorno. Si
> escribiera igual, cifraría con su clave y la instancia leería después
> `password_indescifrable`: el correo quedaría roto **sin que nada falle a la
> vista**. Hablando por HTTP, cada instancia sigue cifrando con su propia clave
> en su propio proceso y el problema no existe.

La autenticación entre backoffice e instancia es el token de servicio de
`libraauth v0.7.0` (`X-Internal-Auth`), que viaja por la red interna de Docker
y nunca sale a internet.

## Features

| Feature | Qué es | Plano |
|---|---|---|
| `instancias` | Inventario y ciclo de vida de los contenedores de cliente | host |
| `smtp` | Correo saliente **de una instancia**, con la contraseña cifrada en reposo | HTTP |
| `usuarios` | Usuarios **de una instancia**: alta, edición, baja lógica, borrado y reset de contraseña ajena | HTTP |
| `salud` | Versión y arranque del backoffice + qué instancias contestan | ambos |
| `apariencia` | El **tema de la suite**: los colores que el superadmin elige para TODAS las instancias del producto (ADR-007 de `libra-ui`) | HTTP |
| `marca` | La **marca de UNA instancia** para venderla a marca blanca: nombre, logo, color y Términos propios (ADR-092 y ADR-093 de `libracore`) | HTTP |
| `revendedores` | La **consola de revendedores**: un despliegue aparte, de ningún producto. Va sola (ver abajo) | HTTP, a los backoffices |

Se declaran por entorno: `FEATURES=instancias,smtp,usuarios,salud`.

### `revendedores`: la consola

Quiénes son los revendedores, qué productos pueden vender, qué instancias son suyas, y el bloqueo. Es **un despliegue más de esta imagen**, de
ningún producto, y **sólo por túnel SSH**: puede cortarles el servicio a clientes de cualquier producto. La marca, los planes y el alta siguen
en el backoffice de cada producto. Diseño: `consola-de-revendedores-diseno`, en el wiki.

Un proceso no puede atender a varios productos (`libracore.admin.services` guarda estado global de uno), así que la consola le pide el trabajo a
cada backoffice por `stack_stack-net`, en `http://<producto>-admin:8000/api/consola`. Esa ruta sólo lista instancias y las suspende o activa.

| Dónde | Entorno |
|---|---|
| **Cada backoffice** | `CONSOLA_TOKEN`. Sin él, `/api/consola` da 404 y el backoffice queda como estaba |
| **La consola** | `FEATURES=revendedores`, el mismo `CONSOLA_TOKEN` y `CONSOLA_PRODUCTOS=ventalibra:VentaLibra,libracargo:LibraCargo`. No lleva `REPO_ROOT`, ni `docker.sock`, ni repos montados |

🔴 **Desbloquear reactiva sólo lo que suspendió la consola.** Una instancia que ya estaba suspendida, por falta de pago por ejemplo, no vuelve.

### `apariencia`: el tema de la suite

Una **suite es un producto**: lo que se elige acá es UN tema para todas sus instancias. La pantalla «Apariencia» lee la lista de colores de
`libra-ui/tema` (la única, la misma que valida la instancia y pinta la SPA), muestra cómo queda el menú sobre fondo claro y oscuro y no deja
guardar nada inválido: un fondo sobre el que ningún texto llega a contraste 4,5:1 se rechaza.

Al guardar, el backoffice **guarda primero** (en `TEMA_PATH`, por defecto junto al estado del login, en el volumen persistente) y **después
empuja** el tema a cada instancia con el token de servicio (`PUT /api/tema`, `libracore` ≥ v1.118.0). Cada instancia lo guarda en su propio
`config.json` y lo sirve ella misma: su SPA lee de ella y no de acá, así que una instancia sigue con sus colores aunque el backoffice esté
caído. Un fallo parcial no deshace nada: la pantalla dice qué pasó con cada una (`aplicada`, `detenida`, `no contesta`, `hay que actualizarla`
si es una versión sin el endpoint, `rechazada`) y «Reaplicar a todas» vuelve a intentar con las que quedaron atrás. Las instancias nuevas
reciben el tema al darlas de alta (mejor esfuerzo; si no contestan todavía, figuran como `desfasada`).

| Variable | Qué es |
|---|---|
| `TEMA_PATH` | Dónde se guarda el tema de la suite. Por defecto, `tema.json` junto a `ADMIN_PANEL_ESTADO_PATH` (o `/var/lib/libra-backoffice/tema.json`). |
| `TEMA_INSTANCIA_PATH` | La ruta del tema en cada instancia. Por defecto `/api/tema` (la misma en los seis productos). |

Se autentica contra cada instancia con su token de servicio, como `smtp` y `usuarios` (ver «Token de servicio por instancia»).

**Una instancia con marca propia no recibe el tema de la suite** (ver `marca`, abajo): antes de empujar o comparar, el backoffice le pregunta
`GET /api/marca` y, si es `propia`, la figura como `marca propia` y no la toca. Una instancia que no contesta esa pregunta (vieja, caída) se trata
como «sin marca» y sigue el camino de siempre.

### `marca`: la marca de una instancia (marca blanca)

Es de **una** instancia, no de la suite: es la pestaña «Marca» de la ficha de cada instancia (sólo si el producto tiene la feature), y cada
acción le habla a *esa* instancia, que es la que guarda todo en su `config.json` y su volumen (`libracore.marca_router` y
`libracore.terminos_propios`, `libracore` ≥ v1.206.0). A diferencia de «Apariencia», nada se empuja a las demás.

**El orden importa: primero los términos, después la marca.** Con marca propia la instancia *tiene que* tener Términos propios (ADR-030 de
`libraauth`); si no los tiene queda frenada y sus usuarios no pueden entrar. Por eso guardar el nombre, el color o el logo en una instancia que
todavía no es de marca propia y no tiene términos se rechaza con `409` (`terminos_primero`), y quitar los términos de una instancia con marca propia
también (`quedaria_frenada`); en los dos casos, quien opera puede seguir a sabiendas (`sin_terminos` / `?confirmar=true`). Los términos no se
pueden releer: la instancia devuelve versión, vigencia y huella, no el texto.

| Ruta (`/api/instancias/{slug}/marca…`) | Qué hace |
|---|---|
| `GET` | La marca y los términos de la instancia |
| `PUT` | Nombre, nombre corto y color |
| `POST /logo`, `DELETE /logo`, `GET /logo` | Subir (multipart, hasta 1 MB), quitar y ver el logo (la vista previa la sirve este backoffice, detrás de la sesión) |
| `PUT /terminos`, `DELETE /terminos` | Cargar o quitar los Términos propios |
| `DELETE` | Volver a la marca del producto (se lleva también los términos) |

| Variable | Qué es |
|---|---|
| `MARCA_INSTANCIA_PATH` | La ruta de la marca en cada instancia. Por defecto `/api/marca` (la misma en los productos que montan `marca_router`). |

## Ciclo de vida de una instancia

`instancias` cubre el onboarding completo, sin salir del navegador:

| Pantalla | Qué hace del otro lado |
|---|---|
| **Alta** (`POST /api/instancias`) | Directorio del cliente, `docker compose up`, plan inicial y —con dominio— proxy con SSL |
| **Editar** (`PUT /api/instancias/{slug}`) | Nombre y dominio en `cliente.json`; con dominio nuevo, proxy nuevo |
| **Plan / estado / backup** | `set_plan`, `start`/`stop`/`restart`, tar.gz de `data/` |
| **Baja** (`POST /api/instancias/{slug}/baja`) | Backup, borra el proxy, `docker compose down -v` y `rmtree` del directorio |

Dos detalles que la UI no puede tratar como cualquier formulario:

- **La contraseña del admin vuelve una sola vez.** Si el alta no la trae, el
  motor la genera y la devuelve en esa única respuesta. Por eso el alta termina
  en un panel de credenciales y no redirigiendo al listado. Si el navegador
  nunca llega a verla, queda en `clientes/<slug>/cliente.json` del host.
- **El alta puede pasar del minuto** —levantar el contenedor, esperar a que
  inicialice su base y emitir el certificado— y un proxy con `proxy_read_timeout`
  corto puede cortar la respuesta con el alta ya en curso. La pantalla no
  reintenta: relee el inventario y, si apareció una instancia nueva, avisa que
  no se reintente.

La baja es `POST .../baja` y no `DELETE` porque lleva un cuerpo obligatorio (la
confirmación del slug) y el `api-client` de `libra-ui` —compartido por los seis
productos— manda `DELETE` sin cuerpo.

## Login en dos pasos

Desde la F4 (2026-09-13, libraauth v0.42.0) el login con segundo factor se
hace en **dos pasos**, cada uno su propio endpoint — antes `POST /api/login`
exigía usuario, contraseña y código TOTP los tres juntos, así que no había
forma de mostrar el código en una pantalla separada sin que el backend ya lo
supiera de antemano.

| Paso | Endpoint | Qué recibe | Qué contesta |
|---|---|---|---|
| 1 | `POST /api/login` | `{username, password, captcha, codigo?}` | Sin segundo factor: `200` + cookie, como siempre. Con segundo factor y **sin** `codigo`: `200` sin cookie, `{"requiere_codigo": true, "desafio": "..."}`. Clave mala: `401`. |
| 2 | `POST /api/login/codigo` | `{desafio, codigo}`, sin sesión | Desafío vencido/inválido: `401` "El código venció: volvé a ingresar.". Código malo: `401` "Código incorrecto.". Los dos bien: `200` + cookie. |

Orden de validaciones en cada uno, y por qué:

1. **`rate_limit_excedido(ip)` primero, en los dos.** Es el mismo contador por
   IP (`AdminAuth`, ver "Seguridad" más abajo): un intento fallido en
   cualquiera de los dos pasos cuenta para el mismo bloqueo, y una IP
   bloqueada recibe `429` sin llegar a validar nada más.
2. **El captcha, sólo en el paso 1** — el paso 2 no lo pide: ya pagó el costo
   del captcha al pasar el paso 1, y pedirlo de nuevo no compra nada.
3. **`codigo` no vacío en `/api/login` es el camino de un solo paso, sin
   cambios**: `check_credentials` de siempre, para el cliente que todavía
   manda los tres datos juntos. Nada de esto le cambia el comportamiento.

🔴 **Consecuencia asumida (ADR-016 de libraauth): con 2FA encendido, el paso 1
le confirma a quien prueba contraseñas que la clave es correcta** — antes,
con el único endpoint, clave y código mal daban el mismo `401` y no se podía
distinguir cuál de los dos falló. Se mitiga con lo que ya protegía el login
entero: el captcha (ADR-014) encarece cada contraseña probada, el bloqueo por
IP (ADR-009) sigue cortando antes de agotar los cinco intentos, y una sesión
de verdad exige además el código — superar el paso 1 no abre nada por sí
solo. El desafío del paso 1 no sirve como cookie de sesión ni al revés:
`emitir_desafio_totp` lo firma con un salt propio, distinto del de la cookie.

## Seguridad: doble factor del superadmin

Pantalla `/seguridad`, presente en los seis backoffices — no es una `feature`
de la tabla de arriba: aplica siempre, como el login mismo. Deja encender o
apagar el segundo factor TOTP del superadmin sin tocar el `.env` ni recrear el
contenedor (F3, 2026-09-13; `AdminAuth.iniciar_totp` / `confirmar_totp` /
`desactivar_totp` de libraauth v0.41.0, detrás de `routers/seguridad.py`).

- **Encender no activa nada solo.** `POST /api/seguridad/totp/iniciar` genera
  un secreto PENDIENTE y devuelve el QR —`data:image/svg+xml`, armado con
  [segno](https://pypi.org/project/segno/)— y el secreto en texto para cargar
  a mano si el QR no se puede escanear. Recién queda activo al
  `POST /api/seguridad/totp/confirmar` con un código vigente del autenticador;
  hasta entonces no hay nada guardado como activo.
- **Desactivar exige el código del autenticador**, igual que confirmar: sin uno
  vigente no hay forma de apagar el segundo factor, ni siquiera desde este
  backoffice.
- Los tres endpoints comparten el rate limiting del login
  (`rate_limit_excedido` / `registrar_intento_fallido`, por IP vía
  `ip_del_request`): una sesión de backoffice robada no puede probar códigos
  sin límite.
- **El entorno sigue mandando cuando está presente.** Con
  `ADMIN_PANEL_TOTP_SECRET` seteado, `origen` es `"entorno"`: la pantalla
  muestra el interruptor deshabilitado, y encender, confirmar o desactivar
  desde acá da 409 — se cambia desde el `.env`, como antes de la F3.

### `totp.json`, y cómo recuperarse si se pierde el teléfono

El secreto enrolado desde la pantalla se guarda en `totp.json`, **hermano** del
archivo del bloqueo de login: mismo directorio que `ADMIN_PANEL_ESTADO_PATH`
(`/var/lib/libra-backoffice/` en el compose de ejemplo, dentro del volumen
`estado`). Sin `ADMIN_PANEL_ESTADO_PATH` configurado (ni `ADMIN_PANEL_TOTP_PATH`
a mano) no hay dónde guardarlo: la pantalla lo dice (`enrolable: false`) y
encender da 409.

El archivo falla **cerrado**, a diferencia del de intentos fallidos: uno
ilegible o con forma inesperada deja el segundo factor `activo: true` y el
login cerrado — pidiendo un código que ya nadie puede dar — en vez de apagarse
solo. Para recuperarse (teléfono perdido, o archivo roto), desde el host:

```bash
docker exec <producto>-admin rm /var/lib/libra-backoffice/totp.json
```

Y volver a encenderlo desde la pantalla. Un `rm` y no una edición a mano: el
archivo no tiene un formato que valga la pena tocar con un editor, y un JSON
escrito a mano con una forma apenas distinta es exactamente lo que el
fail-closed de arriba trata como "roto".

## Qué reusa

Casi todo. Lo genuinamente nuevo de este repo es el ensamblado y el proxy.

- **`libraauth`** — `AdminAuth` (sesión del superadmin, credenciales por
  entorno, cookie propia, rate limiting, renovación deslizante de 8 h sin uso
  desde v0.43.0/ADR-017 — ver `deps.admin_actual`) y el guard de token de
  servicio. Desde v0.43.0/ADR-018 también los modelos públicos
  `UsuarioAlta`/`UsuarioEdicion`/`UsuarioClaveNueva` de `libraauth.usuarios`:
  el proxy de `config_instancia.py` los importa en vez de redefinirlos —
  contrato único de usuarios para toda la familia.
- **`libracore`** — `admin.services` (inventario y ciclo de vida, que a su vez
  envuelve los scripts del repo de cada producto) y `security_headers`.
- **`libra-ui`** — `Layout`, `Login`, `Usuarios`, `data-table`, `AuthContext`,
  `api-client` y `ConfiguracionSmtp`. Este repo es el **primer consumidor** de
  la `v0.10.0`. Desde v0.71.0, `Usuarios` recibe `roles` (`USERS_ROLES`, vía
  `/api/salud`) y `permitirEliminar` (siempre `true` acá: el proxy de `DELETE`
  ya existe) — sin `usuarioActualId`, porque el superadmin del backoffice no
  es un usuario de ninguna instancia.

## Estructura

```
backend/libra_backoffice/   FastAPI, API JSON
frontend/                   Vite + React + shadcn/ui + libra-ui
Dockerfile                  build del frontend -> estáticos servidos por el backend
scripts/construir_imagen.sh arma el `docker build` de la imagen (ver "Construir la imagen")
```

## Desarrollo

```bash
cd backend && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest -q --cov
```

```bash
cd frontend && npm install && npm run build
```

## Configuración

| Variable | Obligatoria | Qué es |
|---|---|---|
| `PRODUCT_SLUG` | sí | `gestiolibra`, `contalibra`, … |
| `PRODUCT_NAME` | no | Nombre para mostrar. Default: el slug capitalizado. |
| `FEATURES` | sí | Lista separada por comas. Un valor desconocido **no arranca**. |
| `ADMIN_PANEL_USER` / `ADMIN_PANEL_PASSWORD` | sí | Credenciales del superadmin. Sin password, se rechaza todo login. |
| `SECRET_KEY` | sí | Firma la cookie de sesión **de este backoffice**. |
| `ADMIN_PANEL_TOTP_SECRET` | no | Segundo factor del superadmin (libraauth v0.36.0). Con esto seteado el login pide el código del autenticador. Se genera con `python -m libraauth.totp <producto>`; un valor inválido no deja levantar. |
| `ADMIN_PANEL_ESTADO_PATH` | no | Archivo donde el bloqueo por intentos fallidos sobrevive al reinicio. El compose de ejemplo lo monta en un volumen. |
| `WEB_CONCURRENCY` | no | Procesos de uvicorn (`--workers` del `CMD`). Default 1. **No subirlo** sin leer «Varios procesos». |
| `LIBRA_ERRORES_DIR` | no | Carpeta del registro de errores (`errores.jsonl`). El compose de ejemplo la fija **dentro del volumen `estado`** (`/var/lib/libra-backoffice/errores`); sin ella cae en el directorio de trabajo, o sea dentro del contenedor, y un recreate la borra. |
| `LIBRA_ENTORNO` | no | `cliente`, `demo` o `dev`: de eso depende cómo avisa el vigía. Sin ella, `desconocido` (se trata como `cliente`). |
| `LIBRA_INSTANCIA` | no | Nombre del contenedor (`<producto>-admin`). Distingue los ocho backoffices en el registro. |
| `LIBRA_VERSION` | no | El `release` de cada línea. La imagen la trae del tag con que se construyó (`APP_VERSION`). |
| `ADMIN_PANEL_TOTP_PATH` | no | Archivo del secreto TOTP enrolado en runtime desde la pantalla Seguridad (F3). Default: `totp.json` al lado de `ADMIN_PANEL_ESTADO_PATH`. Ver "Seguridad: doble factor del superadmin". |
| `REPO_ROOT` | sí | Checkout del producto en el host, de donde se importan `panel_admin.py` / `nuevo_cliente.py` / `plans.py` y, por defecto, donde vive `clientes/`. |
| `LIBRA_CLIENTES_DIR` | no | Ruta **absoluta** del directorio de instancias, si no es `REPO_ROOT/clientes`. Requiere libracore >= v1.123.0 (con una anterior se ignora en silencio). Ver "Dónde viven las instancias". |
| `DB_FILENAME` | sí | Nombre del archivo de base de cada instancia (`contalibra.db`). |
| `LIBRA_SERVICE_TOKEN` | no | El global, **de respaldo**: se manda a las instancias que todavía no tienen token propio y es el reintento durante una rotación. Ver «Token de servicio por instancia». |
| `SMTP_PATH` | no | Default `/admin/smtp`. Contalibra y Restolibra usan `/api/config/smtp`. |
| `USERS_PATH` | no | Default `/users`. LibraDesk usa `/api/usuarios`. |
| `USERS_ROLES` | no | Vocabulario de roles de ESTE producto, separado por comas (ej. `admin,operador,cajero`). Default `staff,admin`. Llega al `Select` de rol de la pantalla de Usuarios vía `/api/salud` (campo `usuarios_roles`) — mismo camino que `features`. Sin etiqueta propia: la muestra es el valor capitalizado (`operador` → «Operador»). Contalibra: `admin,operador,cajero`. Restolibra: `admin,operador,cajero,mozo`. |
| `INSTANCIA_PUERTO` | no | Puerto interno de las instancias. Default `8000`. |
| `TIMEOUT_INSTANCIA` | no | Segundos. Default `5`. |

### Token de servicio por instancia

Desde libracore v1.183.0 (su ADR-071) **cada instancia tiene su propio
`LIBRA_SERVICE_TOKEN`** en su `docker-compose.yml` (literal o `${VAR}` contra su
`.env`). El alta lo genera, y `panel_admin.py token-servicio <slug> --rotar` /
`--cerrar` lo rota en dos pasos (libraauth v0.52.0 acepta el anterior mientras
tanto). El backoffice lo lee del disco **en cada request**
(`libracore.admin.services.token_de_servicio(slug)`, sin caché), así que una
rotación no pide reiniciarlo. Los valores no se loguean ni salen por la API.

- **Sin token propio** (instancias anteriores al ADR-071, hasta que se roten):
  se manda el global de `/etc/<producto>-admin.env`.
- **Ventana de rotación:** entre que `--rotar` escribe el valor nuevo y que el
  `up -d` recrea el contenedor, la instancia todavía conoce el viejo. Si una
  request con el propio da **401**, se reintenta con el
  `LIBRA_SERVICE_TOKEN_ANTERIOR` de la instancia (si hay y es distinto) y, si
  no hay o también da 401, con el global (en la primera rotación el viejo es el
  global), sin repetir un valor ya probado: **dos reintentos como máximo**.
  Ningún otro código se reintenta.
- **Sin propio ni global:** esa instancia contesta 503 con un mensaje que dice
  cuál y cómo generarle uno; el backoffice y las demás siguen andando. Por eso
  el global ya no es obligatorio para arrancar.
- **`/api/salud`** trae `token` por instancia: `propio`, `compartido` (el mismo
  valor que el global: falta rotarla) o `ausente`. La pantalla de salud lo
  muestra junto al estado.

**Orden:** primero se despliega este backoffice, después se rotan las
instancias; al revés, la instancia rotada contesta 401 al backoffice viejo.

## Dónde viven las instancias (`LIBRA_CLIENTES_DIR`)

Cada instancia es una carpeta `<slug>/` con su `cliente.json`, su
`docker-compose.yml` y su `data/`. Por defecto el directorio que las contiene es
`REPO_ROOT/clientes`, y **no cambia nada** mientras no se defina lo de abajo.

Desde libracore v1.123.0 (el pin de este repo) esa ubicación se resuelve en un
solo lugar, `libracore.provisioning.get_config().clientes_dir`, con esta
precedencia:

1. el parámetro `clientes_dir=` que el `configure()` del producto le pase (hoy
   ninguno en `develop` al 2026-10-03);
2. la variable de entorno `LIBRA_CLIENTES_DIR` (vacía cuenta como no definida;
   se lee en cada acceso, no al arrancar);
3. `REPO_ROOT/clientes`.

Antes `libracore.admin.services` (lo que usa este backoffice) leía la constante
`CLIENTES_DIR` del `scripts/panel_admin.py` del producto, y el alta y el cron
leían otra cosa: cambiar una sola dejaba al cron y al backoffice mirando carpetas
distintas. Ahora los tres leen la misma, y `CLIENTES_DIR` queda en los scripts
sólo por compatibilidad.

Para mover las instancias fuera del checkout hace falta, **los tres a la vez**:

- **La misma variable en todos los procesos que operan instancias:** el
  contenedor de este backoffice (`environment:` del compose, o el
  `/etc/<producto>-admin.env`), el cron de `panel_admin.py` (`backup-all`,
  `resguardo-externo`, `estado-externo`) y las sesiones de línea de comandos.
  Con valores distintos, cada uno ve su propio inventario. Usar ruta absoluta:
  una relativa se resuelve contra el directorio de cada proceso.
- **El mount espejado de ese directorio en este contenedor.** Es la misma razón
  por la que el checkout se monta espejado (`/root/<producto>:/root/<producto>`):
  `docker compose` corre acá adentro pero el daemon resuelve los binds en el
  **host**, así que la ruta del `-f` y la de `data/` tienen que ser idénticas
  adentro y afuera. Si `clientes/` sale de `REPO_ROOT`, queda fuera de ese mount
  y el inventario se ve vacío; un symlink queda colgado dentro del contenedor.
  Ejemplo, con el destino propuesto `/srv/libra/<producto>/clientes`:

  ```yaml
  environment:
    - LIBRA_CLIENTES_DIR=/srv/libra/<producto>/clientes
  volumes:
    - /root/<producto>:/root/<producto>             # el checkout (scripts), como siempre
    - /srv/libra/<producto>:/srv/libra/<producto>   # espejado: misma ruta adentro y afuera
  ```

  Con el backoffice como servicio de systemd (`Environment=`) es sólo la
  variable en la unidad.
- **Un pin de libracore >= v1.123.0 acá adentro.** Es ESTE contenedor el que
  importa el `panel_admin.py` del producto con su propia libracore: un producto
  que pase `configure(clientes_dir=...)` exige el pin acá (si no, `TypeError` en
  cada `GET /api/instancias`, con el contenedor `healthy`; mismo mecanismo que
  `backup_zip` y `migraciones`), y con un pin anterior la variable se ignora sin
  avisar. Lo cubre
  `test_la_libracore_instalada_acepta_clientes_dir_en_configure`.

> ⚠️ `docker-compose.example.yml` **todavía no** trae el mount ni la variable:
> es la etapa 2 del plan *Sacar `clientes/` del árbol del repo* (wiki). Esta
> sección documenta el mecanismo; apuntarlo a otro directorio y mover datos es
> un paso aparte, que se pide por separado. **Rollback:** sacar la variable y el
> mount extra.

## Registro de errores

Desde `libracore` v1.159.0 (ADR-045) un `500` ya no se pierde en el stdout del contenedor: `instalar_registro_de_errores(app, "libra-backoffice")`
(en `app.py`, al lado de `SecurityHeadersMiddleware`) responde `{"detail": "Error interno", "ref": "a1b2c3d4"}` y deja **una línea JSON** en
`$LIBRA_ERRORES_DIR/errores.jsonl` (rotación 5 MB × 3, sin cuerpos, cookies ni datos personales). El `ref` es el código que la pantalla «Algo
falló» (`<ErrorBoundary>` de `libra-ui`, en `main.tsx`) le muestra al usuario; los errores del navegador llegan a `POST /api/errores-cliente`.
Lee los archivos el vigía del host (`operaciones/vigilar_errores.py` del wiki) y avisa por Telegram.

🔴 **El archivo tiene que estar en un volumen.** El compose de ejemplo lo pone dentro del volumen `estado` (el del login y el tema), en
`/var/lib/libra-backoffice/errores`; en el host queda en `/var/lib/docker/volumes/<proyecto>_estado/_data/errores/errores.jsonl`, que es lo que
busca el glob por defecto del vigía. `LIBRA_INSTANCIA` (el `container_name`) es lo que distingue a un backoffice de otro: el producto es siempre
`libra-backoffice`.

## Varios procesos

El contenedor corre **un solo uvicorn** (`WEB_CONCURRENCY` vale 1 si no se la toca) y así se queda. Qué hay que saber antes de subirlo
(libraauth v0.50.0, ADR-023):

- **El estado del login es seguro entre procesos sólo con `ADMIN_PANEL_ESTADO_PATH`.** Con él, cada actualización (intentos fallidos, último código
  TOTP) corre bajo un `flock` sobre `<archivo>.lock`, y un mismo código TOTP lo acepta un solo proceso. Sin él, cada worker lleva sus propios
  intentos (N veces más margen para un ataque) y su propio «último código»; `AdminAuth` lo avisa en el log del arranque si `WEB_CONCURRENCY` > 1.
  El compose de ejemplo ya lo setea. Dos **contenedores** (no procesos de uno) tendrían que compartir el volumen.
- 🔴 **El captcha sigue en memoria**: este backoffice no tiene base propia (administra las instancias por `docker exec` y por HTTP), así que no hay
  dónde poner `UsadosEnBase`. Con N workers un desafío resuelto sirve **una vez por worker**: el captcha encarece N veces menos el ataque. Para
  subir `WEB_CONCURRENCY` hace falta darle una base (aunque sea un SQLite en el volumen `estado`) y pasar `Captcha(..., usados=UsadosEnBase(...))`
  en `app.py`. No se hizo porque hoy no se justifica un worker más.

## Despliegue

Contenedor en la red `stack_stack-net` del VPS, proxy host de NPM apuntando
**por nombre de contenedor** (`forward_host=<producto>-admin`,
`forward_port=8000`). Sin publicar puertos al host. Ver
`docker-compose.example.yml`.

Las credenciales van en `/etc/<producto>-admin.env` (chmod 600, fuera del
repo), igual que las de los backoffices que ya existían.

### Construir la imagen

Una sola imagen, `libra-backoffice:<tag>`, la usan los ocho `<producto>-admin`
(el producto lo elige `PRODUCT_SLUG`/`FEATURES` del compose, no la imagen). Se
construye **en el VPS, desde un checkout limpio de `main`** (`/root/libra-backoffice`),
con:

```bash
git pull --ff-only
export LIBRA_SSH_KEY_LIBRACORE=...   # ruta de la deploy key de libracore
export LIBRA_SSH_KEY_LIBRAAUTH=...   # ruta de la deploy key de libraauth
export LIBRA_SSH_KEY_LIBRA_UI=...    # ruta de la deploy key de libra-ui
scripts/construir_imagen.sh --dry-run   # imprime el comando sin construir
scripts/construir_imagen.sh             # construye (tag: vAAAA.MM.DD-HHMMSS)
scripts/construir_imagen.sh v2026.10.15-120000   # o con un tag explícito
```

El script no lleva rutas ni contenido de claves: las rutas viajan por entorno.
Se niega a construir con el árbol sucio (`APP_COMMIT` mentiría) o fuera de `main`
(salvo `--permitir-rama`), y lee los ids de `--ssh` **del propio Dockerfile**, así
que una dependencia privada nueva le exige su variable sola
(`backend/tests/test_construir_imagen.py` lo cubre). Lo que arma es:

```bash
docker build \
  --ssh libracore=$LIBRA_SSH_KEY_LIBRACORE \
  --ssh libraauth=$LIBRA_SSH_KEY_LIBRAAUTH \
  --ssh libra-ui=$LIBRA_SSH_KEY_LIBRA_UI \
  --build-arg APP_VERSION=$TAG --build-arg APP_COMMIT=$(git rev-parse --short HEAD) \
  -t libra-backoffice:$TAG -t libra-backoffice:latest .
```

| Pieza | Qué es |
|---|---|
| `--ssh libra-ui=` | Stage del frontend: `npm ci` baja `libra-ui` por `git+https`, y el stage reescribe esa URL a SSH. Un solo mount y un `SSH_AUTH_SOCK` alcanzan. |
| `--ssh libracore=` y `--ssh libraauth=` | Stage de Python: `uv sync --frozen` resuelve las dos de `uv.lock`. Cada una tiene su alias `Host github-<repo>` con su `IdentityAgent`. |
| `APP_VERSION` | El tag de la imagen. Alimenta `LIBRA_VERSION` (el `release` del registro de errores) y el campo `backoffice.version` de `/api/salud`. |
| `APP_COMMIT` | El commit corto del código que se construyó. Sin él la imagen dice `desconocido`. |
| `:latest` | Sólo sirve para comparar image IDs; **ningún compose lo usa**, siempre un tag concreto. |

🔴 **Una clave por `--ssh` id, no un agente con las tres cargadas.** Con varias
en un agente, SSH las ofrece en orden y GitHub autentica con la primera que
acepta, que puede no ser la del repo que se está clonando.

Las claves privadas viajan por `--mount=type=ssh` y no quedan en ninguna capa.
Lo que sí está horneado en el Dockerfile son las claves **públicas** de libracore
y libraauth (`/root/.ssh/id_libracore.pub`, `id_libraauth.pub`): sólo le dicen a
ssh qué fingerprint pedirle al agente. **Si se rota una de esas deploy keys, hay
que cambiar también su línea `.pub` en el Dockerfile**, o el build falla con
«no more authentication methods to try».

> Si buildx ≥ 0.38 pide `--allow=fs.read=...` por las rutas de las claves, antepóngase
> `BUILDX_BAKE_ENTITLEMENTS_FS=0` (es lo que `reglas/deploy.md` del wiki indica para
> `docker compose up --build`; para `docker build` a secas no se midió).

**Los tags no ordenan cronológicamente** (`v2026.08.02-1910` se construyó
*antes* que `-1605`). Cuál imagen es más nueva lo dicen el image ID y el
`APP_COMMIT`, nunca el nombre.

### Verificar la imagen antes de tocar nada

```bash
docker run --rm libra-backoffice:$TAG printenv APP_VERSION APP_COMMIT
docker run --rm libra-backoffice:$TAG sh -c 'ls /opt/frontend-dist/assets/index-*.js && grep -l "<texto de lo recién agregado>" /opt/frontend-dist/assets/*.js'
```

El primero tiene que devolver el tag y el commit que se esperan; el segundo
confirma que el bundle de la imagen trae lo nuevo (el frontend se resuelve en el
build: un `restart` o un build viejo sirven el bundle anterior).

### Desplegar en los `<producto>-admin`

Cada backoffice es un compose propio (`docker-compose.example.yml`) que apunta a
la imagen por **tag concreto** y sin `build:`. Desplegar es repinear esa línea:
**de a un producto**, empezando por uno de bajo riesgo, y sin tocar el resto del
compose salvo que el cambio agregue una feature o una variable.

1. En el directorio del compose (`/root/<producto>/admin/`; en Contalibra y
   Restolibra es `/root/<producto>/backoffice/`): copiar
   `docker-compose.yml` a `docker-compose.yml.antes-<motivo>-<fecha>`.
2. Cambiar `image: libra-backoffice:<tag viejo>` por el tag nuevo (y, si hace
   falta, sumar la feature a `FEATURES`).
3. `docker compose up -d` (recrea el contenedor; **no** `restart`).
4. Esperar `healthy` y verificar.

**Rollback:** devolver `image:` al tag anterior (queda en el respaldo del paso
1) y `docker compose up -d`.

### Verificar el despliegue

Por contenido, no sólo por salud (`/health` da 200 también con la imagen vieja):

```bash
docker inspect -f '{{.State.Health.Status}} restarts={{.RestartCount}} {{.Image}}' <producto>-admin
docker exec <producto>-admin printenv APP_VERSION APP_COMMIT
docker exec <producto>-admin python3 -c "import json,urllib.request; print(json.load(urllib.request.urlopen('http://localhost:8000/health', timeout=3)))"
curl -s https://admin.<producto>.com.ar/ | grep -o 'assets/index-[^"]*\.js'   # el bundle servido
curl -s -o /dev/null -w '%{http_code}\n' https://admin.<producto>.com.ar/api/salud   # sin sesión: 401
```

Tiene que dar: `healthy`, `restarts=0`, el `APP_VERSION`/`APP_COMMIT` de la
imagen construida, un objeto JSON en `/health`, el **mismo image ID** que
`docker image inspect -f '{{.Id}}' libra-backoffice:$TAG` y el mismo hash de
bundle que en la imagen (y que en los demás `-admin` ya actualizados).
Con sesión, `backoffice.version` y `backoffice.commit` de `/api/salud` dicen lo
mismo (es lo que muestra la pantalla de salud).

## Dónde se arregla (regla de la familia, 2026-10-03)

**El arreglo de fondo vive siempre en el motor** (`libracore`; `libracommerce` y `libra-ui` para
lo suyo), **nunca en este repo.** Lo que otro producto comparte o podría compartir —el protocolo
con ARCA, las reglas fiscales y sus validaciones, las guardas contra duplicados, la numeración, la
cuenta corriente, los componentes de pantalla compartidos— se escribe y se arregla en el motor.
Este repo sólo aporta **costuras** (los hooks que el motor ya expone) y lo suyo: pantallas,
textos y su modelo de datos propio. Si falta la costura, se agrega al motor; si el arreglo hace
falta antes, igual se hace en el motor (PR y tag) y acá se sube el pin: nada «provisorio» en este
repo. Un hueco que se encuentra acá se busca en los demás productos antes de darlo por acotado.
Detalle y motivo: `reglas/producto.md` del wiki.
