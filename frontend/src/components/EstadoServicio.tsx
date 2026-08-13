// Corte de servicio de una instancia: activo / pausado / suspendido.
//
// Esto vivía en la pantalla de Configuración del propio producto, donde el
// admin del cliente lo veía y lo podía tocar. Era la palanca comercial —el
// corte por falta de pago— servida al cliente que se corta: un cliente pausado
// se despausaba solo, y uno que se suspendía por error quedaba afuera sin forma
// de volver desde el navegador. Va acá, que es el único lado donde el
// superadmin administra a todos.
//
// El estado del contenedor (`instancia.estado`) es OTRO eje y por eso no se
// mezcla en esta tarjeta: `stop` apaga el proceso —la instancia deja de
// responder, se cae el healthcheck y el proxy tira 502—, mientras que
// `suspender` la deja corriendo y contestando 503 con un mensaje. Para cortarle
// el acceso a un cliente que no pagó se usa este, no `stop`.
import { useEffect, useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'

import { OPCIONES_SERVICIO, variantePorEstado } from '@/lib/servicio'

import { type Instancia, type ServicioEstado } from '../api'

type Props = {
  instancia: Instancia
  ocupado: boolean
  onAplicar: (accion: string, mensaje: string, label: string) => Promise<unknown>
}

export function EstadoServicio({ instancia, ocupado, onAplicar }: Props) {
  const [estado, setEstado] = useState<ServicioEstado>(instancia.servicio_estado)
  const [mensaje, setMensaje] = useState(instancia.servicio_mensaje)

  // Se resincroniza cuando la instancia cambia por cualquier otra acción de la
  // pantalla: sin esto, aplicar un cambio y después tocar otro botón mandaría
  // de vuelta el estado que el formulario tenía cargado de antes.
  useEffect(() => {
    setEstado(instancia.servicio_estado)
    setMensaje(instancia.servicio_mensaje)
  }, [instancia.servicio_estado, instancia.servicio_mensaje])

  const opcion = OPCIONES_SERVICIO.find((o) => o.estado === estado) ?? OPCIONES_SERVICIO[0]
  const llevaMensaje = estado !== 'activo'
  const sinCambios = estado === instancia.servicio_estado
    && (!llevaMensaje || mensaje === instancia.servicio_mensaje)

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          Estado del servicio
          <Badge variant={variantePorEstado(instancia.servicio_estado)}>
            {instancia.servicio_estado}
          </Badge>
        </CardTitle>
        <CardDescription>
          Controla el acceso de «{instancia.nombre || instancia.slug}» al sistema. No apaga el
          contenedor: para eso están Iniciar / Detener, arriba.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid max-w-xl gap-4">
        <div className="grid gap-2">
          <Label htmlFor="servicio-estado">Estado</Label>
          <Select
            value={estado}
            disabled={ocupado}
            onValueChange={(v) => setEstado(v as ServicioEstado)}
          >
            <SelectTrigger id="servicio-estado" className="w-56">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {OPCIONES_SERVICIO.map((o) => (
                <SelectItem key={o.estado} value={o.estado}>
                  {o.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="text-sm text-muted-foreground">{opcion.descripcion}</p>
        </div>

        {llevaMensaje && (
          <div className="grid gap-2">
            <Label htmlFor="servicio-mensaje">Mensaje para el cliente</Label>
            <Input
              id="servicio-mensaje"
              value={mensaje}
              onChange={(e) => setMensaje(e.target.value)}
              placeholder="Ej.: factura de agosto impaga"
            />
            <p className="text-sm text-muted-foreground">
              Lo lee el cliente. Al volver a Activo se borra solo.
            </p>
          </div>
        )}

        <div>
          <Button
            disabled={ocupado || sinCambios}
            onClick={() => onAplicar(opcion.accion, llevaMensaje ? mensaje : '', opcion.label)}
          >
            {ocupado ? 'Aplicando…' : 'Aplicar'}
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
