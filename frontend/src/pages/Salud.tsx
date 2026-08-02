import { useEffect, useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

import { ApiError, backoffice, type EstadoInstancia, type Salud as TSalud } from '../api'

function describirError(err: unknown): string {
  if (err instanceof ApiError) return err.detail
  return 'Error de conexión.'
}

function duracion(segundos: number): string {
  const dias = Math.floor(segundos / 86400)
  const horas = Math.floor((segundos % 86400) / 3600)
  const minutos = Math.floor((segundos % 3600) / 60)
  if (dias) return `${dias} d ${horas} h`
  if (horas) return `${horas} h ${minutos} min`
  return `${minutos} min`
}

function FilaInstancia({ estado }: { estado: EstadoInstancia }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 border-b py-2 last:border-0">
      <div className="min-w-0">
        <p className="truncate text-sm font-medium">{estado.nombre || estado.slug}</p>
        <p className="truncate text-xs text-muted-foreground">
          {estado.container || 'sin contenedor'}
          {estado.detalle && ` · ${estado.detalle}`}
        </p>
      </div>
      <Badge variant={estado.estado === 'ok' ? 'default' : 'destructive'}>{estado.estado}</Badge>
    </div>
  )
}

export function Salud() {
  const [salud, setSalud] = useState<TSalud | null>(null)
  const [cargando, setCargando] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    backoffice
      .salud()
      .then(setSalud)
      .catch((err) => setError(describirError(err)))
      .finally(() => setCargando(false))
  }, [])

  if (cargando) return <p className="text-sm text-muted-foreground">Cargando…</p>
  if (!salud) return <p className="text-sm font-medium text-destructive">{error}</p>

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>{salud.producto.nombre}</CardTitle>
          <CardDescription>
            Backoffice {salud.backoffice.version} · commit {salud.backoffice.commit}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          {/* El dato que delata un servicio que "responde 200" pero nunca se
              reinició después del último deploy. */}
          <p>
            <span className="text-muted-foreground">Levantado hace </span>
            {duracion(salud.backoffice.uptime_segundos)}
          </p>
          <p className="flex flex-wrap items-center gap-1">
            <span className="text-muted-foreground">Features: </span>
            {salud.features.map((f) => (
              <Badge key={f} variant="outline">
                {f}
              </Badge>
            ))}
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Instancias</CardTitle>
          <CardDescription>Se le pregunta a cada una por su propio /health.</CardDescription>
        </CardHeader>
        <CardContent>
          {salud.instancias.length === 0 && (
            <p className="text-sm text-muted-foreground">No hay instancias.</p>
          )}
          {salud.instancias.map((i) => (
            <FilaInstancia key={i.slug} estado={i} />
          ))}
        </CardContent>
      </Card>
    </div>
  )
}
