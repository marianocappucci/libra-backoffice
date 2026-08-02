import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { type ColumnDef } from '@tanstack/react-table'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

import { DataTable, sortableHeader } from '../components/data-table'
import { ApiError, backoffice, type Instancia } from '../api'

function describirError(err: unknown): string {
  if (err instanceof ApiError) return err.detail
  return 'Error de conexión.'
}

function VarianteEstado({ estado }: { estado: string }) {
  const ok = estado === 'running'
  return <Badge variant={ok ? 'default' : 'outline'}>{estado}</Badge>
}

export function Instancias() {
  const [instancias, setInstancias] = useState<Instancia[]>([])
  const [cargando, setCargando] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    backoffice
      .instancias()
      .then((r) => setInstancias(r.instancias))
      .catch((err) => setError(describirError(err)))
      .finally(() => setCargando(false))
  }, [])

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
        header: 'Estado',
        cell: ({ row }) => <VarianteEstado estado={row.original.estado} />,
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
      <CardHeader>
        <CardTitle>Instancias</CardTitle>
      </CardHeader>
      <CardContent>
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
