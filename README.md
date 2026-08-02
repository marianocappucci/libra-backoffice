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
| `usuarios` | Usuarios **de una instancia**, con baja lógica | HTTP |
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

## Qué reusa

Casi todo. Lo genuinamente nuevo de este repo es el ensamblado y el proxy.

- **`libraauth`** — `AdminAuth` (sesión del superadmin, credenciales por
  entorno, cookie propia, rate limiting) y el guard de token de servicio.
- **`libracore`** — `admin.services` (inventario y ciclo de vida, que a su vez
  envuelve los scripts del repo de cada producto) y `security_headers`.
- **`libra-ui`** — `Layout`, `Login`, `Usuarios`, `data-table`, `AuthContext`,
  `api-client` y `ConfiguracionSmtp`. Este repo es el **primer consumidor** de
  la `v0.10.0`.

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
| `REPO_ROOT` | sí | Checkout del producto en el host, donde vive `clientes/`. |
| `DB_FILENAME` | sí | Nombre del archivo de base de cada instancia (`contalibra.db`). |
| `LIBRA_SERVICE_TOKEN` | con `smtp`/`usuarios` | El mismo valor que tienen seteado las instancias de este producto. |
| `SMTP_PATH` | no | Default `/admin/smtp`. Contalibra y Restolibra usan `/api/config/smtp`. |
| `USERS_PATH` | no | Default `/users`. LibraDesk usa `/api/usuarios`. |
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
