import { createLogin } from 'libra-ui/Login'

import { useAuth } from '../auth'
import type { Superadmin } from '../api'

export const Login = createLogin<Superadmin>({
  productName: 'Backoffice',
  productInitial: 'B',
  redirectTo: '/instancias',
  useAuth,
  // Sin `forgotPasswordPath`: las credenciales del superadmin salen del
  // entorno (`ADMIN_PANEL_USER`/`ADMIN_PANEL_PASSWORD`), no de una tabla, así
  // que no hay nada que recuperar por correo. Mostrar el enlace sería un link
  // a un 404. En su lugar va un texto (libra-ui v0.69.1), para que la pantalla
  // diga qué hacer. No nombra el archivo del servidor: esta pantalla es
  // pública, y dónde viven las credenciales no tiene por qué estar a la vista.
  forgotPasswordHint: '¿Olvidaste tu contraseña? La cambia quien administra el servidor.',
  //
  // Segundo factor: ya no hay sonda ni campo arriba (libra-ui v0.70.0). La
  // pantalla pide usuario, contraseña y captcha; si el backend contesta que
  // falta el código, abre un modal con un casillero por dígito y lo manda a
  // `segundoFactorPath` (ver `auth.ts`). Lo decide el backend en cada login,
  // así que la misma imagen sigue sirviendo con y sin 2FA.
  //
  // Captcha «No soy un robot» (libraauth v0.40.0, libra-ui v0.69.0). El
  // backend lo exige siempre; la sonda es el mismo GET del desafío, y
  // «Ingresar» queda deshabilitado hasta tildar la casilla.
  captchaPath: '/api/captcha',
  // El detalle real del backend: con segundo factor el 401 dice "usuario,
  // contraseña o código", y el 429 del bloqueo dice cuánto esperar. El
  // genérico de libra-ui taparía los dos.
  formatError: (err) => err.detail,
})
