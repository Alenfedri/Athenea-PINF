# VitaBand (escritorio) · puesta en marcha

Monitoriza una banda pectoral ECG (100 Hz), guarda tu historial y analiza fatiga y forma. Funciona **en local**: tus datos no salen del PC.

## Arrancar (Windows 10/11)
1. Instala **Python 3.10+** desde python.org marcando *Add python.exe to PATH* (solo una vez).
2. Haz **doble clic en `VitaBand.bat`**. La primera vez instala lo necesario (1-3 min, con internet); después abre la app al instante.

*Alternativa sin Python en el otro PC:* en un PC con Python ejecuta `construir_exe.bat` y copia la carpeta `dist\VitaBand` entera; se abre con `VitaBand.exe`.

## Primer uso (5 minutos)
1. **Crea tu cuenta.** Pide verificación en dos pasos: escanea el QR con una app de autenticación (Google/Microsoft Authenticator) y escribe el código de 6 cifras.
2. **Sin banda a mano: marca `Modo Demo`** (arriba) y elige Reposo, Esfuerzo Z3 o Estrés. Verás el ECG a 100 Hz en directo. No guarda nada.
3. **Pulsa `Datos de ejemplo`** (úsalo en una cuenta de prueba). Carga ~12 semanas de entrenamientos **simulados**: Historial con mapa de calor, carga y forma (TSB), Laboratorio ECG con Poincaré y recorte de sesión, actividades con RPE y exportación PDF/PNG/CSV/TCX.
4. **Coach IA** (pestaña Coach): necesita [Ollama](https://ollama.com) instalado. La primera vez pide tu consentimiento para descargar el modelo (varios GB). Sin Ollama el resto de la app funciona igual. Con los datos de ejemplo, el Coach ya tiene fatiga y carga reales con las que razonar.

## Con la banda real
Conecta la banda (la app usa MQTT: `settings.json` → `mqtt`, por defecto `localhost:1883`) y pulsa Conectar. Los datos del móvil se importan por archivo en la carpeta `intercambio`.

## Dónde se guardan los datos
Junto a la app (`vitaband_historial.db`), o en la carpeta `datos` junto a `VitaBand.exe` si usas el ejecutable. Para empezar de cero, cierra la app y borra ese archivo.

## Importante
- Las calorías, la carga y la forma son **estimaciones orientativas, no diagnóstico**; VitaBand no es un producto sanitario.
- Probado con datos simulados y pruebas automáticas. **No** validado todavía con una banda real de uso prolongado, ni en equipos Windows distintos al de desarrollo.
- Si no abre: ejecuta `VitaBand.bat` desde una ventana de CMD para ver el error, o borra la carpeta `.venv` y reintenta.
