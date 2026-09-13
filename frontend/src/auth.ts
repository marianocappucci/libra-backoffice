// Sesión del superadmin del backoffice.
//
// Se usa la factory `createAuthContext` de libra-ui en vez de la instancia
// pre-configurada porque el backoffice tiene sus propias rutas (`/api/login`,
// `/api/me`, `/api/logout`) y su propio tipo de usuario — mismo caso que
// Contalibra y Restolibra.
import { createAuthContext } from 'libra-ui/AuthContext'

import type { Superadmin } from './api'

export const { AuthProvider, useAuth } = createAuthContext<Superadmin>({
  mePath: '/api/me',
  loginPath: '/api/login',
  logoutPath: '/api/logout',
  // Paso 2 del login con segundo factor (libra-ui v0.70.0, libraauth v0.42.0):
  // si `/api/login` contesta `{requiere_codigo, desafio}`, la pantalla abre el
  // modal de los casilleros y manda `{desafio, codigo}` acá.
  segundoFactorPath: '/api/login/codigo',
})
