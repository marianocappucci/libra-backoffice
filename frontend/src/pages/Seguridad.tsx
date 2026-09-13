// Doble factor (TOTP) del superadmin del backoffice.
//
// Encender no activa nada todavía: `iniciar` sólo genera un secreto pendiente
// y devuelve el QR para escanear. Recién queda `activo` cuando se confirma con
// un código vigente del autenticador — por eso el secreto se ve una vez, acá,
// y desaparece del estado de React apenas se confirma (o se cancela). No hay
// forma de recuperarlo después: si se perdió antes de confirmar, se cancela y
// se enciende de nuevo.
//
// Apagar pide el mismo tipo de código: sin uno vigente, no hay forma de
// desactivar el doble factor de la sesión, ni siquiera desde este backoffice.
import { useCallback, useEffect, useState } from 'react'
import { Copy, Check, ShieldCheck } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'

import { ApiError, backoffice, type TotpEstado, type TotpIniciado } from '../api'

function describirError(err: unknown): string {
  if (err instanceof ApiError) return err.detail
  return 'Error de conexión.'
}

// El secreto se muestra agrupado de a 4 para que sea más fácil de copiar a
// mano si el QR no se puede escanear (p.ej. cargándolo en otro dispositivo).
function agrupado(secreto: string): string {
  return (secreto.match(/.{1,4}/g) ?? [secreto]).join(' ')
}

type Modo = 'ninguno' | 'activando' | 'desactivando'

export function Seguridad() {
  const [estado, setEstado] = useState<TotpEstado | null>(null)
  const [cargando, setCargando] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [ocupado, setOcupado] = useState(false)

  const [modo, setModo] = useState<Modo>('ninguno')
  const [iniciado, setIniciado] = useState<TotpIniciado | null>(null)
  const [codigo, setCodigo] = useState('')
  const [copiado, setCopiado] = useState(false)
  const [errorForm, setErrorForm] = useState<string | null>(null)

  const recargar = useCallback(async () => {
    setEstado(await backoffice.totp())
  }, [])

  useEffect(() => {
    setCargando(true)
    recargar()
      .catch((err) => setError(describirError(err)))
      .finally(() => setCargando(false))
  }, [recargar])

  function cerrarPanel() {
    setModo('ninguno')
    setIniciado(null)
    setCodigo('')
    setCopiado(false)
    setErrorForm(null)
  }

  async function encender() {
    setOcupado(true)
    setError(null)
    setAviso(null)
    try {
      const r = await backoffice.iniciarTotp()
      setIniciado(r)
      setModo('activando')
      setCodigo('')
      setErrorForm(null)
    } catch (err) {
      setError(describirError(err))
    } finally {
      setOcupado(false)
    }
  }

  function pedirApagado() {
    setModo('desactivando')
    setCodigo('')
    setErrorForm(null)
    setAviso(null)
  }

  async function confirmar(e: React.FormEvent) {
    e.preventDefault()
    setOcupado(true)
    setErrorForm(null)
    try {
      await backoffice.confirmarTotp(codigo.trim())
      // El secreto no sobrevive a una confirmación exitosa: ni en pantalla,
      // ni en el estado de React.
      cerrarPanel()
      await recargar()
      setAviso('Listo: desde el próximo inicio de sesión se pide el código.')
    } catch (err) {
      setErrorForm(describirError(err))
    } finally {
      setOcupado(false)
    }
  }

  async function desactivar(e: React.FormEvent) {
    e.preventDefault()
    setOcupado(true)
    setErrorForm(null)
    try {
      await backoffice.desactivarTotp(codigo.trim())
      cerrarPanel()
      await recargar()
      setAviso('Doble factor desactivado.')
    } catch (err) {
      setErrorForm(describirError(err))
    } finally {
      setOcupado(false)
    }
  }

  if (cargando) return <p className="text-sm text-muted-foreground">Cargando…</p>
  if (!estado) {
    return (
      <p className="text-sm font-medium text-destructive">
        {error ?? 'No se pudo cargar el estado del doble factor.'}
      </p>
    )
  }

  // Deshabilitado si el secreto viene del entorno (no hay nada que tocar acá),
  // si este backoffice no tiene dónde guardar uno nuevo, o mientras hay un
  // panel abierto o una request en vuelo — para no disparar un segundo
  // `iniciar`/`desactivar` encima del que ya está en curso.
  const soloLectura = estado.origen === 'entorno'
  const sinDondeGuardar = !estado.enrolable && !estado.activo
  const switchDeshabilitado = soloLectura || sinDondeGuardar || ocupado || modo !== 'ninguno'

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex flex-wrap items-center gap-2">
            <ShieldCheck className="h-4 w-4" />
            Doble factor (TOTP)
            {estado.activo && <Badge>Activo</Badge>}
          </CardTitle>
          <CardDescription>
            Con el doble factor encendido, el login pide además el código de 6 dígitos de
            una app autenticadora (Google Authenticator, Authy, 1Password, Bitwarden).
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center gap-3">
            <Switch
              id="totp-switch"
              aria-label="Doble factor (TOTP)"
              checked={estado.activo}
              disabled={switchDeshabilitado}
              onCheckedChange={(checked) => {
                if (checked) void encender()
                else pedirApagado()
              }}
            />
            <Label htmlFor="totp-switch" className="font-normal">
              {estado.activo ? 'Encendido' : 'Apagado'}
            </Label>
          </div>

          {soloLectura && (
            <p className="text-sm text-muted-foreground">
              Configurado en el servidor (<code>ADMIN_PANEL_TOTP_SECRET</code>). Se cambia
              desde el .env del backoffice.
            </p>
          )}
          {!soloLectura && sinDondeGuardar && (
            <p className="text-sm text-muted-foreground">
              Este backoffice no tiene dónde guardar el secreto (falta{' '}
              <code>ADMIN_PANEL_ESTADO_PATH</code>).
            </p>
          )}

          {error && <p className="text-sm font-medium text-destructive">{error}</p>}
          {aviso && <p className="text-sm font-medium text-primary">{aviso}</p>}

          {modo === 'activando' && iniciado && (
            <div className="space-y-4 rounded-md border p-4">
              <p className="text-sm text-muted-foreground">
                Hasta que confirmes con un código, el doble factor no queda activo.
              </p>

              <div className="flex flex-wrap items-start gap-4">
                <div className="inline-block rounded-md bg-white p-3">
                  <img
                    src={iniciado.qr}
                    alt="Código QR para escanear con la app autenticadora y activar el doble factor"
                    width={200}
                    height={200}
                  />
                </div>

                <div className="grid gap-2">
                  <Label htmlFor="totp-secreto">O cargalo a mano</Label>
                  <div className="flex items-center gap-2">
                    <code
                      id="totp-secreto"
                      className="rounded bg-muted px-3 py-2 text-sm font-bold tracking-widest"
                    >
                      {agrupado(iniciado.secreto)}
                    </code>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        void navigator.clipboard?.writeText(iniciado.secreto)
                        setCopiado(true)
                      }}
                    >
                      {copiado
                        ? <><Check className="mr-1 h-4 w-4" /> Copiado</>
                        : <><Copy className="mr-1 h-4 w-4" /> Copiar</>}
                    </Button>
                  </div>
                </div>
              </div>

              <form onSubmit={confirmar} className="grid max-w-xs gap-2">
                <Label htmlFor="totp-codigo-confirmar">Código del autenticador</Label>
                <Input
                  id="totp-codigo-confirmar"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  maxLength={6}
                  autoFocus
                  value={codigo}
                  onChange={(e) => setCodigo(e.target.value)}
                />
                {errorForm && <p className="text-sm font-medium text-destructive">{errorForm}</p>}
                <div className="flex gap-2">
                  <Button type="submit" disabled={ocupado || !codigo.trim()}>
                    {ocupado ? 'Confirmando…' : 'Confirmar'}
                  </Button>
                  <Button type="button" variant="outline" disabled={ocupado} onClick={cerrarPanel}>
                    Cancelar
                  </Button>
                </div>
              </form>
            </div>
          )}

          {modo === 'desactivando' && (
            <form onSubmit={desactivar} className="grid max-w-xs gap-2 rounded-md border p-4">
              <Label htmlFor="totp-codigo-desactivar">
                Código del autenticador, para desactivar
              </Label>
              <Input
                id="totp-codigo-desactivar"
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={6}
                autoFocus
                value={codigo}
                onChange={(e) => setCodigo(e.target.value)}
              />
              {errorForm && <p className="text-sm font-medium text-destructive">{errorForm}</p>}
              <div className="flex gap-2">
                <Button type="submit" variant="destructive" disabled={ocupado || !codigo.trim()}>
                  {ocupado ? 'Desactivando…' : 'Desactivar'}
                </Button>
                <Button type="button" variant="outline" disabled={ocupado} onClick={cerrarPanel}>
                  Cancelar
                </Button>
              </div>
            </form>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
