# Cumplimiento de requisitos — aplicación de escritorio

Estado tras las tareas #23–#30. Los tests automáticos (`pytest`) cubren la lógica y la interfaz en modo
sin pantalla. **Nada se ha verificado visualmente en una ventana real, en Windows, con un broker MQTT real,
con la pasarela/banda pectoral reales ni con la app móvil real.** "Cumple" significa "implementado y probado con tests".

Leyenda: ✅ cumple · 🟡 cumple con matices · 📱 corresponde a la app móvil / pasarela (no aplica al escritorio)

## Matices que afectan a varios requisitos
- **El formato de sincronización lo ha diseñado el lado del escritorio** (`docs/contrato_sincronizacion.md`).
  La app móvil aún no lo genera: quien la desarrolle debe adoptarlo o acordar otro.
- La sincronización es **por archivo/carpeta** (sin servidor) y **síncrona**: con paquetes muy grandes la interfaz se queda parada unos segundos.
- El ECG histórico se guarda solo como **envolvente de 1 s (mín/máx)**, no la señal a 100 Hz.
- Las observaciones son **orientativas, no diagnósticas**; sus umbrales no están validados clínicamente.
- Los periodos de conservación son configurables en `settings.json` (valores por defecto: 30 días periódico, 365 actividades).
- Eliminar una cuenta no borra copias externas (CSV exportados, archivos de la carpeta de intercambio, datos del móvil).

## Matriz

| RF | Estado | Dónde / cómo |
|---|---|---|
| 01 Inicio de sesión | ✅ | Correo + contraseña (scrypt) en `servicio_auth`, `login_dialog` |
| 02 Cierre de sesión | ✅ | `SesionActiva.liberar()` cierra MQTT, ViewModel y BD; vuelve al login |
| 03 Mediciones por usuario | ✅ | `RepositorioHistorial` atado a `usuario_id`; tests de aislamiento |
| 04–07 Dispositivo/BLE | 📱 | El escritorio recibe por MQTT (`docs/contrato_mqtt.md`) |
| 08 Tiempo real | 🟡 | Se muestra en la pestaña "Tiempo real" (el requisito habla de la app móvil) |
| 09 Gráficas | ✅ | Tiempo real (ECG) e historial (`grafica_serie`) |
| 10, 11 ECG/estado de conexión (móvil) | 📱 | El escritorio además muestra ECG y estado de enlace |
| 12 Registro automático | ✅ | Grabador periódico del ViewModel (10 s, configurable) |
| 13 Fecha y hora | ✅ | `ts` en cada medición |
| 14 Historial local sin Internet (móvil) | 📱 | El escritorio también es 100 % local |
| 15 Filtro por fechas | ✅ | `SelectorRango` |
| 16 Gráfica del historial | ✅ | Resolución automática/minuto/hora/día; periodos largos resumidos |
| 17 Conservación al cerrar | ✅ | SQLite; tests de reapertura |
| 18 Transferencia móvil→escritorio | 🟡 | Importación de paquetes JSON de una carpeta (`servicio_sync`); no es automática por red |
| 19 Consulta de lo sincronizado | ✅ | Historial/Actividades + exportación CSV |
| 20 Integridad | ✅ | Todo o nada, SHA-256, `uid` único por usuario (sin duplicados) |
| 21 Estado de sincronización | ✅ | Barra de estado, botón "Sincronizar ahora", estados PENDIENTE/SINCRONIZADO/ERROR con reintento |
| 22 Estadísticas | ✅ | Media, mínimo, máximo, recuento (`domain/analisis`) |
| 23 Generación de observaciones | ✅ | `domain/observaciones`, `servicio_observaciones` |
| 24 Consulta de observaciones | ✅ | `panel_observaciones` |
| 25 Patrones | 🟡 | Reglas sencillas y orientativas |
| 26 Registro sin Internet | 📱 | |
| 27 Interrupciones | ✅ | Huecos visibles en gráfica y tabla, no se rellenan |
| 28 Datos pendientes de sincronizar | ✅ | Los paquetes con error se conservan y se reintentan |
| 29 Actualización automática de observaciones | ✅ | Temporizador configurable + al arrancar/sincronizar |
| 30, 31 Registro detallado de actividad | 📱 | El escritorio solo recibe actividades por sincronización |
| 32 Consulta de actividades | ✅ | Pestaña "Actividades" con detalle |
| 33 Almacenamiento del ECG | 🟡 | Solo envolvente 1 s |
| 34 ECG compacto | ✅ | `GraficaEcg` |
| **35 Zoom del ECG (opcional)** | ✅ | `PanelEcgZoom`: intervalo arrastrable + Acercar/Alejar/◀/▶/Restablecer; límite = resolución almacenada (1 s) |
| 36 Sincronizar al iniciar | ✅ | `vm.arrancar()` |
| 37 Segundo plano (móvil) | 📱 | |
| **38 Eliminar mediciones (opcional)** | ✅ | Seleccionadas, por periodo y actividades, siempre con confirmación explícita |
| **39 Eliminar cuenta (opcional)** | ✅ | `RepositorioCuentas.eliminar` (transacción, `secure_delete`), contraseña de nuevo, doble confirmación + palabra `ELIMINAR` |
| 41 Registro de usuarios | ✅ | |
| 42 Autenticación multifactor | ✅ | TOTP |
| 43 Tipo de registro | ✅ | PERIODICO / ACTIVIDAD / AMBOS |
| 44 Actividades independientes | ✅ | Retención propia |
| 45 Consulta diferenciada | ✅ | Pestañas separadas; ámbito en consultas y CSV |
| 46 Eliminación por vencimiento | ✅ | `purgar()` al arrancar |
| 47 Análisis periódico | ✅ | Observaciones DIARIA |
| 48 Análisis de actividades | ✅ | Observaciones ACTIVIDAD |
| 49 Asociación a periodo/actividad | ✅ | `tipo` + `clave` + `actividad_id` |
| 50 Tipo de actividad | 📱/🟡 | Se muestra el tipo que trae el paquete |
| 40 Conservación diferenciada | ✅ | Ver 44 y 46 |

## Semántica del borrado (RF-38, 45)
- Borrar del historial periódico: las PERIODICO se eliminan; las AMBOS pasan a ACTIVIDAD.
- Borrar una actividad: sus mediciones ACTIVIDAD se eliminan; las AMBOS vuelven a PERIODICO.
- Las observaciones diarias de días que se quedan sin mediciones se eliminan.

## Pruebas
`tests/test_e2e.py` recorre: paquete demo → sincronización → consultas → observaciones → CSV → borrar medición → borrar cuenta.
