import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { type ColumnDef } from '@tanstack/react-table'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

import { AltaInstancia } from '../components/AltaInstancia'
import { DataTable, sortableHeader } from '../components/data-table'
import { ApiError, backoffice, type Instancia, type Plan } from '../api'

function describirError(err: unknown): string {
  if (err instanceof ApiError) return err.detail
  return 'Error de conexión.'
}

function VarianteEstado({ estado }: { estado: string }) {
  const ok = estado === 'running'
  return <Badge variant={ok ? 'default' : 'outline'}>{estado}</Badge>
}

export function Instancias() {
  // La baja redirige acá y trae su aviso en el estado de la navegación: incluye
  // la ruta del backup, que es la única copia que queda de esos datos.
  const { state } = useLocation()
  const avisoDeBaja = (state as { aviso?: string } | null)?.aviso ?? null

  const [instancias, setInstancias] = useState<Instancia[]>([])
  const [planes, setPlanes] = useState<Plan[]>([])
  const [cargando, setCargando] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Devuelve los slugs porque el alta los necesita para distinguir un alta que
  // falló de una que el navegador no llegó a ver terminar.
  const recargar = useCallback(async () => {
    const { instancias } = await backoffice.instancias()
    setInstancias(instancias)
    return instancias.map((i) => i.slug)
  }, [])

  useEffect(() => {
    // Los planes se piden acá y no dentro del diálogo para que el formulario de
    // alta abra con el select ya poblado.
    Promise.all([recargar(), backoffice.planes().catch(() => [])])
      .then(([, p]) => setPlanes(p))
      .catch((err) => setError(describirError(err)))
      .finally(() => setCargando(false))
  }, [recargar])

  const columnas = useMemo<ColumnDef<Instancia>[]>(
    () => [
      { accessorKey: 'slug', header: sortableHeader('Instancia') },
      { accessorKey: 'nombre', header: 'Nombre' },
      {
        accessorKey: 'domain',
        header: 'Dominio',
        cell: ({ row }) => row.original.domain || <span className="text-muted-foreground">—</span>,
      },
      { accessorKey: 'plan', header: sortableHeader('Plan') },
      {
        accessorKey: 'estado',
        header: 'Contenedor',
        cell: ({ row }) => <VarianteEstado estado={row.original.estado} />,
      },
      {
        // Columna propia y no un badge más en «Contenedor»: son dos ejes
        // independientes. Un cliente suspendido corre igual —el contenedor
        // dice `running`— y le devuelve 503 a todo el mundo. Sin esta columna
        // el listado de un producto con un cliente cortado se ve idéntico al
        // de uno donde está todo bien.
        accessorKey: 'servicio_estado',
        header: sortableHeader('Servicio'),
        cell: ({ row }) => {
          const estado = row.original.servicio_estado
          if (estado === 'activo') return <span className="text-muted-foreground">activo</span>
          return <Badge variant={estado === 'suspendido' ? 'destructive' : 'secondary'}>{estado}</Badge>
        },
      },
      {
        id: 'acciones',
        header: '',
        cell: ({ row }) => (
          <Button asChild variant="outline" size="sm">
            <Link to={`/instancias/${row.original.slug}`}>Administrar</Link>
          </Button>
        ),
      },
    ],
    [],
  )

  if (cargando) return <p className="text-sm text-muted-foreground">Cargando…</p>

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-4 space-y-0">
        <CardTitle>Instancias</CardTitle>
        <AltaInstancia
          planes={planes}
          slugsPrevios={instancias.map((i) => i.slug)}
          recargar={recargar}
        />
      </CardHeader>
      <CardContent className="space-y-4">
        {avisoDeBaja && (
          <p className="rounded-md border p-3 text-sm font-medium break-all">{avisoDeBaja}</p>
        )}
        {error && <p className="text-sm font-medium text-destructive">{error}</p>}
        {!error && instancias.length === 0 && (
          <p className="text-sm text-muted-foreground">
            Todavía no hay ninguna instancia dada de alta.
          </p>
        )}
        {instancias.length > 0 && <DataTable columns={columnas} data={instancias} />}
      </CardContent>
    </Card>
  )
}
