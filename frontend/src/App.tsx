import type { ReactNode } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'

import { useAuth } from './auth'
import { Layout } from './components/Layout'
import { Login } from './pages/Login'
import { Instancia } from './pages/Instancia'
import { Instancias } from './pages/Instancias'
import { Salud } from './pages/Salud'

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
            <Instancias />
          </RutaProtegida>
        }
      />
      <Route
        path="/instancias/:slug"
        element={
          <RutaProtegida>
            <Instancia />
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
      <Route path="*" element={<Navigate to="/instancias" replace />} />
    </Routes>
  )
}
