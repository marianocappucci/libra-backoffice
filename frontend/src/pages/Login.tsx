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
  // Segundo factor (F2, libraauth v0.36.0): la sonda dice si este backoffice
  // tiene `ADMIN_PANEL_TOTP_SECRET`; sólo entonces aparece el campo del código.
  // La misma imagen corre con y sin 2FA según su `.env`, por eso se pregunta
  // en runtime y no se decide en el build.
  totpPath: '/api/login/opciones',
  // Captcha «No soy un robot» (libraauth v0.40.0, libra-ui v0.69.0). El
  // backend lo exige siempre; la sonda es el mismo GET del desafío, y
  // «Ingresar» queda deshabilitado hasta tildar la casilla.
  captchaPath: '/api/captcha',
  // El detalle real del backend: con segundo factor el 401 dice "usuario,
  // contraseña o código", y el 429 del bloqueo dice cuánto esperar. El
  // genérico de libra-ui taparía los dos.
  formatError: (err) => err.detail,
})
