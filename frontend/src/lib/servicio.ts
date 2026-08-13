// El corte de servicio de una instancia, en un solo lugar.
//
// No vive dentro de `EstadoServicio.tsx` porque el listado también lo pinta y
// un archivo que exporta componentes **y** constantes rompe el fast refresh de
// Vite (`react(only-export-components)`).
import { type ServicioEstado } from '../api'

export type OpcionServicio = {
  estado: ServicioEstado
  // La acción que entiende `POST /api/instancias/{slug}/estado`. No es el
  // estado: el motor recibe verbos (`suspender`) y persiste adjetivos
  // (`suspendido`).
  accion: string
  label: string
  descripcion: string
}

export const OPCIONES_SERVICIO: OpcionServicio[] = [
  {
    estado: 'activo', accion: 'activar', label: 'Activo',
    descripcion: 'Operación normal. Todos los usuarios tienen acceso completo.',
  },
  {
    estado: 'pausado', accion: 'pausar', label: 'Pausado',
    descripcion:
      'El cliente entra igual, pero ve un banner de aviso. Sirve para avisar antes de un corte.',
  },
  {
    estado: 'suspendido', accion: 'suspender', label: 'Suspendido',
    descripcion:
      'Acceso bloqueado por completo: la instancia sigue corriendo y devuelve 503 con el mensaje.',
  },
]

export function variantePorEstado(estado: ServicioEstado) {
  if (estado === 'suspendido') return 'destructive' as const
  if (estado === 'pausado') return 'secondary' as const
  return 'outline' as const
}
