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

export type Instancia = {
  slug: string
  nombre: string
  container: string
  domain: string
  port: number | string
  plan: string
  estado: string
  iniciado: string
  modulos_activos: number | null
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

  crear: (datos: Record<string, unknown>) => api.post<Instancia>('/api/instancias', datos),
  editar: (slug: string, datos: { nombre: string; domain: string }) =>
    api.put<Instancia>(`/api/instancias/${slug}`, datos),
  cambiarPlan: (slug: string, plan: string) =>
    api.put<Instancia>(`/api/instancias/${slug}/plan`, { plan }),
  accion: (slug: string, accion: string) =>
    api.post<Instancia>(`/api/instancias/${slug}/estado`, { accion }),
  backup: (slug: string) => api.post<{ archivo: string }>(`/api/instancias/${slug}/backup`),
}

// Rutas que consumen los componentes de libra-ui vía su prop `basePath`.
// Están acá y no inline en cada pantalla para que quede en un solo lugar el
// hecho de que **son por instancia**: es la diferencia entre configurarle el
// correo al cliente correcto y al equivocado.
export const rutaSmtp = (slug: string) => `/api/instancias/${slug}/smtp`
export const rutaUsuarios = (slug: string) => `/api/instancias/${slug}/usuarios`
