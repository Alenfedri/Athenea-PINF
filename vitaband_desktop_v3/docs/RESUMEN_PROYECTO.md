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
  la app autenticadora: se puede escanear el código QR o escribir la clave a mano («Introducir clave de
  configuración»). Con las cuentas que ya tienen la verificación activada no se vuelve a mostrar.
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

- **Calidad de contacto:** insignia de color sobre la gráfica ECG, calculada en memoria con los últimos
  4 s de ECG (cada ~0,3 s): verde «Contacto óptimo»; ámbar «Señal con ruido (revisa ajuste/humedad de la
  banda)» si hay saturación, amplitud no fisiológica, saltos de línea base, ruido de alta frecuencia o
  picos aislados; rojo «Sin señal» si hay enlace pero la señal es plana o no llega; gris «Sin señal» si no
  hay enlace. Con ruido, el pulso y los avisos pueden no ser fiables (un artefacto no es una taquicardia).
  Los umbrales son estimaciones y no se han contrastado con una banda pectoral real; no se guarda nada.
- **Modo Entrenamiento:** el botón «Modo Entrenamiento» abre una pantalla completa negra (#0A0A0A) con
  el BPM en 120 pt, el RPM en 72 pt y un bloque con la zona cardíaca actual en color (Z1 gris azulado,
  Z2 verde, Z3 ámbar, Z4 naranja, Z5 rojo, p. ej. «Z3 · Aeróbico»), más el estado de la banda pectoral
  y la calidad de contacto. Se actualiza con cada estado nuevo mientras está abierto; «Salir del modo
  entrenamiento» o `Esc` vuelven a la vista normal, que no cambia. Sin valor válido, o calibrando,
  muestra `--` y «Sin zona». La zona usa la FC máx. de referencia de 190 BPM: la aplicación no tiene
  un perfil con FC máx. propia. No guarda nada. Visto solo en pruebas sin pantalla: la legibilidad a
  2–3 m no se ha comprobado en un monitor real.

**Qué se guarda de lo que se recibe en directo.** Mientras el estado es CONECTADO se guarda una
medición periódica cada 10 s (ajustable) con FC, FR, temperatura y nivel de actividad. Si la
pasarela envía la media de FC de ese intervalo, se guarda esa media; si no, el valor instantáneo. El
ECG filtrado se guarda además como una envolvente de un segundo (mínimo y máximo por segundo), no
la señal completa a 100 Hz. En modo ECG crudo no se guarda ECG.

**Informe PDF.** El botón «Exportar informe PDF», junto al de CSV, genera un PDF A4 del rango elegido en
«Historial periódico»: cabecera con perfil (la banda pectoral como fuente), estadísticas, gráficas de BPM
y RPM, un recorte de 2 min del ECG (envolvente de 1 s, sin intervalos R-R) y las observaciones con los
cruces de marcadores. Usa solo PySide6 (`QPdfWriter`/`QPainter`) y los bloques no se parten entre páginas.
Sin datos, ECG u observaciones, la sección lo indica. La cuenta no guarda edad, sexo ni FC máx.: salen como
«no registrado» y 190 BPM de referencia. Revisado en imagen con datos sintéticos, no con una banda real.

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
- **Marcadores de contexto:** un clic sobre la gráfica abre un menú con «Café», «Mal descanso»,
  «Mareo» y «Estrés» (o «Quitar marcador» si se hace clic junto a uno ya puesto). Se dibujan como
  líneas verticales con su etiqueta y se guardan en la tabla `marcadores_contexto`, que se borra con
  la cuenta, con «borrar todo» y con la purga del historial periódico. El servicio de observaciones
  compara los días con una etiqueta frente a los demás (FC en reposo, HRV/RMSSD y FR en reposo) y,
  con al menos 2 días marcados, 3 de referencia y una variación de 5 % o más, escribe una frase como
  «Los días marcados con 'Mal descanso' tu FC en reposo subió un 12 %…». Es una coincidencia, no
  una causa. No cruza anomalías registradas: solo esas tres métricas. Probado con datos sintéticos.
- **Observaciones del periodo:** texto automático (ver 3.4); incluye los cruces con marcadores.
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
- **Zonas cardíacas:** barra segmentada Z1–Z5 con el tiempo en cada zona (porcentaje y minutos). Se
  calcula con una FC máx. de referencia de 190 BPM (constante `FC_MAX_REFERENCIA` en
  `domain/zonas_actividad.py`): Z1 < 60 %, Z2 60–70 %, Z3 70–80 %, Z4 80–90 %, Z5 ≥ 90 %. Los huecos sin
  datos no cuentan como tiempo.
- **Pulso y respiración:** pestaña «Pulso y respiración» con BPM y RPM en la misma gráfica (dos
  ejes) y, si lo detecta, una línea vertical con el **umbral de fatiga** («Umbral fatiga: min 18 · 164
  BPM / 34 RPM»), repetido en texto sobre la gráfica. Se estima como el primer instante, ya en Z3 o más,
  en que el cociente RPM/BPM supera en un 25 % su línea base durante al menos 90 s. Si la actividad dura
  menos de 8 min, faltan datos de respiración o no hay un disparo claro, lo indica y no dibuja la línea.
  Es una estimación orientativa calculada al vuelo con las mediciones (no se guarda nada), probada solo con
  datos sintéticos; con la banda pectoral real habrá que ajustar los factores.
- **Comparador «Antes vs. Ahora»:** casilla «Comparar 2 sesiones» sobre la lista. Se marcan dos
  actividades y la más antigua pasa a ser *Antes* y la más reciente *Ahora*, sea cual sea el orden de
  marcado. El tiempo se normaliza a minutos desde el inicio de cada sesión, de modo que ambas
  arrancan en el minuto 0 aunque duren distinto. Superpone BPM y RPM (Ahora en línea continua, Antes
  discontinua) y resume FC media, FC máx., FR media y duración con la diferencia Ahora − Antes. Con 0,
  1 o más de 2 sesiones marcadas muestra un aviso. La diferencia solo es interpretable si el esfuerzo
  fue equivalente. Se calcula al vuelo, sin guardar nada. Con datos sintéticos, no con la banda real.
- Botón «Eliminar actividad» (ver 3.5), desactivado mientras se compara.

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
- **Recuperación (HRV):** línea añadida a la observación diaria. Se calcula en directo con el ECG a
  100 Hz mientras la banda está conectada, en modo filtrado y con nivel de actividad en reposo: cada
  minuto válido se detectan los picos R, se obtienen los intervalos R-R y se calcula el RMSSD en ms.
  Se descartan los minutos con ruido, con pocos latidos o con intervalos fuera de 300–2000 ms. De
  cada día se usa la mediana de los 5 primeros minutos válidos (mínimo 3) y se muestra como
  «Recuperación óptima» (≥ 50 ms), «Estado equilibrado» (20–50 ms) o «Estrés fisiológico / Fatiga»
  (< 20 ms), con la diferencia respecto a la media de los días anteriores si la hay. Los umbrales son
  generales y no están validados; la HRV cambia mucho con la edad y entre personas. Solo se guarda el
  valor de cada minuto (tabla `hrv_reposo`), no la señal; se borra con la purga, con el borrado de
  mediciones de ese periodo y al eliminar la cuenta. No se calcula con el ECG histórico ni con los
  datos importados del móvil (no contienen los latidos).
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

### 3.6 Métricas avanzadas, alertas, TCX y copia de seguridad

Siete mejoras añadidas sobre los datos de la banda pectoral ECG. Todas son estimaciones orientativas,
probadas con datos sintéticos y sin una banda real; los umbrales no están validados clínicamente.

- **Carga de entrenamiento (TRIMP):** cada sesión suma 1·min en Z1 + 2·Z2 + 3·Z3 + 4·Z4 + 5·Z5 (FC máx. de
  referencia 190). Se compara el TRIMP de los últimos 7 días con la media semanal de los últimos 28:
  «Carga baja» (< 0,8), «Carga óptima» (0,8–1,3) o «Riesgo de sobreentrenamiento» (> 1,3). Con menos de
  14 días de historial se usan umbrales fijos de TRIMP semanal (75 y 300, elegidos por estimación). Sale
  en Actividades y bajo las tarjetas de Historial periódico.
- **HRR-60:** pulso pico menos pulso 60 s después, en la ficha de cada sesión; «N/D» si la sesión termina antes.
- **Alertas en Tiempo real y Modo Entrenamiento:** Zona 5 (≥ 90 % de la FC máx.), temperatura ≥ 38,0 °C y
  pérdida de contacto, solo con la banda CONECTADA. Banner rojo (y borde en el Modo Entrenamiento) mientras
  dure la condición, y `QApplication.beep()` como mucho una vez cada 20 s por tipo. Botón «Silenciar/Activar
  sonido»: silencia el pitido, no el banner.
- **Exportar .TCX:** botón en Actividades; TrainingCenterDatabase v2 con FC y las RPM en `Cadence`. Sin GPS
  ni distancia. Las RPM no son cadencia de pedaleo: Strava o Garmin pueden interpretarla como tal.
- **Deriva cardíaca:** en sesiones de ≥ 20 min, si la FC media sube ≥ 5 % entre mitades con RPM estables
  (< 10 %) y la temperatura sube ≥ 0,4 °C o llega a 37,8 °C, se avisa en la ficha y en la observación de la
  actividad. Sin datos de respiración o temperatura no se afirma nada.
- **Dashboard semanal:** cuatro tarjetas en Historial periódico (últimos 7 días vs. 7 anteriores): minutos
  activos (duración de las sesiones), TRIMP, HRV media y FC en reposo media, con variación y color.
- **Copia de seguridad (.zip):** botones «Exportar Backup (.zip)» y «Restaurar Backup (.zip)» en la barra
  superior. Vuelca la base en caliente con `sqlite3.backup` y añade `manifest.json`. Al restaurar se valida
  el zip y `PRAGMA integrity_check`, se guarda un `.bak` de la base actual y se vuelca la copia sobre la
  conexión abierta. Se rechaza una copia que no contenga la cuenta con la sesión abierta. La copia incluye
  TODA la base, también cuentas (hash de contraseña y clave TOTP): hay que guardarla en lugar seguro.

### 3.7 Sesión en directo, constancia y valoración

Todo con la banda pectoral ECG de VitaBand. Son estimaciones, no están validadas con una banda real.

- **Vueltas (Lap):** botón en «Tiempo real» y tecla `Espacio` en Modo Entrenamiento. Pertenecen a la
  sesión en directo (periodo CONECTADA); en «Actividades» salen en el desglose si su hora cae dentro
  de la actividad (Duración, BPM medio, RPM medio).
- **Test ortostático (3 min):** 2 min en reposo + 1 min de pie, con pitido al cambiar de fase.
  Guarda FC/RMSSD basal, pico, de pie y ΔFC.
- **Auto-pausa:** más de 5 s «Sin señal» congela el tiempo efectivo y excluye esas muestras de medias y kcal.
- **Calorías (Keytel):** necesitan edad y sexo, que la cuenta no tenía: nuevo botón «Perfil fisiológico».
  Sin ellos se muestra N/D.
- **Mapa de calor** de 12 semanas, objetivo semanal editable (150 min por defecto), barra y rachas.
- **RPE 1-10 + nota** por actividad; se cruza con el % de FCmax en las observaciones.
- **Botón PNG** junto al ECG, el comparador y la gráfica del Historial (doble resolución).
- Tablas nuevas (`CREATE TABLE IF NOT EXISTS`): `vueltas_sesion`, `tests_ortostaticos`, `notas_sesion`, `perfil_fisiologico`.

### 3.8 Coherencia, Poincaré, VO2máx, disciplinas, ratio y anonimización

Con la banda pectoral ECG de VitaBand (estimaciones orientativas, sin validar con una banda real): **Coherencia Cardíaca**
(2/3/5 min a 6 RPM, índice % de BPM sincronizado), **Poincaré** con SD1/SD2 y latidos atípicos (usa los R-R guardados desde ahora,
tabla `rr_ventanas`), **VO2máx de Uth** con edad cardiovascular mensual, **disciplinas y PRs** (tabla `disciplinas_sesion`; PR = menor BPM
medio en la misma franja de duración o más tiempo en Z2; un empate no cuenta), **ratio BPM/RPM** (alerta < 3:1 sostenido 60 s),
**Modo Escritorio** (ventana 20 min) y casilla **Anonimizar datos personales** (`SUJETO-` + 6 hex SHA-256 del correo en PDF y columna `sujeto` del CSV).

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
zoom del ECG, observaciones, importación de paquetes, CSV y borrados. Hay 750 tests automáticos que
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
- La HRV solo existe de lo que la aplicación ha recibido en directo en reposo; si no se usa
  «Conectar», o la banda no está en reposo, no hay datos y la línea de recuperación no aparece. Nunca se ha
  contrastado con una banda real (el detector se ha probado con ECG sintético).
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
