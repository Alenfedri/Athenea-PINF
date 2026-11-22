// =============================================================================
//  [Se publica como "Lang" desde main.cpp]
//  Lang.qml  -  "El diccionario" español / inglés (RF multidioma del wireframe)
//  USO en cualquier pantalla:   text: Lang.t("login")
//  Cambiar idioma:               Lang.setLanguage("en")   (se recuerda al cerrar)
//  PARA AÑADIR UN TEXTO: añade la misma clave en "es" y en "en".
// =============================================================================
import QtQuick
import QtCore

QtObject {
    id: root
    property Settings store: Settings { category: "language"; property string code: "es" }
    readonly property string code: store.code
    function setLanguage(c) { store.code = c }

    // Devuelve el texto en el idioma actual. Si falta la clave, muestra la clave.
    function t(key) {
        var d = dict[code]
        return (d && d[key] !== undefined) ? d[key] : key
    }

    readonly property var dict: ({
        "es": {
            appName: "VitaBand Software", tagline: "Tu salud, en tiempo real",
            user: "Usuario", password: "Contraseña", confirmPassword: "Confirmar contraseña",
            login: "Iniciar sesión", register: "Registrarse", createAccount: "Crear cuenta",
            name: "Nombre", surname: "Apellidos", username: "Nombre de usuario", email: "Correo electrónico",
            badLogin: "Usuario o contraseña incorrectos",
            e_exists: "Ese usuario ya existe", e_invalid: "Revisa los datos del formulario", e_email: "Correo no válido",
            e_weak: "La contraseña debe tener al menos 6 caracteres", e_mismatch: "Las contraseñas no coinciden",
            tabMonitor: "Inicio", tabEcg: "ECG", tabHistory: "Historial", tabActivity: "Deporte", tabMore: "Más",
            heartRate: "Frec. cardíaca", respRate: "Frec. respiratoria", temperature: "Temperatura", activityLevel: "Actividad",
            bpm: "lpm", rpm: "rpm", celsius: "°C",
            rest: "Reposo", medium: "Media", intense: "Intensa",
            alert0: "Depresión vital", alert1: "Taquicardia", alert2: "Colapso",
            connected: "Conectado", disconnected: "Desconectado", scanning: "Buscando…", connecting: "Conectando…", error: "Error de comunicación",
            connection: "Conexión", scan: "Buscar VitaBand", disconnect: "Desconectar", connect: "Conectar", demo: "Probar con simulador",
            noDevices: "No se han encontrado dispositivos", foundDevices: "Dispositivos encontrados", signal: "Señal",
            skipConnect: "No mostrar esta pantalla al iniciar", continueBtn: "Continuar",
            permission: "Falta el permiso de Bluetooth", lostConn: "Se ha perdido la conexión con VitaBand",
            firstTime: "Primera vez: acerca la banda y pulsa Buscar", calibrating: "Calibrando respiración…",
            ecgTitle: "Electrocardiograma", live: "EN DIRECTO", noSignal: "Sin señal", filterOff: "Desactivar filtro ECG",
            signalOk: "Señal correcta", lastUpdate: "Actualizado",
            history: "Historial", evolution: "Evolución", filters: "Filtros", range: "Periodo", type: "Tipo", variable: "Variable",
            last1h: "Última hora", today: "Hoy", last7: "Últimos 7 días", last30: "Últimos 30 días",
            all: "Todos", periodic: "Periódico", sport: "Deportivo", noData: "Todavía no hay mediciones",
            activities: "Actividades deportivas", startActivity: "Iniciar actividad", stopActivity: "Finalizar y guardar",
            chooseActivity: "Elige una actividad", summary: "Resumen de actividad", duration: "Duración", savedActivities: "Actividades guardadas",
            walk: "Caminar", run: "Correr", cycling: "Ciclismo", swim: "Natación", hiking: "Senderismo", strength: "Fuerza", training: "Entrenamiento general", other: "Otra",
            avg: "Media", min: "Mínima", max: "Máxima", close: "Cerrar", recording: "Grabando",
            more: "Más opciones", sync: "Sincronización", stats: "Estadísticas y observaciones", settings: "Ajustes", template: "Plantilla de pantalla", logout: "Cerrar sesión",
            pending: "Pendientes de enviar", lastSync: "Última sincronización", never: "Nunca", syncNow: "Sincronizar ahora",
            syncDone: "Sincronización completada", syncNothing: "No hay datos pendientes", syncing: "Preparando paquete…",
            mobileState: "Móvil", pcState: "Ordenador", ready: "Listo", waitingPc: "Esperando al ordenador", file: "Archivo generado",
            day: "Día", week: "Semana", month: "Mes", observations: "Observaciones",
            infoOnly: "Información orientativa. No sustituye la valoración de un profesional sanitario.",
            o_NO_DATA: "Aún no hay suficientes datos para generar observaciones.",
            o_REST_HR: "Tu frecuencia cardíaca media en reposo ha sido de %1 lpm.",
            o_ACT_HR: "Durante la actividad, tu frecuencia media fue de %1 lpm.",
            o_HIGH_REST_HR: "Tu pulso en reposo es algo elevado. Si se repite, conviene consultarlo.",
            o_LOW_REST_HR: "Tu pulso en reposo es bajo. Es habitual en personas entrenadas.",
            o_HIGH_REST_RR: "Tu respiración en reposo es algo rápida.",
            o_HIGH_TEMP: "Tu temperatura media ha sido algo alta.",
            language: "Idioma", spanish: "Español", english: "English", account: "Cuenta", dataMgmt: "Gestión de datos",
            delMeas: "Borrar historial periódico", delAll: "Borrar todo el historial", delAccount: "Eliminar cuenta",
            confirm: "Confirmar", cancel: "Cancelar", areYouSure: "¿Seguro?",
            delMeasMsg: "Se borrará el historial periódico. Las actividades guardadas se conservan.",
            delAllMsg: "Se borrarán TODAS las mediciones y actividades de este móvil.",
            delAccMsg: "Se eliminará tu cuenta y todos sus datos. No se puede deshacer.", done: "Hecho",
            about: "Acerca de", version: "Versión",
            tplTitle: "Título de la pantalla", tplSection: "Sección desplegable", tplOptions: "Opciones", tplChoose: "Elige una opción",
            tplSwitch: "Interruptor", tplSlider: "Deslizador", tplCheck: "Casilla", tplPrimary: "Botón principal", tplSecondary: "Botón secundario",
            tplTabs: "Pestañas", tplCard: "Tarjeta con animación", tplPopup: "Abrir ventana emergente", tplToast: "Mostrar aviso", tplHello: "¡Hola desde la plantilla!"
        },
        "en": {
            appName: "VitaBand Software", tagline: "Your health, in real time",
            user: "User", password: "Password", confirmPassword: "Confirm password",
            login: "Sign in", register: "Sign up", createAccount: "Create account",
            name: "First name", surname: "Last name", username: "Username", email: "Email",
            badLogin: "Wrong username or password",
            e_exists: "That username already exists", e_invalid: "Please check the form", e_email: "Invalid email",
            e_weak: "Password must be at least 6 characters", e_mismatch: "Passwords do not match",
            tabMonitor: "Home", tabEcg: "ECG", tabHistory: "History", tabActivity: "Sport", tabMore: "More",
            heartRate: "Heart rate", respRate: "Respiratory rate", temperature: "Temperature", activityLevel: "Activity",
            bpm: "bpm", rpm: "rpm", celsius: "°C",
            rest: "Rest", medium: "Medium", intense: "Intense",
            alert0: "Vital depression", alert1: "Tachycardia", alert2: "Collapse",
            connected: "Connected", disconnected: "Disconnected", scanning: "Scanning…", connecting: "Connecting…", error: "Communication error",
            connection: "Connection", scan: "Search VitaBand", disconnect: "Disconnect", connect: "Connect", demo: "Try with simulator",
            noDevices: "No devices found", foundDevices: "Devices found", signal: "Signal",
            skipConnect: "Don't show this screen at startup", continueBtn: "Continue",
            permission: "Bluetooth permission is missing", lostConn: "Connection with VitaBand was lost",
            firstTime: "First time: bring the band close and tap Search", calibrating: "Calibrating breathing…",
            ecgTitle: "Electrocardiogram", live: "LIVE", noSignal: "No signal", filterOff: "Disable ECG filter",
            signalOk: "Signal OK", lastUpdate: "Updated",
            history: "History", evolution: "Evolution", filters: "Filters", range: "Period", type: "Type", variable: "Variable",
            last1h: "Last hour", today: "Today", last7: "Last 7 days", last30: "Last 30 days",
            all: "All", periodic: "Periodic", sport: "Sport", noData: "No measurements yet",
            activities: "Sport activities", startActivity: "Start activity", stopActivity: "Finish and save",
            chooseActivity: "Choose an activity", summary: "Activity summary", duration: "Duration", savedActivities: "Saved activities",
            walk: "Walking", run: "Running", cycling: "Cycling", swim: "Swimming", hiking: "Hiking", strength: "Strength", training: "General training", other: "Other",
            avg: "Average", min: "Minimum", max: "Maximum", close: "Close", recording: "Recording",
            more: "More options", sync: "Synchronization", stats: "Statistics and insights", settings: "Settings", template: "Screen template", logout: "Sign out",
            pending: "Pending to send", lastSync: "Last sync", never: "Never", syncNow: "Sync now",
            syncDone: "Synchronization completed", syncNothing: "Nothing pending", syncing: "Preparing package…",
            mobileState: "Mobile", pcState: "Computer", ready: "Ready", waitingPc: "Waiting for computer", file: "File created",
            day: "Day", week: "Week", month: "Month", observations: "Insights",
            infoOnly: "Informative only. It does not replace the assessment of a healthcare professional.",
            o_NO_DATA: "Not enough data yet to generate insights.",
            o_REST_HR: "Your average resting heart rate was %1 bpm.",
            o_ACT_HR: "During activity your average heart rate was %1 bpm.",
            o_HIGH_REST_HR: "Your resting pulse is a bit high. If it repeats, consider checking it.",
            o_LOW_REST_HR: "Your resting pulse is low. This is common in trained people.",
            o_HIGH_REST_RR: "Your resting breathing is a bit fast.",
            o_HIGH_TEMP: "Your average temperature was a bit high.",
            language: "Language", spanish: "Español", english: "English", account: "Account", dataMgmt: "Data management",
            delMeas: "Delete periodic history", delAll: "Delete all history", delAccount: "Delete account",
            confirm: "Confirm", cancel: "Cancel", areYouSure: "Are you sure?",
            delMeasMsg: "The periodic history will be deleted. Saved activities are kept.",
            delAllMsg: "ALL measurements and activities on this phone will be deleted.",
            delAccMsg: "Your account and all its data will be deleted. This cannot be undone.", done: "Done",
            about: "About", version: "Version",
            tplTitle: "Screen title", tplSection: "Collapsible section", tplOptions: "Options", tplChoose: "Pick an option",
            tplSwitch: "Switch", tplSlider: "Slider", tplCheck: "Checkbox", tplPrimary: "Primary button", tplSecondary: "Secondary button",
            tplTabs: "Tabs", tplCard: "Animated card", tplPopup: "Open popup", tplToast: "Show toast", tplHello: "Hello from the template!"
        }
    })
}
