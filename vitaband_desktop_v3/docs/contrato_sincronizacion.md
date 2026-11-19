# Contrato de sincronización móvil → escritorio

> **Origen del contrato:** lo ha definido el lado del escritorio. El móvil todavía no
> lo implementa: quien desarrolle la app móvil debe exportar sus datos con este
> formato. Si el móvil necesita otro formato, hay que acordarlo y cambiar este
> documento y `domain/paquete_sync.py`.

## Cómo funciona

No hay servidor. El móvil deja un **archivo JSON** en la *carpeta de intercambio* y el
escritorio lo **importa** a la base de datos local del usuario.

- Carpeta: `intercambio.carpeta` de `settings.json` (por defecto `intercambio/`, relativa a donde se
  ejecuta la aplicación; se crea sola al iniciar sesión).
- Se leen los archivos `*.json` de esa carpeta (sin subcarpetas). El nombre es libre.
- **Escribe en un archivo temporal y renómbralo a `.json` al terminar** (por ejemplo `paquete.json.tmp` →
  `paquete.json`). Así el escritorio nunca lee un archivo a medias.
- Cuándo se importa: **al iniciar sesión** (RF-36), con el botón **«Sincronizar ahora»** (RF-21) y de forma
  automática cada `intercambio.intervalo_comprobacion_s` segundos (por defecto 60; `0` = desactivada).

## Formato (versión 1)

```json
{
  "version": 1,
  "usuario": "ana@correo.com",
  "generado": "2026-11-15T20:30:00",
  "actividades": [
    {"uid": "act-001", "inicio": 1794000000, "fin": 1794002400, "tipo": "carrera"}
  ],
  "mediciones": [
    {"uid": "m-0001", "ts": 1793990000, "bpm": 64.5, "rpm": 14, "temp": 36.4, "actividad": 0},
    {"uid": "m-0002", "ts": 1794000030, "bpm": 142, "rpm": 27, "temp": 36.9, "actividad": 2,
     "etiqueta": "ACTIVIDAD", "actividad_uid": "act-001"}
  ],
  "ecg": [
    {"ts_inicio": 1794000000, "paso_s": 1, "minimos": [1210, 1190], "maximos": [2040, 2100]}
  ]
}
```

Todas las marcas de tiempo (`ts`, `inicio`, `fin`, `ts_inicio`) son **segundos Unix (UTC)**.

### Campos

| Campo | Obligatorio | Descripción |
|---|---|---|
| `version` | sí | Debe ser `1`. |
| `usuario` | sí | Correo del propietario. Debe coincidir con el de la cuenta que ha iniciado sesión (se ignoran mayúsculas y espacios). |
| `generado` | no | Texto libre (normalmente fecha ISO). |
| `actividades[].uid` | sí | Identificador único de la actividad (1–64 caracteres). |
| `actividades[].inicio` / `fin` | sí | Inicio y fin; `fin ≥ inicio`. |
| `actividades[].tipo` | no | Texto de hasta 40 caracteres (RF-50, opcional). |
| `mediciones[].uid` | sí | Identificador único de la medición (1–64 caracteres). |
| `mediciones[].ts` | sí | Momento de la medición. |
| `mediciones[].bpm` | sí | Frecuencia cardíaca, 20–250. |
| `mediciones[].rpm` | no | Frecuencia respiratoria, 0–100. |
| `mediciones[].temp` | no | Temperatura cutánea en °C, 20–45. |
| `mediciones[].actividad` | no | Nivel: `0` reposo, `1` media, `2` intensa, `255` sin clasificar. |
| `mediciones[].etiqueta` | no | `PERIODICO`, `ACTIVIDAD` o `AMBOS` (RF-43). Por omisión: `ACTIVIDAD` si lleva `actividad_uid`, si no `PERIODICO`. |
| `mediciones[].actividad_uid` | según etiqueta | Obligatorio con `ACTIVIDAD`/`AMBOS`; prohibido con `PERIODICO`. |
| `ecg[]` | no | Envolvente del ECG: un mínimo y un máximo **por segundo** (`paso_s` solo admite `1`). `minimos` y `maximos` tienen la misma longitud (1–3600), son enteros de 16 bits y cada mínimo ≤ su máximo. |

**Etiquetas (RF-43):** una medición `PERIODICO` solo aparece en el historial periódico; `ACTIVIDAD`, solo en
su actividad; `AMBOS`, en los dos. Una `actividad_uid` puede referirse a una actividad del mismo paquete o a
una importada antes.

**ECG:** no se guarda la señal completa a 100 Hz, sino su envolvente por segundo. Sirve para ver la forma
general y los periodos sin señal, no para analizar cada latido.

## Validación: todo o nada

El paquete se valida entero antes de tocar la base de datos. **Un solo error rechaza todo el archivo** y no se
importa nada (así no se guardan datos a medias ni alterados). Se rechaza si:

- no es JSON válido en UTF-8, o la `version` no es la `1`, o falta `usuario`;
- un `uid` está repetido dentro del paquete, falta o tiene una longitud no válida;
- una marca de tiempo es anterior al año 2000 o posterior a «ahora + 1 día»;
- un valor está fuera de rango o no es numérico (texto, `true`, NaN);
- la combinación `etiqueta` / `actividad_uid` no es coherente, o una medición apunta a una actividad que no
  existe (ni en el paquete ni importada antes). En ese caso **no se importa nada del paquete**;
- se superan los límites: 200 000 mediciones, 5 000 actividades, 5 000 bloques de ECG, 64 MB por archivo.

En el archivo con error se muestran los primeros motivos en el estado de la sincronización.

## Duplicados (RF-20)

Hay dos barreras:

1. **Por archivo:** cada archivo se identifica por el **SHA-256 de su contenido**. Si ya se importó, no se
   vuelve a leer, aunque se renombre o se copie.
2. **Por dato:** cada medición y cada actividad tienen un `uid` único **por usuario**. Si llega un `uid` que ya
   existe, **se conserva el original** y el repetido se ignora (se cuenta como «duplicado»). El ECG de un segundo ya
   guardado tampoco se sobrescribe.

Por eso el móvil puede reexportar todo su historial cada vez: lo ya importado no se duplica. Conviene que los
`uid` sean **estables** (los mismos para el mismo dato en cada exportación).

## Estados (RF-21)

Cada archivo está en uno de tres estados, que se ven en la barra inferior de la aplicación:

| Estado | Significado |
|---|---|
| `PENDIENTE` | Hay un archivo cuyo contenido aún no se ha importado. |
| `SINCRONIZADO` | Su contenido se importó correctamente. |
| `ERROR` | Se rechazó (formato inválido, archivo ilegible, dependencia sin resolver…). Se **reintenta en cada sincronización**; si corriges el archivo (su contenido cambia) se importa normalmente. |

Un archivo puede depender de otro (p. ej. mediciones que apuntan a una actividad de otro paquete): en una
misma sincronización se repite la pasada mientras haya progreso, así que el orden de los nombres no importa.

## Varios usuarios en el mismo equipo

Los paquetes de otro `usuario` se **ignoran**: no se importan ni cuentan como pendientes o errores de la
sesión actual. Un archivo que no es JSON y no se puede atribuir a nadie sí aparece como error en todas las cuentas.

## Probarlo sin el móvil

```bash
python tools/generar_paquete_demo.py --usuario tu@correo.com
```

Genera en `intercambio/` un paquete con datos sintéticos (periódico, una interrupción, actividades y ECG).
Opciones: `--dias`, `--actividades`, `--intervalo`, `--semilla`, `--sin-huecos`, `--salida`, `--nombre`.
Con los mismos parámetros y semilla produce los mismos `uid`: volver a importarlo no duplica nada.
