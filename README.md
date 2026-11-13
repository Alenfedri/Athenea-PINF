# 🫀 VitaBand — Arquitectura MQTT y Aplicación Móvil (v2)

![Universidad de Cádiz](https://img.shields.io/badge/UCA-Escuela_Superior_de_Ingenier%C3%ADa-005A8B?style=flat-square)
![Hardware](https://img.shields.io/badge/Hardware-XIAO_ESP32--C6_(PCB_v2)-2EA44F?style=flat-square)
![Protocolo](https://img.shields.io/badge/Transporte-BLE_5_%E2%86%94_MQTT-FF6F00?style=flat-square)
![Frecuencia ECG](https://img.shields.io/badge/Muestreo_ECG-100_Hz-blueviolet?style=flat-square)
![Estado](https://img.shields.io/badge/Estado-Prototipo_Acad%C3%A9mico-lightgrey?style=flat-square)

> [!CAUTION]
> **Rigor Académico — Línea Roja Innegociable:** **VitaBand** es un **prototipo académico**, no un dispositivo médico certificado. En la aplicación móvil y en la documentación **nunca** deben emplearse términos clínicos como *"diagnóstico médico"*, *"taquicardia"*, *"depresión vital"* o *"colapso"*. Utiliza exclusivamente denominaciones técnicas neutras como *"aviso experimental"*, *"FC elevada en reposo"* o *"niveles bajos en reposo"*.

---

## 📋 Tabla de Contenidos

- [1. Contexto y Objetivo del Proyecto](#1-contexto-y-objetivo-del-proyecto)
- [2. Especificaciones Técnicas del Prototipo (PCB v2)](#2-especaciones-técnicas-del-prototipo-pcb-v2)
  - [2.1. Hardware, Pinout y Alimentación](#21-hardware-pinout-y-alimentación)
  - [2.2. Sensores y Procesamiento Embarcado (Firmware)](#22-sensores-y-procesamiento-embarcado-firmware)
  - [2.3. Máquinas de Estados, Histéresis y Matrices de Interpretación](#23-máquinas-de-estados-histéresis-y-matrices-de-interpretación)
  - [2.4. Protocolo BLE Original (Referencia para Pasarela BLE↔MQTT y Mock)](#24-protocolo-ble-original-referencia-para-pasarela-blemqtt-y-mock)
  - [2.5. Casos Borde y Limitaciones Experimentales Conocidas](#25-casos-borde-y-limitaciones-experimentales-conocidas)
- [3. Requisitos Funcionales y de Calidad (App Móvil)](#3-requisitos-funcionales-y-de-calidad-app-móvil)
- [4. Gobernanza, Rol del Product Owner y Reglas de Tutoría](#4-gobernanza-rol-del-product-owner-y-reglas-de-tutoría)

---

## 1. Contexto y Objetivo del Proyecto

* **Antecedentes:** Existe un prototipo físico funcional de **VitaBand** (cinturón biométrico torácico colocado sobre el esternón), desarrollado en el Trabajo de Fin de Grado de Ingeniería Electrónica Industrial de **Luis Fernando Barba Céspedes** (septiembre de 2026, tutorizado por **Arturo Morgado Estévez** y cotutorizado por **Blas Salvador Domínguez**, ESI - Universidad de Cádiz).
* **Motivación del reemplazo:** La primera versión de la aplicación móvil, implementada en **MIT App Inventor**, constituyó únicamente una prueba de concepto con importantes limitaciones técnicas:
  * No soporta ejecución en segundo plano ni reconexión robusta.
  * Persiste datos únicamente en `TinyDB` local por fecha, sin exportación ni analítica avanzada.
  * Renderiza la onda ECG borrando y reiniciando un lienzo estático (`Canvas` de `400 px`).
  * Emplea etiquetas clínicas inadecuadas en la interfaz de usuario.
* **Objetivo como Cliente / Product Owner:** Migrar y escalar la visualización, gestión e historial de los datos biométricos hacia una **aplicación móvil moderna, fluida, escalable y bien estructurada** (multiplataforma o nativa), sustituyendo tanto la app de MIT App Inventor como las herramientas de prueba en PC (`PyQtGraph` / `Matplotlib`).
* **Arquitectura de desarrollo desacoplada:** El equipo de **4 estudiantes de 3º de Ingeniería Informática** trabaja en paralelo sobre una arquitectura desacoplada en tres bloques:

```text
┌───────────────────────────┐       ┌──────────────────┐       ┌─────────────────────────┐
│ Hardware Real (ESP32-C6)  │       │                  │       │                         │
│            ó              │ ────► │   Broker MQTT    │ ◄───► │    Aplicación Móvil     │
│  Script Mock en Python    │       │  (Topics JSON)   │       │ (UI + Lógica + Histor.) │
└───────────────────────────┘       └──────────────────┘       └─────────────────────────┘
```

---

## 2. Especificaciones Técnicas del Prototipo (PCB v2)

Todas las decisiones de emulación, pasarela e interfaz deben ajustarse con fidelidad al comportamiento del prototipo final (2ª integración / PCB v2).

### 2.1. Hardware, Pinout y Alimentación

* **Microcontrolador:** **Seeed Studio XIAO ESP32-C6** (arquitectura RISC-V de 32 bits hasta `160 MHz`, BLE 5, ADC de 12 bits `[0–4095]`, lógica de `3,3 V`).
* **Alimentación y autonomía:**
  * Batería LiPo de **1200 mAh** (`3,7 V`).
  * Carga por USB-C mediante **MCP73831** a **500 mA** con circuito *Load Sharing* (permite el uso simultáneo del dispositivo durante la carga).
  * Convertidor buck-boost **TPS63802** regulado a **3,3 V**.
  * Consumo medido en operación: **61 mA** (autonomía teórica estimada de **~19,7 horas**).

#### Asignación de Pines (`XIAO ESP32-C6`)

| Pin | Función | Subsistema / Descripción |
| :--- | :--- | :--- |
| `D0 / A0` | Entrada analógica | Señal ECG acondicionada (salida del AD8232) |
| `D1 / A1` | Entrada analógica | Señal de respiración (potenciómetro deslizante) |
| `D4 (SDA)` | Bus I2C (Datos) | Bus compartido: MAX30205 (`0x48`) y BNO055 (`0x28`) |
| `D5 (SCL)` | Bus I2C (Reloj) | Bus compartido: MAX30205 (`0x48`) y BNO055 (`0x28`) |
| `D7 (LO-)` | Entrada digital | Detección de desconexión de electrodo negativo del AD8232 *(cableado en PCB, aún sin empaquetar en trama BLE v1)* |
| `D8 (LO+)` | Entrada digital | Detección de desconexión de electrodo positivo del AD8232 *(cableado en PCB, aún sin empaquetar en trama BLE v1)* |

---

### 2.2. Sensores y Procesamiento Embarcado (Firmware)

1. **Electrocardiograma — ECG (`A0` · Chip `AD8232`):**
   * **Etapa analógica:** Filtro paso alto de 2 polos (`0,5 Hz`), filtro paso bajo de 2 polos (`40 Hz`) y ganancia total de `1100`. Conectado a **3 electrodos tipo *snap*** dispuestos en triángulo compacto sobre el esternón (admite también lectura puntual apoyando los dedos).
   * **Muestreo y filtrado digital:** Adquisición a **100 Hz** (`10 ms`). Aplica un filtro digital **Butterworth pasabanda de orden 2 (`4–30 Hz` a $f_s = 100\text{ Hz}$)** implementado mediante dos secciones *biquad* en cascada.
   * **Cálculo de BPM:** Detector por flanco de bajada con histéresis sobre la señal filtrada (`TH_HIGH = -100.0`, `TH_LOW = -200.0`). Solo acepta intervalos entre latidos comprendidos entre **300 ms y 1200 ms** (rango válido: **50–200 BPM**).
   * **Offset de visualización:** Al transmitir la señal filtrada, el firmware suma `OFFSET_ECG = 1600` unidades ADC para centrarla en valores positivos.

2. **Respiración (`A1` · Potenciómetro deslizante de `100 kΩ`):**
   * **Acondicionamiento mecánico y eléctrico:** Mecanismo con polea, hilo, resorte de retorno y cinta elástica auxiliar que convierte la expansión torácica en desplazamiento lineal del cursor, acoplado mediante un seguidor de tensión **LPV521**. Sin filtrado digital (para evitar retardo transitorio).
   * **Calibración automática inicial (`6 segundos`):** Al establecerse la conexión, muestrea `A1` durante **6000 ms** exigiendo una amplitud mínima `max - min >= 100` unidades ADC. Si no la alcanza, reinicia automáticamente el ciclo de `6 s` y **bloquea la transmisión de paquetes** hasta completar una calibración válida.
   * **Cálculo de RPM:** Define umbrales dinámicos al **35 %** (`TH_LOW = min + 0.35 * amp`) y **70 %** (`TH_HIGH = min + 0.70 * amp`). Detector por flanco de subida con ventana temporal válida entre **1000 ms y 10000 ms** (**6–60 RPM**).

3. **Temperatura cutánea (`I2C 0x48` · `MAX30205`):**
   * Sensor digital de contacto con resolución de **16 bits** ($0,00390625\text{ }^\circ\text{C/LSB}$) y precisión de **$\pm 0,1\text{ }^\circ\text{C}$** (entre `37 °C` y `39 °C`), acoplado térmicamente a la piel mediante una superficie de cobre y vías térmicas en la cara inferior de la PCB.

4. **Movimiento / IMU (`I2C 0x28` · `BNO055`):**
   * Sensor inercial de 9 ejes en modo de fusión `NDOF` con cristal externo de `32,768 kHz`.
   * Calcula el módulo de la aceleración lineal sin gravedad $a_{mov} = \sqrt{a_x^2 + a_y^2 + a_z^2}$ y lo suaviza mediante una media móvil de **25 muestras** ($I_{mov}$).

---

### 2.3. Máquinas de Estados, Histéresis y Matrices de Interpretación

#### Clasificación Individual con Histéresis

Cada magnitud se clasifica en tres niveles discretos: `0` (Bajo), `1` (Medio / Normal) y `2` (Alto).

| Variable | Estado Inicial | Transición `0 → 1` | Transición `1 → 0` | Transición `1 → 2` | Transición `2 → 1` |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Movimiento ($I_{mov}$)** | `0` | $\ge 0,9\text{ m/s}^2$ | $< 0,5\text{ m/s}^2$ | $\ge 3,0\text{ m/s}^2$ | $< 2,5\text{ m/s}^2$ |
| **Frecuencia Cardíaca (FC)** | `1` | $\ge 62\text{ BPM}$ | $< 58\text{ BPM}$ | $\ge 102\text{ BPM}$ | $< 98\text{ BPM}$ |
| **Frecuencia Respiratoria (FR)** | `1` | $\ge 13\text{ RPM}$ | $< 11\text{ RPM}$ | $\ge 19\text{ RPM}$ | $< 17\text{ RPM}$ |

#### Matrices de Interpretación Conjunta (`Byte 8` y `Byte 9`)

| Combinación `(Mov, FC, FR)` | Actividad Física (`Byte 8`) | Aviso Experimental (`Byte 9`) | Significado Técnico en la App |
| :---: | :---: | :---: | :--- |
| `(0, 1, 1)` | `0` | `255` | Actividad baja / Reposo (Sin aviso) |
| `(1, 1, 1)` | `1` | `255` | Actividad media (Sin aviso) |
| `(2, 2, 2)` | `2` | `255` | Actividad intensa (Sin aviso) |
| `(0, 0, 0)` | `255` | `0` | Sin actividad definida · **Aviso por niveles bajos** |
| `(0, 2, 0)` o `(0, 2, 1)` | `255` | `1` | Sin actividad definida · **Aviso por FC elevada en reposo** |
| `(0, 2, 2)` | `255` | `2` | Sin actividad definida · **Aviso conjunto elevado en reposo** |
| *Cualquier otra combinación* | `255` | `255` | En transición / Sin clasificar · Normal / Sin aviso |

---

### 2.4. Protocolo BLE Original (Referencia para Pasarela BLE↔MQTT y Mock)

* **Nombre del dispositivo:** `"VitaBand"`

#### Perfil GATT

| Elemento GATT | UUID | Propiedades | Descripción / Payload |
| :--- | :--- | :---: | :--- |
| **Servicio Principal** | `12345678-1234-5678-1234-56789abcdef0` | — | Servicio biométrico VitaBand |
| **Característica Datos** | `12345678-1234-5678-1234-56789abcdef1` | `NOTIFY` | Flujo ESP32 → Cliente (`10` o `12 bytes` cada `~10 ms`) |
| **Característica Control** | `12345678-1234-5678-1234-56789abcdef2` | `WRITE` | Comando Cliente → ESP32 (`"0"`: ECG filtrada, `"1"`: ECG cruda) |

#### Estructura de la Trama Binaria (Little-Endian)

| Bytes | Tipo | Campo | Escala / Codificación | Frecuencia |
| :---: | :---: | :--- | :--- | :---: |
| `0–1` | `int16_t` | Muestra ECG | `A0_filtrada + 1600` (filtrada) o `[0–4095]` (cruda) | Cada `~10 ms` (10 B) |
| `2–3` | `uint16_t` | Frecuencia Cardíaca | `BPM × 100` | Cada `~10 ms` (10 B) |
| `4–5` | `uint16_t` | Frecuencia Respiratoria | `RPM × 100` | Cada `~10 ms` (10 B) |
| `6–7` | `int16_t` | Temperatura Cutánea | `Temperatura (°C) × 100` | Cada `~10 ms` (10 B) |
| `8` | `uint8_t` | Actividad Interpretada | `0` (Baja), `1` (Media), `2` (Intensa), `255` (Sin definir) | Cada `~10 ms` (10 B) |
| `9` | `uint8_t` | Aviso Experimental | `0`, `1`, `2` o `255` (Normal / Sin aviso) | Cada `~10 ms` (10 B) |
| `10–11` | `uint16_t` | **Media BPM (10 s)** | **Enteros de BPM sin multiplicar por 100** | **Cada `10 s` (paquete de 12 B)** |

---

### 2.5. Casos Borde y Limitaciones Experimentales Conocidas

> [!WARNING]
> Tanto el **Script Mock en Python** como la **Aplicación Móvil** deben modelar y gestionar explícitamente estos comportamientos físicos del prototipo real:

* **Arranque en `0.0` tras calibración:** Una vez superados los `6 s` de calibración inicial, los campos `BPM` y `RPM` transmiten `0.0` hasta que el firmware detecta al menos **2 latidos** o **2 ciclos respiratorios** consecutivos.
* **Transición post-ejercicio (`255` y aviso `2`):** Al detenerse bruscamente tras correr, el índice de movimiento cae rápido a `0` mientras FC y FR permanecen en nivel `2`, generando transitoriamente actividad `255` y aviso experimental `2` durante la fase de recuperación.
* **Sensibilidad postural y artefactos:** Inclinarse hacia delante desplaza el offset mecánico del potenciómetro y puede congelar temporalmente el cálculo de RPM; correr, el vello pectoral o el sudor introducen deriva de línea base o ruido en la señal ECG.

---

## 3. Requisitos Funcionales y de Calidad (App Móvil)

- [ ] **1. Visualización ECG en tiempo real:** Gráfica fluida con ventana deslizante de **4 a 8 segundos a 100 Hz**, incorporando un selector para alternar entre señal **filtrada** y **cruda** (publicando el comando de control por MQTT hacia el simulador o pasarela).
- [ ] **2. Panel de constantes vitales:** Lectura numérica clara de **BPM**, **RPM**, **Temperatura (`°C`)**, estado de **actividad física** (`Baja` / `Media` / `Intensa`) y **avisos experimentales**.
- [ ] **3. Gestión limpia de calibración y código `255`:** Indicador de estado explícito durante los `6 s` iniciales de calibración respiratoria (evitando mostrar valores erróneos antes de tiempo) y traducción amigable del código `255` (p. ej., *"En transición / Sin clasificar"* y *"Sin avisos"*, nunca errores ni campos vacíos/rotos).
- [ ] **4. Historial persistente y consulta:** Almacenamiento estructurado local/remoto y consulta tanto gráfica como tabular por fecha de las medias periódicas de frecuencia cardíaca (y evolución por sesión), superando las limitaciones de `TinyDB`.
- [ ] **5. Cumplimiento estricto de rigor académico:** Eliminación total de terminología clínica (*"diagnóstico médico"*, *"taquicardia"*, *"depresión vital"*, *"colapso"*) en favor de etiquetas técnicas experimentales neutras.
