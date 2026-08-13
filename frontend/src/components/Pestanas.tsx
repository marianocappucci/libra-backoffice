/** El conmutador de pestañas del backoffice.
 *
 *  ## Es una copia deliberada del de `libra-ui/Configuracion`
 *
 *  El pedido fue "que se vea como en los sistemas", así que el marcado y las
 *  clases son las mismas que las de `createConfiguracion()`: nav con `border-b`,
 *  botón con `border-b-2` y `aria-current="page"` en la activa, icono de lucide
 *  a la izquierda del label. Si las dos divergen visualmente, esto es lo que hay
 *  que mirar primero.
 *
 *  No se importa de `libra-ui` por dos razones concretas, no por comodidad:
 *  allá el conmutador está **embebido** en `createConfiguracion` —no se exporta
 *  suelto— y este repo pinea `libra-ui#v0.10.0` mientras el paquete va por
 *  `v0.16.0`. Sacarlo de ahí sería exportar un componente nuevo en libra-ui,
 *  publicar versión, y subir el pin del backoffice siete minors de una: un
 *  cambio de riesgo bastante mayor que este archivo. Cuando ese pin se suba por
 *  otro motivo, esta duplicación es la primera candidata a borrarse.
 *
 *  ## Tampoco se usa `@/components/ui/tabs`
 *
 *  No está instalado en este repo (mismo motivo por el que libra-ui no lo usa),
 *  y traer Radix entero por un conmutador de cuatro botones no se paga.
 *
 *  ## La pestaña activa va en la URL
 *
 *  `?seccion=correo`, igual que en los productos: se puede mandar "andá a
 *  Usuarios de acme" por mensaje, y el botón «atrás» del navegador vuelve a la
 *  pestaña anterior en vez de sacar de la instancia.
 */
import { type ComponentType, type ReactNode } from 'react'
import { useSearchParams } from 'react-router-dom'

export type Pestana = {
  clave: string
  label: string
  icono?: ComponentType<{ className?: string }>
  contenido: ReactNode
}

type Props = {
  pestanas: Pestana[]
  /** Para el `aria-label` del nav: hay una sola pantalla con pestañas hoy, pero
   *  "Secciones" a secas no dice de qué. */
  etiqueta: string
}

export function Pestanas({ pestanas, etiqueta }: Props) {
  const [params, setParams] = useSearchParams()
  const pedida = params.get('seccion')
  // Una `?seccion=` que no existe cae en la primera en vez de dejar la pantalla
  // en blanco: el link viejo de una pestaña renombrada sigue llevando a algo.
  const actual = pestanas.find((p) => p.clave === pedida) ?? pestanas[0]

  return (
    <div className="grid gap-4">
      <nav className="flex flex-wrap gap-1 border-b" aria-label={etiqueta}>
        {pestanas.map((p) => {
          const activa = p.clave === actual.clave
          const Icono = p.icono
          return (
            <button
              key={p.clave}
              type="button"
              aria-current={activa ? 'page' : undefined}
              onClick={() => setParams({ seccion: p.clave })}
              className={
                'flex items-center gap-2 border-b-2 px-3 py-2 text-sm transition-colors '
                + (activa
                  ? 'border-primary font-medium text-foreground'
                  : 'border-transparent text-muted-foreground hover:text-foreground')
              }
            >
              {Icono && <Icono className="h-4 w-4" />}
              {p.label}
            </button>
          )
        })}
      </nav>

      {/* Sólo la activa se monta, como en los productos. Es lo que hace que el
          SMTP y los usuarios de la instancia se pidan al entrar a su pestaña y
          no en cada carga de la pantalla. */}
      <div className="grid gap-4">{actual.contenido}</div>
    </div>
  )
}
