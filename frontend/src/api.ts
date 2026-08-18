// Cliente HTTP y tipos del backoffice.
//
// El cliente base (`ApiError` / `request` / `api`) viene de
// `libra-ui/api-client`, igual que en los seis productos. Los tipos de acá
// para abajo son propios del backoffice.
export { api, ApiError } from 'libra-ui/api-client'

import { api } from 'libra-ui/api-client'

// El superadmin del backoffice **no** es un usuario de ningún producto: se
// autentica por entorno (`AdminAuth` de libraauth) y no tiene fila en ninguna
// tabla `usuarios`. Por eso su forma es un `username` y nada más — no tiene
// `role` ni `id`.
export type Superadmin = {
  username: string
}

export type ServicioEstado = 'activo' | 'pausado' | 'suspendido'

export type Instancia = {
  slug: string
  nombre: string
  container: string
  domain: string
  port: number | string
  plan: string
  // El contenedor: running, exited, sin contenedor…
  estado: string
  iniciado: string
  modulos_activos: number | null
  // El corte comercial, que es otro eje: un contenedor `running` puede estar
  // suspendido y devolverle 503 a todo el mundo.
  servicio_estado: ServicioEstado
  servicio_mensaje: string
}

// Lo que el alta acepta. Casi todo es opcional porque el motor tiene un default
// mejor que cualquiera que pueda inventar la UI: el slug sale del nombre, el
// puerto es el próximo libre y la contraseña se genera.
export type AltaIn = {
  nombre: string
  slug?: string
  domain?: string
  port?: number
  admin_user?: string
  admin_password?: string
  plan?: string
  setup_npm?: boolean
}

// Lo que devuelve el alta, que **no** es una `Instancia`: trae `admin_user` y
// `admin_password`. Si el alta se pidió sin contraseña, el motor genera una y
// esta respuesta es la única vez que sale del host — de ahí que la pantalla la
// muestre en vez de refrescar el listado y seguir.
export type InstanciaCreada = {
  slug: string
  nombre: string
  domain: string
  port: number | string
  container: string
  admin_user: string
  admin_password: string
  plan: string
  // `null` = no se intentó (sin dominio, o NPM sin configurar). `false` = se
  // intentó y falló: la instancia existe pero su dominio todavía no resuelve.
  proxy_ok: boolean | null
}

export type Baja = {
  slug: string
  backup: string | null
  npm: boolean | null
}

export type Plan = {
  key: string
  label: string
  precio: number | null
  modulos: string[]
}

export type EstadoInstancia = {
  slug: string
  nombre: string
  container: string
  estado: 'ok' | 'error' | 'inalcanzable' | 'sin contenedor'
  detalle: string
}

export type Salud = {
  producto: { slug: string; nombre: string }
  features: string[]
  backoffice: {
    version: string
    commit: string
    arrancado: string
    uptime_segundos: number
  }
  instancias: EstadoInstancia[]
}

export const backoffice = {
  instancias: () => api.get<{ instancias: Instancia[] }>('/api/instancias'),
  instancia: (slug: string) => api.get<Instancia>(`/api/instancias/${slug}`),
  planes: () => api.get<Plan[]>('/api/planes'),
  salud: () => api.get<Salud>('/api/salud'),

  crear: (datos: AltaIn) => api.post<InstanciaCreada>('/api/instancias', datos),
  editar: (slug: string, datos: { nombre: string; domain: string }) =>
    api.put<Instancia>(`/api/instancias/${slug}`, datos),
  cambiarPlan: (slug: string, plan: string) =>
    api.put<Instancia>(`/api/instancias/${slug}/plan`, { plan }),
  // `mensaje` sólo pesa en `pausar` y `suspender`; en `activar` el motor lo
  // limpia, así que mandarlo o no da lo mismo.
  accion: (slug: string, accion: string, mensaje = '') =>
    api.post<Instancia>(`/api/instancias/${slug}/estado`, { accion, mensaje }),
  backup: (slug: string) => api.post<{ archivo: string }>(`/api/instancias/${slug}/backup`),
  // POST y no DELETE: la baja lleva un cuerpo obligatorio —la confirmación del
  // slug— y el `api-client` compartido manda DELETE sin cuerpo. Ver el
  // comentario del router.
  baja: (slug: string, datos: { confirmar_slug: string; hacer_backup: boolean }) =>
    api.post<Baja>(`/api/instancias/${slug}/baja`, datos),
}

// Rutas que consumen los componentes de libra-ui vía su prop `basePath`.
// Están acá y no inline en cada pantalla para que quede en un solo lugar el
// hecho de que **son por instancia**: es la diferencia entre configurarle el
// correo al cliente correcto y al equivocado.
export const rutaSmtp = (slug: string) => `/api/instancias/${slug}/smtp`
export const rutaUsuarios = (slug: string) => `/api/instancias/${slug}/usuarios`
// Los códigos de acceso a la demo. Misma regla: es por instancia, porque la
// demo de un producto es una instancia más y sus códigos no valen en otra.
export const rutaCodigosDemo = (slug: string) =>
  `/api/instancias/${slug}/demo-codigos`
