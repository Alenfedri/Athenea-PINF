# VitaBand – App móvil (C++ / Qt 6 QML)

App para móvil que **se conecta a la banda VitaBand por Bluetooth Low Energy**, muestra los datos en tiempo real,
dibuja el ECG, guarda un registro local (SQLite) y prepara un paquete JSON para la app de escritorio (que no forma parte de este proyecto).

## 1. Cómo compilar
1. Instala **Qt 6.5 o superior** con los módulos *Qt Quick, Qt Bluetooth, Qt SQL, Qt SVG* (y Android/iOS si vas a ir a móvil).
2. Abre `CMakeLists.txt` con **Qt Creator** → elige el kit → ▶ Ejecutar.
3. **Sin banda**: en *Conexión* pulsa **"Probar con simulador"**. Genera paquetes con el mismo formato que la banda real.
4. Android: añade los permisos que indica el final de `CMakeLists.txt`.

## 2. Mapa de carpetas (qué es cada cosa)
| Archivo | Para qué sirve (en cristiano) |
|---|---|
| `src/main.cpp` | Interruptor general: crea el Bluetooth y la base de datos y se los da a las pantallas. |
| `src/BleManager.*` | **El traductor**: habla con la banda y convierte bytes en "72 lpm". Incluye el simulador. |
| `src/DatabaseManager.*` | **El archivero**: usuarios, mediciones y actividades en un archivo SQLite. |
| `qml/Theme.qml` | Paleta (azul, cian, gris, negro, blanco) y medidas. Cambias un color aquí y cambia en toda la app. |
| `qml/Lang.qml` | Diccionario español/inglés. |
| `qml/Nav.qml` | El "conductor" que abre y cierra pantallas. |
| `qml/*Page.qml`, `Shell.qml` | Las pantallas. |
| `qml/V*.qml`, `Collapsible`, `LineChart`, `EcgChart`… | Piezas reutilizables (botón, tarjeta, desplegable, gráficas…). |
| `assets/` | Imágenes SVG: logo, banda, ondas, 25 iconos. |

## 3. Cómo funciona la app (de principio a fin)
1. **Arranque** → `main.cpp` abre la base de datos, crea `ble` y `db`, y carga `Main.qml`.
2. **Login / Registro** → `db.login()` / `db.registerUser()`. La contraseña nunca se guarda: solo una huella SHA-256 con "sal".
3. Tras entrar se abre **Shell** (barra superior con el estado de la banda + 5 pestañas). Si la banda no está conectada y no marcaste *"No mostrar al iniciar"*, se abre además **Conexión**.
4. **Conexión** → `ble.startScan()` busca dispositivos llamados *VitaBand* (o que anuncien el servicio `…cdef0`); al tocar uno, `ble.connectTo(i)` conecta, se suscribe a las notificaciones y, con el primer paquete, el estado pasa a *Conectado*.
5. **Datos en vivo** → cada paquete (10 bytes, 100 veces/s) se traduce y actualiza `ble.heartRate`, `ble.respRate`, etc. Las pantallas se actualizan solas (esto se llama *binding*).
6. **Guardado automático** → una vez por segundo `ble` emite `snapshot(...)`; `db.onSnapshot` guarda **1 registro periódico cada 10 s** (RF-12) y, si hay una actividad en marcha, **1 registro por segundo** (RF-30). Funciona sin Internet (RF-26).
7. **Sincronización** → `db.exportPending()` escribe un JSON con lo no enviado; al terminar `db.markSynced()` los marca. Cada medición tiene un `uuid` único para que el PC no cree duplicados (RF-20).
8. **Mantenimiento** → al iniciar sesión se borran las mediciones *periódicas* de más de 30 días; las actividades guardadas no se tocan (RF-40, 44, 46).

### Protocolo BLE usado (del TFG)
Servicio `12345678-1234-5678-1234-56789abcdef0` · Datos (NOTIFY) `…cdef1` · Control ECG (WRITE) `…cdef2`.
Paquete: `ECG(int16) · FC×100 · FR×100 · Temp×100 (uint16) · Actividad(1B) · Aviso(1B) [· media FC×100]`, todo *little-endian*.

## 4. Cómo se conectan las pantallas
```
LoginPage ──Registrarse──▶ RegisterPage
   │  ⚙ Ajustes ─────────────────────────────▶ SettingsPage
   └─ login correcto ─▶ Shell ──────────────────────────────────────────┐
                         ├ barra superior: chip de estado ─▶ ConnectionPage
                         ├ barra superior: ⚙ ───────────────▶ SettingsPage
                         └ pestañas (StackLayout):
                            0 MonitorPage   (tarjetas en tiempo real; tocar el aviso ─▶ ConnectionPage)
                            1 EcgPage       (ECG en directo + filtro)
                            2 HistoryPage   (gráfica + filtros desplegables + lista)
                            3 ActivityPage  (elegir deporte, cronómetro, resumen emergente, guardadas)
                            4 MorePage ──▶ ConnectionPage · SyncPage · StatsPage · SettingsPage · TemplatePage
                                       └─▶ Cerrar sesión ─▶ LoginPage
```
Reglas de navegación: `Nav.push("nombre")` abre encima · `Nav.pop()` vuelve · `Nav.goRoot("nombre")` reemplaza todo.
Los nombres válidos están en `Main.qml` (`Nav.pages`).

## 5. Base de datos local (SQLite) – cómo implementarla y por qué así
**Dónde**: un único archivo `vitaband.sqlite` en la carpeta privada de la app (`QStandardPaths::AppDataLocation`). Qt lo gestiona con el módulo `QtSql` (driver `QSQLITE`, incluido en Qt; no hay que instalar nada).

**Tablas** (los "cajones"):
```
users         id · username (UNIQUE) · name · surname · email · salt · pass_hash · created_at
activities    id · user_id · type · start_ts · end_ts · avg_hr · max_hr · min_hr · avg_rr · avg_temp · synced
measurements  id · uuid (UNIQUE) · user_id · ts · hr · rr · temp · activity ·
              kind ('periodic'|'activity') · activity_id · synced (0 pendiente / 1 enviado)
```
**Decisiones clave**
- `user_id` en todo → cada usuario solo ve lo suyo (RF-03). `ON DELETE CASCADE` → eliminar la cuenta elimina sus datos (RF-39).
- `ts` en milisegundos desde 1970 → fácil de filtrar y de resumir en gráficas.
- `kind` + `activity_id` → distinguir historial periódico y deportivo y poder conservar las actividades (RF-43/44).
- `synced` + `uuid` → saber qué falta por enviar y evitar duplicados al sincronizar (RF-20, 21, 28).
- Índice `(user_id, ts)` → las consultas por fechas siguen siendo rápidas con miles de filas.
- Los huecos (sin banda conectada) simplemente **no tienen filas**; `series()` inserta un corte en la gráfica en vez de inventar valores (RF-27).
- Volumen estimado: 1 fila cada 10 s ≈ 8 640 filas/día ≈ 260 000 en 30 días (unos pocos MB). Perfectamente asumible.

**Ampliaciones fáciles**: tabla `ecg_chunks(activity_id, ts, blob)` para guardar ECG (RF-33), cifrado con SQLCipher, y cambiar la exportación JSON por una API REST cuando exista la app de escritorio.

## 6. Cómo añadir una pantalla nueva
Copia `qml/TemplatePage.qml` (tiene los 4 pasos explicados en su cabecera y todos los controles: pestañas, tarjeta animada, desplegables, lista desplegable, interruptor, casilla, deslizador, campos, botones, gráfica y ventana emergente).

## 7. Qué NO está hecho / siguientes pasos
- La app de escritorio (indicado como fuera de alcance) y el **transporte real** de la sincronización (hoy genera el JSON y lo marca como enviado).
- Autenticación multifactor (RF-42), cambio de contraseña por enlace, ECG histórico y ampliado (RF-33…35), selector de fechas en calendario (hoy se usan periodos predefinidos).
- **No he podido compilar ni ejecutar** el proyecto en el entorno donde lo generé (no hay Qt); puede haber pequeños errores de sintaxis que Qt Creator te marcará.
