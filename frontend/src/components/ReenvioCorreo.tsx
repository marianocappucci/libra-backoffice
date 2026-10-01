// Correo de reenvío de una instancia. Piloto: Contalibra.
//
// El backoffice no edita el destino: eso lo carga el cliente en SU propio
// panel (`GET/PUT /api/config/reenvio-correo` de la instancia). Acá sólo se
// lee lo que cargó y, con un click de un humano administrativo, se lo aplica
// de verdad en el servidor de correo —la misma pieza (SSH) que usa el alta de
// instancia—. Si la feature no está habilitada para este producto, el
// backoffice devuelve 404 y esta tarjeta ni se monta (ver `Instancia.tsx`).
import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

import { ApiError, backoffice } from '../api'

type Props = {
  slug: string
}

function describirError(err: unknown): string {
  if (err instanceof ApiError) return err.detail
  return 'Error de conexión.'
}

export function ReenvioCorreo({ slug }: Props) {
  const [destino, setDestino] = useState<string | null>(null)
  const [cargando, setCargando] = useState(true)
  const [aplicando, setAplicando] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)

  useEffect(() => {
    setCargando(true)
    setError(null)
    backoffice.reenvioCorreo(slug)
      .then((r) => setDestino(r.destino))
      .catch((err) => setError(describirError(err)))
      .finally(() => setCargando(false))
  }, [slug])

  async function aplicar() {
    setAplicando(true)
    setError(null)
    setAviso(null)
    try {
      const r = await backoffice.aplicarReenvioCorreo(slug)
      if (r.aplicado) {
        setAviso(`Aplicado: el correo de la instancia ahora reenvía a ${r.destino}.`)
      } else {
        // `aplicado: false` no es "no se hizo nada": el cliente no tiene
        // destino cargado, y el backend igual sacó cualquier reenvío previo
        // del servidor de correo (quitar_reenvio es un no-op si no había
        // ninguno) — ver `aplicar_reenvio_correo` en config_instancia.py.
        setAviso('Sin destino cargado: se sacó cualquier reenvío previo del servidor de correo.')
      }
      setDestino(r.destino ?? null)
    } catch (err) {
      setError(describirError(err))
    } finally {
      setAplicando(false)
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Correo de reenvío</CardTitle>
        <CardDescription>
          Destino que el cliente cargó en su propio panel. «Aplicar» lo escribe de verdad en el
          servidor de correo; hasta entonces, el reenvío real puede no coincidir con esto.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {cargando ? (
          <p className="text-sm text-muted-foreground">Cargando…</p>
        ) : (
          <p className="text-sm">
            {destino ? <span className="font-mono">{destino}</span> : (
              <span className="text-muted-foreground">Sin cargar</span>
            )}
          </p>
        )}

        {error && <p className="text-sm font-medium text-destructive">{error}</p>}
        {aviso && <p className="text-sm font-medium text-primary">{aviso}</p>}

        <Button
          variant="outline"
          size="sm"
          disabled={cargando || aplicando}
          onClick={aplicar}
        >
          {aplicando ? 'Aplicando…' : 'Aplicar'}
        </Button>
      </CardContent>
    </Card>
  )
}
