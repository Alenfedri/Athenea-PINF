# VitaBand Desktop: qué es y qué hace

Este documento describe lo que la aplicación de escritorio hace hoy, según el código del repositorio.
Lo que no está hecho, o depende de otra parte del sistema, se dice de forma expresa.

## 1. Qué es VitaBand y qué papel tiene esta aplicación

VitaBand es un dispositivo de medición biométrica que se lleva en el pecho, sujeto con una correa
(banda pectoral). Mide electrocardiograma (ECG), frecuencia cardíaca, frecuencia respiratoria,
temperatura cutánea y nivel de actividad física.

El sistema tiene tres piezas:

- **La banda pectoral** y una **pasarela** que recibe sus datos y los publica por MQTT. La pasarela la
  desarrolla otro compañero; en este repositorio solo existe un *mock* (simulación) hecho por él.
- **La app móvil** (Qt/QML), de otro compañero. Según los requisitos, es la que se conecta a la banda,
  registra actividades y guarda las mediciones del móvil.
- **Esta aplicación de escritorio** (Python + PySide6), que hace dos cosas:
  1. Muestra en tiempo real lo que publica la pasarela por MQTT y guarda una medición cada 10 segundos.
  2. Importa los datos que el móvil le entrega en forma de archivo y permite consultarlos, analizarlos,
     exportarlos y borrarlos.

Flujo de los datos:

```
banda pectoral ──(BLE)──> pasarela ──(MQTT)──> escritorio ─┐
                                                           ├─> base de datos SQLite local
app móvil ──(archivo JSON en una carpeta)──> escritorio ───┘
```

Todo se guarda en un único archivo SQLite en el propio ordenador (`vitaband_historial.db` por
defecto). No hay servidor ni nube.

## 2. Acceso y seguridad de cuentas

Al abrir el programa aparece una ventana de acceso con tres pantallas.

- **Crear cuenta:** nombre, correo, contraseña y repetición de la contraseña. La contraseña necesita al
  menos 10 caracteres, una letra y un número. Se guarda solo un resumen (hash scrypt), nunca la contraseña.
- **Inicio de sesión:** correo y contraseña. Después hace falta un **código de 6 dígitos** de una app
  autenticadora (TOTP: Google Authenticator, Microsoft Authenticator, Authy…). La primera vez, la ventana
  muestra una clave de configuración para añadirla a la app (se introduce a mano; no hay código QR).
- **Bloqueo por intentos:** tras 5 fallos seguidos la cuenta se bloquea 5 minutos.

Una vez dentro:

- **Cerrar sesión** (botón arriba a la derecha) cierra la conexión MQTT y la base de datos y vuelve a
  la ventana de acceso.
- **Eliminar cuenta** (botón arriba a la derecha) pide dos confirmaciones: primero un aviso de lo que se
  va a perder; después un cuadro donde hay que escribir `ELIMINAR` y la contraseña. Si la contraseña es
  correcta, se borran en una sola operación la cuenta y todos sus datos (mediciones, actividades, ECG,
  observaciones y estado de sincronización). Si es incorrecta, no se borra nada y el fallo cuenta para el
  bloqueo por intentos. No se borran las copias que el usuario haya sacado fuera: CSV exportados y
  archivos de la carpeta de intercambio.

Cada usuario solo ve sus datos: todo lo guardado va asociado a su cuenta. Varias cuentas pueden compartir
el mismo ordenador.

## 3. Recorrido por la interfaz

La ventana principal tiene una barra superior, tres pestañas y una barra de estado.

**Barra superior:** estado de la conexión con la pasarela (Desconectado, Conectando, Calibrando,
Conectado, Error de comunicación), botones *Conectar* y *Desconectar*, *Sincronizar ahora*,
*Exportar historial (CSV)*, el nombre de usuario, *Eliminar cuenta* y *Cerrar sesión*.

**Barra de estado (abajo):** estado de la sincronización con el móvil. El texto muestra el resumen y un
tooltip detalla archivos sincronizados, pendientes y con error.

### Pestaña «Tiempo real»

- Cuatro tarjetas: frecuencia cardíaca, frecuencia respiratoria, temperatura y nivel de actividad.
- Un banner con el aviso que envía el dispositivo.
- Una gráfica del ECG a 100 Hz con la ventana de los últimos 6 segundos.
- Una casilla para ver el ECG **crudo** en lugar del filtrado; envía la orden a la pasarela por MQTT.
- Durante los primeros 6 segundos tras conectar, el estado es *Calibrando* (la respiración necesita esa ventana).

Cada 10 segundos, mientras el estado es *Conectado*, se guarda una **medición periódica** (frecuencia
cardíaca, y respiración, temperatura y nivel de actividad si el valor es válido). Si el firmware envía una
media de BPM, se guarda esa; si no, el valor instantáneo. El ECG se guarda aparte, en forma
resumida (ver apartado 5). El ECG crudo no se guarda.

### Pestaña «Historial periódico»

Muestra las mediciones periódicas, tanto las guardadas por el escritorio como las importadas del móvil.

- **Selector de periodo:** fechas Desde/Hasta y atajos *Hoy*, *7 días*, *30 días* y *Todo*.
- **Variable:** frecuencia cardíaca, frecuencia respiratoria, temperatura cutánea o nivel de actividad.
- **Resolución:** automática, sin agrupar, por minuto, por hora o por día. Con periodos largos conviene
  agrupar; los grupos muestran media, mínimo y máximo.
- **Resumen:** número de registros, media, mínimo y máximo del periodo.
- **Gráfica y tabla** con los mismos datos. Los **huecos** (cuando no hay datos durante un rato) se ven
  sombreados en la gráfica y se indican en un aviso; no se rellenan ni se interpolan.
- **Observaciones del periodo:** textos automáticos (ver más abajo).
- **ECG histórico** con zoom (ver más abajo).
- **Borrado:**
  - *Eliminar seleccionadas*: borra las filas marcadas en la tabla (solo disponible con resolución «sin
    agrupar»).
  - *Eliminar periodo…*: borra todas las mediciones periódicas del rango elegido y dice cuántas son.
  - Los dos piden confirmación y avisan de que no se puede deshacer. Si una medición también pertenece a
    una actividad, se conserva dentro de esa actividad.

### Pestaña «Actividades»

Lista las actividades deportivas importadas desde el móvil: inicio, tipo, duración, número de mediciones,
frecuencia cardíaca media y máxima. El escritorio **no** crea actividades; solo las recibe por sincronización.
Al elegir una actividad se ve:

- una gráfica de la variable elegida durante la actividad,
- su ECG con zoom,
- una observación automática de la actividad,
- el botón **Eliminar actividad** (con confirmación): borra la actividad, sus mediciones propias y su
  observación. Las mediciones que también estaban en el historial periódico se conservan allí. El ECG
  guardado de ese tramo **no** se borra con la actividad (se elimina cuando vence su plazo de conservación).

### Zoom del ECG

El ECG histórico se dibuja en dos partes: una **vista general** del periodo, con un intervalo
arrastrable, y debajo un **detalle** de ese intervalo. Los botones *Acercar*, *Alejar*, *◀*, *▶* y
*Restablecer* mueven o cambian el tamaño del intervalo. El zoom llega hasta la resolución guardada (1
segundo), así que no se puede ampliar hasta ver latidos individuales. El ECG histórico solo se consulta
para periodos de hasta 7 días.

### Observaciones automáticas

Son textos orientativos, generados con reglas fijas, nunca un diagnóstico (cada texto lo advierte). Hay
tres tipos:

- **Diarias** sobre el historial periódico: valoran la frecuencia cardíaca, respiratoria y la temperatura en
  reposo frente a unos umbrales (por ejemplo, FC en reposo por encima de 100 o por debajo de 45 lpm) y
  mencionan las interrupciones.
- **Patrones recurrentes**: por ejemplo, diferencias de frecuencia cardíaca entre franjas del día que se
  repiten varios días.
- **De actividad**: resumen de la actividad (duración, FC media y máxima, nivel de esfuerzo respecto a
  la FC en reposo).

Se generan al iniciar sesión, tras cada sincronización y cada hora (configurable). Los umbrales son
orientativos y **no están validados clínicamente**.

### Exportación a CSV

*Exportar historial (CSV)* guarda **todas** las mediciones del usuario (periódicas y de actividades) en un
archivo con las columnas `fecha;hora;bpm;rpm;temp_c;nivel_actividad;etiqueta`. Va en UTF-8 con BOM,
separado por `;` y con coma decimal, para que Excel en español lo abra bien. No incluye el ECG.

### Conservación y borrado automático

Al iniciar sesión se eliminan los registros vencidos: **30 días** para el historial periódico y **365
días** para las actividades (valores configurables en `settings.json`). Una medición marcada como
periódica y de actividad a la vez, cuando vence como periódica, no se borra mientras se conserve su
actividad: pasa a ser solo de actividad. El ECG vencido se conserva si cae dentro de una actividad que
aún se conserva.

## 4. Cómo se comunica con la app móvil

No hay conexión directa. El móvil deja un archivo `.json` en la **carpeta de intercambio** (`intercambio/`
por defecto) y el escritorio lo importa. El archivo contiene el correo del usuario, sus actividades,
mediciones y, opcionalmente, bloques de ECG resumido.

- **Cuándo se importa:** al iniciar sesión, al pulsar *Sincronizar ahora* y automáticamente cada 60
  segundos (configurable; 0 la desactiva).
- **Todo o nada:** si un solo dato del archivo es inválido, se rechaza el archivo completo y no se
  importa nada. El motivo se muestra en la barra de estado.
- **Sin duplicados:** cada archivo se identifica por su contenido y cada medición/actividad por su `uid`.
  El móvil puede reexportar todo su historial y lo ya importado no se repite.
- **Estados:** `PENDIENTE`, `SINCRONIZADO` y `ERROR`. Los archivos con error se reintentan en cada
  sincronización.
- **Varios usuarios:** los archivos de otro correo se ignoran.

El formato exacto está en `docs/contrato_sincronizacion.md`. Para probar sin móvil:
`python tools/generar_paquete_demo.py --usuario tu@correo.com`, que crea un paquete con datos sintéticos.

**Importante:** este formato lo ha definido el lado del escritorio. La app móvil todavía no lo genera. El
desarrollador del móvil debe adoptarlo o acordar con el escritorio otro formato.

Con la pasarela, el escritorio habla por MQTT (tópicos `vitaband/{id}/telemetry`, `/status` y
`/control`), descrito en `docs/contrato_mqtt.md`.

## 5. Estado actual y limitaciones

**Hecho y probado con tests automáticos** (332 tests, todos en verde, en modo sin pantalla): cuentas con
verificación en dos pasos, grabación periódica, historial, actividades, ECG histórico con zoom,
observaciones, importación de paquetes, exportación a CSV, borrado de mediciones/periodos/actividades,
eliminación de cuenta, conservación y un flujo completo de extremo a extremo con datos de demostración.

**No verificado:**

- Nunca se ha ejecutado con la **banda pectoral real** ni con la **pasarela real**; solo con el mock de
  un compañero y con datos simulados.
- No se ha probado con un **broker MQTT real** de forma continuada.
- No se ha probado en **Windows**; los tests y el desarrollo se hicieron en Linux.
- La interfaz solo se ha probado sin pantalla (tests); no se ha revisado visualmente en una ventana real.
- No se ha probado con la **app móvil real**: la sincronización se ha probado solo con paquetes generados
  por el script de demostración.

**Limitaciones conocidas:**

- Registrar actividades, buscar y conectar la banda por Bluetooth y el registro en segundo plano
  corresponden al móvil; el escritorio no lo hace.
- La sincronización es por carpeta, no automática por red; y es síncrona: con paquetes muy grandes la
  ventana puede quedarse congelada unos segundos.
- El ECG histórico se guarda solo como envolvente de 1 segundo (mínimo y máximo), no la señal completa
  de 100 Hz.
- Las observaciones son reglas sencillas, sin validación clínica.
- Borrar una cuenta no elimina copias externas (CSV, archivos de intercambio, datos del móvil).
- El estado «Calibrando» depende de que la pasarela publique `READY`; con una pasarela antigua que no
  lo haga, la app se queda en «Calibrando».

La correspondencia con cada requisito (RF-01 a RF-50) está en `docs/cumplimiento_requisitos.md`.
