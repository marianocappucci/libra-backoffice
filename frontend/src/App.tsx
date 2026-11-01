import type { ReactNode } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'

import { useAuth } from './auth'
import { Layout } from './components/Layout'
import { Login } from './pages/Login'
import { Apariencia } from './pages/Apariencia'
import { Instancia } from './pages/Instancia'
import { Instancias } from './pages/Instancias'
import { Revendedor, Revendedores } from './pages/Revendedores'
import { Salud } from './pages/Salud'
import { Seguridad } from './pages/Seguridad'

function RutaProtegida({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  if (loading) {
    return (
      <div className="flex min-h-svh items-center justify-center text-sm text-muted-foreground">
        Cargando…
      </div>
    )
  }
  if (!user) return <Navigate to="/login" replace />
  return <Layout>{children}</Layout>
}

/** La ficha de una instancia, con la sesión resuelta: la pestaña «Marca» depende de las features del producto. */
function FichaDeInstancia() {
  const { user } = useAuth()
  return <Instancia conMarca={user?.features?.includes('marca') ?? false} />
}

/** El inicio: en la consola de revendedores no hay instancias propias, y el Layout siempre entra por `/instancias`. */
function PantallaDeInstancias() {
  const { user } = useAuth()
  if (user?.features?.includes('revendedores')) return <Navigate to="/revendedores" replace />
  return <Instancias />
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      {/* Sin `/forgot-password`: las credenciales del superadmin salen del
          entorno, no de una tabla — no hay nada que recuperar por correo. */}
      <Route
        path="/instancias"
        element={
          <RutaProtegida>
            <PantallaDeInstancias />
          </RutaProtegida>
        }
      />
      <Route
        path="/instancias/:slug"
        element={
          <RutaProtegida>
            <FichaDeInstancia />
          </RutaProtegida>
        }
      />
      <Route
        path="/revendedores"
        element={
          <RutaProtegida>
            <Revendedores />
          </RutaProtegida>
        }
      />
      <Route
        path="/revendedores/:id"
        element={
          <RutaProtegida>
            <Revendedor />
          </RutaProtegida>
        }
      />
      <Route
        path="/salud"
        element={
          <RutaProtegida>
            <Salud />
          </RutaProtegida>
        }
      />
      <Route
        path="/apariencia"
        element={
          <RutaProtegida>
            <Apariencia />
          </RutaProtegida>
        }
      />
      <Route
        path="/seguridad"
        element={
          <RutaProtegida>
            <Seguridad />
          </RutaProtegida>
        }
      />
      <Route path="*" element={<Navigate to="/instancias" replace />} />
    </Routes>
  )
}
