# Documentación Técnica — VitaBand (Arquitectura Software y App Móvil)

> **⚠️ AVISO DE ALCANCE ACADÉMICO (NO CLÍNICO):**  
> **VitaBand** es un prototipo experimental desarrollado en el ámbito académico de la **Escuela Superior de Ingeniería (ESI) de la Universidad de Cádiz (UCA)**. **No es un dispositivo médico certificado** ni ha sido sometido a validación clínica. Toda la interfaz, la documentación y los registros emplean exclusivamente terminología técnica neutra (por ejemplo, *"aviso experimental"*, *"FC elevada en reposo"* o *"niveles bajos en reposo"*), quedando prohibido el uso de términos clínicos o diagnósticos (*diagnóstico*, *taquicardia*, *depresión vital*, *colapso*).

---

## 1. Contexto y Motivación del Rediseño

**VitaBand** es un cinturón biométrico torácico colocado sobre el esternón que adquiere señal electrocardiográfica (ECG), frecuencia cardíaca (BPM), frecuencia respiratoria (RPM), temperatura cutánea y nivel de actividad física. El hardware y el firmware embebido proceden del TFG en Ingeniería Electrónica Industrial de Luis Fernando Barba Céspedes (UCA, septiembre de 2026), tutorizado por el Prof. Arturo Morgado Estévez y cotutorizado por Blas Salvador Domínguez.

La primera aplicación móvil desarrollada en **MIT App Inventor** actuó únicamente como prueba de concepto y presenta limitaciones estructurales que este proyecto resuelve:
* Ausencia de ejecución en segundo plano y gestión deficiente de reconexiones.
* Almacenamiento rudimentario en `TinyDB` local sin estructura relacional ni exportación.
* Renderizado del ECG mediante borrado y reinicio de un lienzo estático (`Canvas` de 400 px), poco fluido a 100 muestras/s.
* Etiquetado con terminología clínica inadecuada para un prototipo académico.

### Objetivos de esta versión
1. **Arquitectura desacoplada:** Separar la adquisición/simulación de datos de la interfaz móvil mediante un **Broker MQTT**.
2. **Entorno de desarrollo paralelo:** Disponer de un **simulador Mock en Python** que reproduzca fielmente las tramas, tiempos y casos borde del hardware real sin depender de tener la placa física conectada en todo momento.
3. **Aplicación móvil robusta:** Desarrollar una app fluida y escalable con visualización ECG en tiempo real (ventana deslizante de 4 a 8 s a 100 Hz), control remoto del filtrado, gestión limpia de calibración y estados transitorios, e historial persistente consultable por fecha.

---

## 2. Arquitectura del Sistema

El sistema se divide en tres componentes independientes que se comunican exclusivamente a través de mensajes publicados en un **Broker MQTT**:

```text
+-----------------------------------+        +-------------------+        +-----------------------------------+
|  Dispositivo VitaBand (ESP32-C6)  |        |                   |        |        Aplicación Móvil           |
|  (vía Pasarela BLE <-> MQTT)      | -----> |                   | -----> |  - Gráfica ECG (100 Hz, 4-8 s)    |
|                o                  |  MQTT  |    Broker MQTT    |  MQTT  |  - Panel de constantes y avisos   |
|     Script Mock en Python         | <----- |   [COMPLETAR]     | <----- |  - Control filtro (Crudo/Filtrado)|
|  (Emulador de tramas y escenarios)|        |                   |        |  - Historial persistente          |
+-----------------------------------+        +-------------------+        +-----------------------------------+
