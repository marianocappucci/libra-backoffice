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

## Qué hace

| Feature | Qué es | Quién la tiene |
|---|---|---|
| `smtp` | Correo saliente de la instancia (host, cuenta, remitente), con la contraseña cifrada en reposo | los seis |
| `usuarios` | ABM de los usuarios del producto, con baja lógica | los seis |
| `salud` | Versión y arranque del backoffice + si la instancia del producto contesta | los seis |
| `clientes` | Alta, plan, ciclo de vida, backup y baja de instancias de cliente | Contalibra y Restolibra |

Se declaran por entorno: `FEATURES=smtp,usuarios,salud`.

## Qué reusa

Casi todo. Lo genuinamente nuevo de este repo es el ensamblado.

- **`libraauth`** — `AdminAuth` (sesión del superadmin, credenciales por
  entorno, cookie propia, rate limiting), `SmtpSettingsRepository` (cifrado y
  precedencia base-sobre-entorno) y `UserRepository`.
- **`libracore`** — `admin.services` (gestión de instancias, que a su vez
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
| `LIBRAAUTH_ENCRYPTION_KEY` | con `smtp` | **Tiene que valer lo mismo que el `SECRET_KEY` de la instancia del producto.** Ver abajo. |
| `AUTH_DB_PATH` | con `smtp`/`usuarios` | Base de la instancia donde libraauth tiene sus tablas. |
| `REPO_ROOT` / `DB_FILENAME` | con `clientes` | Checkout del producto en el host y nombre del archivo de base de cada instancia. |
| `PRODUCT_HEALTH_URL` | no | A quién preguntarle si el producto está vivo. |

> ⚠️ **`LIBRAAUTH_ENCRYPTION_KEY` no es opcional cuando hay `smtp`, y no es
> cualquier valor.** La contraseña SMTP se guarda cifrada con una clave derivada
> del secreto del entorno (`libraauth/crypto.py`), y acá la escribe **este**
> proceso, no el de la instancia. Si no coincide con el `SECRET_KEY` de la
> instancia, el backoffice guarda sin error y el producto después lee
> `password_indescifrable`: el correo queda roto sin que nada falle a la vista.
> No se reusa el `SECRET_KEY` del backoffice para esto — ése firma su propia
> cookie y es un secreto distinto.

## Despliegue

Contenedor en la red `stack_stack-net` del VPS, proxy host de NPM apuntando
**por nombre de contenedor** (`forward_host=<producto>-admin`,
`forward_port=8000`). Sin publicar puertos al host. Ver
`docker-compose.example.yml`.

Las credenciales van en `/etc/<producto>-admin.env` (chmod 600, fuera del
repo), igual que las de los backoffices que ya existían.
