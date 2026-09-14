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

Se declaran por entorno: `FEATURES=instancias,smtp,usuarios,salud`.

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
| `ADMIN_PANEL_TOTP_PATH` | no | Archivo del secreto TOTP enrolado en runtime desde la pantalla Seguridad (F3). Default: `totp.json` al lado de `ADMIN_PANEL_ESTADO_PATH`. Ver "Seguridad: doble factor del superadmin". |
| `REPO_ROOT` | sí | Checkout del producto en el host, donde vive `clientes/`. |
| `DB_FILENAME` | sí | Nombre del archivo de base de cada instancia (`contalibra.db`). |
| `LIBRA_SERVICE_TOKEN` | con `smtp`/`usuarios` | El mismo valor que tienen seteado las instancias de este producto. |
| `SMTP_PATH` | no | Default `/admin/smtp`. Contalibra y Restolibra usan `/api/config/smtp`. |
| `USERS_PATH` | no | Default `/users`. LibraDesk usa `/api/usuarios`. |
| `USERS_ROLES` | no | Vocabulario de roles de ESTE producto, separado por comas (ej. `admin,operador,cajero`). Default `staff,admin`. Llega al `Select` de rol de la pantalla de Usuarios vía `/api/salud` (campo `usuarios_roles`) — mismo camino que `features`. Sin etiqueta propia: la muestra es el valor capitalizado (`operador` → «Operador»). Contalibra: `admin,operador,cajero`. Restolibra: `admin,operador,cajero,mozo`. |
| `INSTANCIA_PUERTO` | no | Puerto interno de las instancias. Default `8000`. |
| `TIMEOUT_INSTANCIA` | no | Segundos. Default `5`. |

> ⚠️ **`LIBRA_SERVICE_TOKEN` tiene que ser el mismo valor en el backoffice y en
> todas las instancias del producto.** Es lo que autentica al backoffice contra
> ellas. Con un valor distinto, todas las pantallas del plano de configuración
> contestan 401. Vive en `/etc/<producto>-admin.env` (chmod 600) del lado del
> backoffice y en el compose de cada instancia del otro.
>
> Una instancia **sin** la variable seteada rechaza el token y sigue
> funcionando como antes: el guard de libraauth es opt-in por ausencia. Eso es
> lo que permite actualizar a `v0.7.0` sin tocar ningún compose.

## Despliegue

Contenedor en la red `stack_stack-net` del VPS, proxy host de NPM apuntando
**por nombre de contenedor** (`forward_host=<producto>-admin`,
`forward_port=8000`). Sin publicar puertos al host. Ver
`docker-compose.example.yml`.

Las credenciales van en `/etc/<producto>-admin.env` (chmod 600, fuera del
repo), igual que las de los backoffices que ya existían.
