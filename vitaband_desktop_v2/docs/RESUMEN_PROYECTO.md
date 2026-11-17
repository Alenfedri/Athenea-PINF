# VitaBand Desktop: qué es y qué hace

Este documento describe la aplicación de escritorio tal y como está programada hoy. Lo que aún no
está hecho o no se ha podido probar con el equipo real se dice de forma explícita en el apartado 5.

## 1. Qué es VitaBand y qué papel tiene esta aplicación

**VitaBand** es un dispositivo de medición biométrica que se lleva en el pecho, sujeto con una
correa (banda pectoral). Mide electrocardiograma (ECG), frecuencia cardíaca (FC), frecuencia
respiratoria (FR), temperatura cutánea y nivel de actividad física, y puede emitir un aviso
experimental (por ejemplo, "FC elevada en reposo").

El sistema completo tiene tres piezas:

- **La banda pectoral**, que envía sus datos por Bluetooth Low Energy (BLE).
- **La app móvil** (Qt/QML), que se conecta a la banda por BLE. Es la que, según la especificación,
  registra actividades deportivas y guarda datos sin conexión. La desarrolla otro compañero.
- **Esta aplicación de escritorio** (Python + PySide6), que hace dos cosas distintas:
  1. **Monitorización en directo** de la banda a través de un broker MQTT y una pasarela que
     traduce de BLE a MQTT. Hoy la pasarela es un simulador (mock) hecho por otro compañero.
  2. **Historial**: guarda en una base de datos local lo que recibe en directo y lo que importa del
     móvil, y permite consultarlo, exportarlo y borrarlo.

Flujo de los datos en directo:

```
banda pectoral --BLE--> pasarela/mock --MQTT--> broker --MQTT--> VitaBand Desktop
```

Flujo de los datos del móvil (no pasan por MQTT):

```
app móvil --archivo JSON en una carpeta--> VitaBand Desktop (la importa)
```

Todo se guarda en local, en SQLite (`vitaband_historial.db`, en la carpeta desde la que se ejecuta el programa). No hay servidor
propio ni nube.

## 2. Acceso y seguridad de cuentas

Sin sesión iniciada no se abre nada de lo anterior. Las cuentas son locales de este equipo.

- **Registro.** Pide nombre, correo, contraseña y repetirla. La contraseña debe tener al menos 10
  caracteres, una letra y un número. No se pueden crear dos cuentas con el mismo correo. La
  contraseña se guarda con un hash (scrypt), no en claro.
- **Inicio de sesión en dos pasos.** Primero correo y contraseña; después, un código de 6 dígitos
  de una app autenticadora (Google Authenticator, Microsoft Authenticator, Authy…). La primera vez
  que se entra con una cuenta nueva, la pantalla muestra la clave de configuración para añadirla a
  la app autenticadora (se escribe a mano con «Introducir clave de configuración»; la pantalla no
  muestra un código QR).
- **Bloqueo por intentos.** Con 5 fallos seguidos la cuenta se bloquea 5 minutos. El paso del
  código tiene un tiempo máximo de 5 minutos.
- **Aislamiento.** Cada medición pertenece al usuario que tenía la sesión abierta; un usuario no ve
  los datos de otro aunque compartan equipo.
- **Cerrar sesión.** Botón «Cerrar sesión» arriba a la derecha: corta la conexión MQTT, guarda lo
  pendiente, cierra la base de datos y vuelve a la pantalla de acceso.
- **Eliminar cuenta.** Botón «Eliminar cuenta» (ver apartado 3.5).

## 3. Recorrido por la interfaz

Al entrar se abre una ventana con una barra superior y tres pestañas. Abajo hay una barra de estado
con el estado de la sincronización.

**Barra superior** (de izquierda a derecha): estado de la conexión, «Conectar», «Desconectar»,
«Sincronizar ahora», «Exportar historial (CSV)», nombre del usuario, «Eliminar cuenta» y «Cerrar
sesión».

La aplicación **no se conecta sola** a la banda: hay que pulsar «Conectar».

### 3.1 Pestaña «Tiempo real»

- Cuatro valores: FC, FR, temperatura y nivel de actividad (Baja/Reposo, Media o Intensa).
- Una línea con el aviso experimental de la banda ("Sin avisos" si no hay).
- Gráfica del ECG a 100 Hz. Muestra una ventana de los últimos segundos (6 por defecto, ajustable en
  `settings.json`).
- Casilla «Mostrar señal ECG cruda (sin filtro Butterworth)». Cambia entre la señal filtrada y la
  cruda enviando una orden a la pasarela. Solo se puede usar con la conexión establecida.
- Estados de conexión que se muestran: DESCONECTADO, CONECTANDO, CALIBRANDO (los primeros 6 s de
  respiración, con los valores en espera), CONECTADO y ERROR_COMUNICACION.
- Si no llegan datos durante 2,5 s, la aplicación pasa a ERROR_COMUNICACION y vacía los valores en
  pantalla. Pasa lo mismo si la pasarela avisa de que ha perdido la banda.

**Qué se guarda de lo que se recibe en directo.** Mientras el estado es CONECTADO se guarda una
medición periódica cada 10 s (ajustable) con FC, FR, temperatura y nivel de actividad. Si la
pasarela envía la media de FC de ese intervalo, se guarda esa media; si no, el valor instantáneo. El
ECG filtrado se guarda además como una envolvente de un segundo (mínimo y máximo por segundo), no
la señal completa a 100 Hz. En modo ECG crudo no se guarda ECG.

### 3.2 Pestaña «Historial periódico»

Muestra las mediciones periódicas: las guardadas por el escritorio en directo y las importadas del
móvil con etiqueta de periódico.

- **Selector de rango:** fechas "Desde" y "hasta" con calendario, atajos «Hoy», «7 días», «30 días» y
  «Todo» (todo lo que hay guardado).
- **Variable:** FC, FR, temperatura o nivel de actividad.
- **Resolución:** Automática, Sin agrupar, Por minuto, Por hora o Por día. Con periodos largos la
  automática agrupa para que la gráfica se pueda leer.
- **Resumen:** número de registros, media, mínimo y máximo del periodo.
- **Gráfica y tabla.** Si hay tramos sin datos, se ven como huecos (no se rellenan ni se
  interpolan) y se listan las interrupciones. En la tabla agrupada, esos tramos aparecen como
  «Sin datos».
- **Observaciones del periodo:** texto automático (ver 3.4).
- **ECG histórico:** gráfica compacta de la envolvente. Solo se dibuja si el rango elegido es de
  7 días o menos; con más, avisa de que hay que acortarlo.
- **Zoom del ECG:** en la vista general se arrastra un intervalo; debajo se ve ese tramo ampliado.
  Botones «Acercar», «Alejar», «◀», «▶» y «Restablecer». El límite de la ampliación es la resolución
  guardada: 1 segundo por intervalo.

### 3.3 Pestaña «Actividades»

Lista de actividades deportivas importadas del móvil. El escritorio no crea actividades: solo las
recibe por sincronización.

- Selector de rango y lista con: inicio, tipo (si el móvil lo envía), duración, número de
  mediciones, FC media y FC máxima.
- Al elegir una actividad: título con duración, estadísticas, gráfica de la variable elegida
  (con interrupciones marcadas), ECG de la actividad con el mismo zoom y la observación de la
  actividad.
- Botón «Eliminar actividad» (ver 3.5).

### 3.4 Observaciones automáticas

Son textos orientativos generados con reglas sencillas, no un diagnóstico. Cada panel lleva el
aviso: *"Observación orientativa de carácter informativo; no constituye un diagnóstico médico."*

- **Diaria** (historial periódico): cuántos registros hay y en cuántas horas del día, las
  interrupciones, FC y FR en reposo y temperatura frente a unos umbrales fijos, FC en actividad,
  cambio respecto al día anterior y, si hay datos de varios días, patrones como "la FC en reposo
  suele ser más alta por la tarde".
- **Por actividad:** duración, FC (media, mínima, máxima), FR, cambio de temperatura, porcentaje del
  tiempo en cada nivel de actividad, esfuerzo estimado (ligero, moderado o alto, respecto a la FC en
  reposo de referencia) e interrupciones.
- Se generan al iniciar sesión, tras cada sincronización y cada 60 minutos (ajustable).
- Los umbrales (por ejemplo, FC en reposo por encima de 100 o por debajo de 45) están en el código
  y **no están validados clínicamente**.

### 3.5 Exportar y borrar

**Exportar a CSV** («Exportar historial (CSV)»). Pide dónde guardar el archivo y exporta todas las
mediciones del usuario. Columnas: `fecha;hora;bpm;rpm;temp_c;nivel_actividad;etiqueta`. Separador
`;`, coma decimal y UTF-8 con BOM, pensado para abrirlo en Excel en español. El ECG no se exporta.

**Borrado de mediciones.** Todas las acciones piden confirmación y avisan de que no se puede
deshacer.

- «Eliminar seleccionadas» (Historial periódico, solo en vista sin agrupar): borra las filas
  elegidas.
- «Eliminar periodo…»: borra todo el historial periódico del rango elegido y dice cuántos
  registros son.
- «Eliminar actividad»: borra la actividad, sus mediciones exclusivas, su ECG y su observación.
- Una medición puede pertenecer a la vez al historial periódico y a una actividad. Si la borras
  desde el historial periódico, se conserva en la actividad; y al revés.

**Conservación automática.** Al iniciar sesión se borra lo que supera el plazo: 30 días para el
historial periódico y 365 para las actividades (ajustables en `settings.json`).

**Eliminar cuenta.** Doble confirmación: un aviso con el alcance y un cuadro donde hay que escribir
`ELIMINAR` y la contraseña. Borra la cuenta y todos sus datos (mediciones, actividades, ECG,
observaciones y estado de sincronización) en una sola operación, y vuelve a la pantalla de acceso. Una
contraseña incorrecta cuenta como intento fallido. No se borran las copias que estén fuera de la
aplicación: CSV exportados, archivos de la carpeta de intercambio o datos del móvil.

## 4. Cómo se comunica con la app móvil

No hay servidor ni conexión directa. El móvil deja un archivo `.json` en una **carpeta de
intercambio** (`intercambio/`, relativa a la carpeta desde la que se ejecuta el programa; configurable) y el escritorio lo importa.

- **Cuándo importa:** al iniciar sesión, al pulsar «Sincronizar ahora» y, mientras la aplicación
  está abierta, cada 60 s (ajustable; 0 la desactiva).
- **Qué lleva el archivo:** el correo del usuario, actividades, mediciones (con FC, FR, temperatura,
  nivel de actividad y etiqueta periódica/actividad/ambas) y, opcionalmente, el ECG como mínimo y
  máximo por segundo. El formato exacto está en `docs/contrato_sincronizacion.md`.
- **Todo o nada:** si el archivo tiene un solo error, no se importa nada de él.
- **Sin duplicados:** cada medición y actividad tiene un identificador propio. Si llega uno que ya
  existe, se conserva el original. El móvil puede volver a exportar todo su historial sin duplicar
  datos, siempre que mantenga los mismos identificadores.
- **Varios usuarios:** los archivos de otro correo se ignoran.
- **Estado:** la barra inferior indica cuántos archivos están sincronizados, pendientes o con error.
  Los que dan error se reintentan en cada sincronización.
- **Para probar sin el móvil:** `python tools/generar_paquete_demo.py --usuario tu@correo.com`
  genera un archivo con datos sintéticos.

**Aviso importante:** este formato lo ha definido el lado del escritorio. **La app móvil todavía no
lo genera.** Quien la desarrolle tiene que adaptarla a este contrato, o acordar otro y cambiar
`docs/contrato_sincronizacion.md` y `domain/paquete_sync.py`.

## 5. Estado actual y limitaciones

**Terminado y probado por software.** Cuentas y verificación en dos pasos, historial, actividades,
zoom del ECG, observaciones, importación de paquetes, CSV y borrados. Hay 332 tests automáticos que
pasan (lógica, interfaz sin pantalla y un recorrido completo: paquete de demo, sincronización,
consultas, observaciones, CSV, borrado de una medición y borrado de la cuenta).

**No probado.**

- Nunca se ha usado con la **banda pectoral real**, ni con la pasarela real. Solo hay pruebas con
  datos simulados.
- No se ha probado con un **broker MQTT real** de principio a fin. Los tests sustituyen la conexión
  MQTT por un simulador.
- No se ha ejecutado en **Windows**. El desarrollo y las pruebas se hicieron en Linux, y la
  interfaz solo se probó sin pantalla (modo offscreen); nadie la ha visto en una ventana real.
- No se ha probado con la **app móvil real**, porque aún no genera el formato de intercambio.

**Depende de otras partes.**

- Conectar con la banda por BLE, buscar dispositivos, registrar actividades, medir sin conexión y
  elegir el tipo de deporte son tareas de la app móvil, no de esta.
- La clave `media_bpm` de la telemetría es una suposición del escritorio (no figuraba en el código de la
  pasarela). Si usa otro nombre, se cambia en `CLAVE_MEDIA_BPM` (`domain/interprete_biometrico.py`).
- Los mensajes MQTT esperados están en `docs/contrato_mqtt.md`.

**Limitaciones conocidas.**

- La sincronización se hace en el hilo de la interfaz: con paquetes muy grandes la ventana se queda
  parada unos segundos.
- El ECG histórico es solo una envolvente de 1 s. Sirve para ver la forma general y los tramos sin
  señal, no para analizar latido a latido.
- Las observaciones usan umbrales fijos sin validación clínica.
- El escritorio no puede iniciar ni terminar actividades; solo las recibe del móvil.
- La contraseña y el estado de las cuentas viven en la base de datos local. No hay recuperación
  de contraseña ni de acceso si se pierde la app autenticadora.
- Para qué requisito se cumple cada cosa, ver `docs/cumplimiento_requisitos.md`.

## Cómo ejecutarlo

```
pip install -r requirements.txt
python main.py        # desde la carpeta del proyecto, con settings.json al lado
python -m pytest      # tests
```

Ajustes en `settings.json`: dirección del broker MQTT, `device_id`, intervalo de registro, días
de conservación, carpeta e intervalo de intercambio e intervalo de observaciones.
