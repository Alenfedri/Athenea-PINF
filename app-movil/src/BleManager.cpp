// =============================================================================
//  BleManager.cpp  -  Implementación (el "cómo" de BleManager.h)
//  Los comentarios explican cada paso en lenguaje llano.
// =============================================================================
#include "BleManager.h"
#include <QBluetoothUuid>
#include <QtEndian>
#include <QtMath>
#include <QRandomGenerator>
#include <QCoreApplication>
#include <QPermissions>

// Los identificadores únicos (UUID) de la banda. Son como el "número de
// teléfono" con el que la app llama al servicio de datos de VitaBand.
static const QBluetoothUuid SERVICE_UUID(QUuid("12345678-1234-5678-1234-56789abcdef0"));
static const QBluetoothUuid CHAR_DATA_UUID(QUuid("12345678-1234-5678-1234-56789abcdef1"));
static const QBluetoothUuid CHAR_CTRL_UUID(QUuid("12345678-1234-5678-1234-56789abcdef2"));

BleManager::BleManager(QObject *parent) : QObject(parent)
{
    // Temporizador del simulador: 10 ms = 100 muestras de ECG por segundo,
    // igual que la banda real ("periodo nominal de 10 ms" según el TFG).
    m_simTimer.setInterval(10);
    connect(&m_simTimer, &QTimer::timeout, this, &BleManager::simulationTick);

    // Temporizador de "fotos": cada segundo avisa para que la base de datos
    // pueda guardar los valores actuales.
    m_snapTimer.setInterval(1000);
    connect(&m_snapTimer, &QTimer::timeout, this, &BleManager::snapshotTick);
    m_snapTimer.start();
}

void BleManager::setState(const QString &s, const QString &err)
{
    m_state = s;
    m_error = err;
    emit stateChanged();
}

// ----------------------------------------------------------------------------
//  1) BUSCAR dispositivos (RF-04)
// ----------------------------------------------------------------------------
void BleManager::startScan()
{
    if (m_simulated) stopSimulation();

    // Android/iOS exigen permiso de Bluetooth. Lo pedimos aquí.
    QBluetoothPermission perm;
    perm.setCommunicationModes(QBluetoothPermission::Access);
    switch (qApp->checkPermission(perm)) {
    case Qt::PermissionStatus::Undetermined:
        qApp->requestPermission(perm, this, [this](const QPermission &) { startScan(); }); // pregunta y reintenta
        return;
    case Qt::PermissionStatus::Denied:
        setState("error", "permission");
        return;
    default: break;
    }

    m_found.clear();
    m_deviceList.clear();
    emit devicesChanged();

    if (!m_agent) {
        m_agent = new QBluetoothDeviceDiscoveryAgent(this);
        m_agent->setLowEnergyDiscoveryTimeout(8000); // busca 8 segundos
        connect(m_agent, &QBluetoothDeviceDiscoveryAgent::deviceDiscovered, this, &BleManager::onDeviceDiscovered);
        connect(m_agent, &QBluetoothDeviceDiscoveryAgent::finished, this, &BleManager::onScanFinished);
        connect(m_agent, &QBluetoothDeviceDiscoveryAgent::canceled, this, &BleManager::onScanFinished);
        connect(m_agent, &QBluetoothDeviceDiscoveryAgent::errorOccurred, this, &BleManager::onScanError);
    }
    setState("scanning");
    m_agent->start(QBluetoothDeviceDiscoveryAgent::LowEnergyMethod);
}

void BleManager::onDeviceDiscovered(const QBluetoothDeviceInfo &info)
{
    if (!(info.coreConfigurations() & QBluetoothDeviceInfo::LowEnergyCoreConfiguration)) return;
    // Solo nos interesan los dispositivos llamados "VitaBand" o que anuncien nuestro servicio.
    const bool ours = info.name().contains("VitaBand", Qt::CaseInsensitive)
                      || info.serviceUuids().contains(SERVICE_UUID);
    if (!ours) return;
    for (const auto &d : std::as_const(m_found))
        if (d.address() == info.address() && d.deviceUuid() == info.deviceUuid()) return; // ya está

    m_found.append(info);
    QVariantMap item;
    item["name"] = info.name().isEmpty() ? "VitaBand" : info.name();
    item["address"] = info.address().isNull() ? info.deviceUuid().toString() : info.address().toString();
    item["rssi"] = info.rssi();   // intensidad de señal (más cerca de 0 = más cerca de la banda)
    m_deviceList.append(item);
    emit devicesChanged();
}

void BleManager::onScanFinished()
{
    if (m_state == "scanning") setState("disconnected");
}

void BleManager::onScanError()
{
    setState("error", m_agent ? m_agent->errorString() : "scan");
}

// ----------------------------------------------------------------------------
//  2) CONECTAR (RF-05)
// ----------------------------------------------------------------------------
void BleManager::connectTo(int index)
{
    if (index < 0 || index >= m_found.size()) return;
    if (m_agent && m_agent->isActive()) m_agent->stop();
    cleanupConnection();

    const QBluetoothDeviceInfo &info = m_found.at(index);
    m_deviceName = info.name().isEmpty() ? "VitaBand" : info.name();
    m_userDisconnect = false;
    m_packets = 0;
    setState("connecting");

    m_controller = QLowEnergyController::createCentral(info, this);
    connect(m_controller, &QLowEnergyController::connected, m_controller, &QLowEnergyController::discoverServices);
    connect(m_controller, &QLowEnergyController::serviceDiscovered, this, &BleManager::onServiceDiscovered);
    connect(m_controller, &QLowEnergyController::discoveryFinished, this, [this]() {
        if (!m_service) setState("error", "service"); // la banda no tiene el servicio esperado
    });
    connect(m_controller, &QLowEnergyController::errorOccurred, this, &BleManager::onControllerError);
    connect(m_controller, &QLowEnergyController::disconnected, this, &BleManager::onControllerDisconnected);
    m_controller->connectToDevice();
}

void BleManager::onServiceDiscovered(const QBluetoothUuid &uuid)
{
    if (uuid != SERVICE_UUID || m_service) return;
    m_service = m_controller->createServiceObject(uuid, this);
    if (!m_service) return;
    connect(m_service, &QLowEnergyService::stateChanged, this, &BleManager::onServiceStateChanged);
    connect(m_service, &QLowEnergyService::characteristicChanged, this, &BleManager::onCharacteristicChanged);
    m_service->discoverDetails();
}

void BleManager::onServiceStateChanged(QLowEnergyService::ServiceState s)
{
    if (s != QLowEnergyService::RemoteServiceDiscovered) return;
    // Nos "suscribimos" a la característica de datos: escribir 0x0001 en su
    // descriptor CCCD equivale a decir "avísame cada vez que haya datos nuevos".
    const auto ch = m_service->characteristic(CHAR_DATA_UUID);
    if (!ch.isValid()) { setState("error", "characteristic"); return; }
    const auto cccd = ch.descriptor(QBluetoothUuid::DescriptorType::ClientCharacteristicConfiguration);
    if (cccd.isValid()) m_service->writeDescriptor(cccd, QByteArray::fromHex("0100"));
    // Seguimos en "connecting" hasta recibir el primer paquete (la banda calibra la respiración antes).
    setEcgFilterOff(m_ecgFilterOff); // reenvía la selección de señal ECG
}

// ----------------------------------------------------------------------------
//  3) RECIBIR y TRADUCIR paquetes (RF-07)
// ----------------------------------------------------------------------------
void BleManager::onCharacteristicChanged(const QLowEnergyCharacteristic &c, const QByteArray &value)
{
    if (c.uuid() == CHAR_DATA_UUID) parsePacket(value);
}

void BleManager::parsePacket(const QByteArray &d)
{
    // Solo existen dos tamaños válidos: 10 (normal) y 12 (con media cada 10 s).
    if (d.size() != 10 && d.size() != 12) return;
    const uchar *p = reinterpret_cast<const uchar *>(d.constData());

    const int ecg = qFromLittleEndian<qint16>(p + 0);                 // señal ECG (con signo)
    m_hr   = qFromLittleEndian<quint16>(p + 2) / 100.0;               // lpm
    m_rr   = qFromLittleEndian<quint16>(p + 4) / 100.0;               // rpm
    m_temp = qFromLittleEndian<quint16>(p + 6) / 100.0;               // °C
    m_activity = p[8];
    m_alert = p[9];
    if (d.size() == 12) m_avg = qFromLittleEndian<quint16>(p + 10) / 100.0;

    if (m_packets++ == 0 && m_state != "connected")
        setState("connected");     // primer paquete = calibración terminada = ¡conectado!

    emit ecgSample(ecg);
    emit vitalsChanged();
}

void BleManager::setEcgFilterOff(bool off)
{
    m_ecgFilterOff = off;
    emit ecgFilterChanged();
    if (!m_service) return;
    const auto ch = m_service->characteristic(CHAR_CTRL_UUID);
    if (ch.isValid())   // 0 = señal filtrada, 1 = señal original sin filtrar
        m_service->writeCharacteristic(ch, QByteArray(1, off ? 1 : 0), QLowEnergyService::WriteWithResponse);
}

// ----------------------------------------------------------------------------
//  4) DESCONECTAR / errores (RF-06)
// ----------------------------------------------------------------------------
void BleManager::disconnectDevice()
{
    if (m_simulated) { stopSimulation(); return; }
    m_userDisconnect = true;
    if (m_controller) m_controller->disconnectFromDevice();
    cleanupConnection();
    setState("disconnected");
}

void BleManager::onControllerError(QLowEnergyController::Error)
{
    const QString msg = m_controller ? m_controller->errorString() : QString();
    cleanupConnection();
    setState("error", msg);
}

void BleManager::onControllerDisconnected()
{
    const bool wasConnected = (m_state == "connected");
    cleanupConnection();
    setState("disconnected");
    if (wasConnected && !m_userDisconnect) emit unexpectedDisconnect(); // la banda se apagó o se alejó
}

void BleManager::cleanupConnection()
{
    if (m_service) { m_service->deleteLater(); m_service = nullptr; }
    if (m_controller) { m_controller->disconnect(this); m_controller->deleteLater(); m_controller = nullptr; }
    m_hr = m_rr = m_temp = m_avg = 0; m_activity = m_alert = 255;
    emit vitalsChanged();
}

// ----------------------------------------------------------------------------
//  5) SIMULADOR: genera datos falsos con el MISMO formato de paquete que la
//     banda real. Así se puede probar toda la app sin tener la banda delante,
//     y de paso se comprueba que el "traductor" (parsePacket) funciona.
// ----------------------------------------------------------------------------
void BleManager::startSimulation()
{
    if (m_agent && m_agent->isActive()) m_agent->stop();
    cleanupConnection();
    m_simulated = true;
    m_deviceName = "VitaBand (demo)";
    m_simT = 0; m_simCount = 0; m_packets = 0;
    setState("connected");
    m_simTimer.start();
}

void BleManager::stopSimulation()
{
    m_simTimer.stop();
    m_simulated = false;
    m_hr = m_rr = m_temp = m_avg = 0; m_activity = m_alert = 255;
    emit vitalsChanged();
    setState("disconnected");
}

// Función auxiliar: una "campana" matemática (gaussiana) para dibujar cada onda del ECG.
static double bump(double x, double c, double w, double a) { return a * qExp(-((x - c) * (x - c)) / (2 * w * w)); }

void BleManager::simulationTick()
{
    m_simT += 0.01;                                              // avanza 10 ms
    const int act = (int(m_simT / 45) % 3);                      // cambia de actividad cada 45 s
    const double hr = 68 + act * 28 + 6 * qSin(m_simT / 7);       // más ejercicio = más pulso
    const double rr = 14 + act * 6 + 1.5 * qSin(m_simT / 5);
    const double temp = 36.4 + act * 0.3 + 0.1 * qSin(m_simT / 30);

    // Forma de un latido (P, Q, R, S, T) repetida cada 60/hr segundos.
    const double period = 60.0 / hr;
    const double ph = fmod(m_simT, period) / period;             // 0..1 dentro del latido
    double e = bump(ph, 0.16, 0.025, 0.12) - bump(ph, 0.285, 0.008, 0.15)
               + bump(ph, 0.30, 0.010, 1.0) - bump(ph, 0.315, 0.010, 0.25) + bump(ph, 0.52, 0.045, 0.28);
    e += 0.02 * (QRandomGenerator::global()->generateDouble() - 0.5);

    // Construimos el paquete EXACTAMENTE como lo haría el microcontrolador.
    QByteArray pk(++m_simCount % 1000 == 0 ? 12 : 10, 0);       // cada 10 s: paquete de 12 bytes
    uchar *p = reinterpret_cast<uchar *>(pk.data());
    qToLittleEndian<qint16>(qint16(2048 + e * 900), p + 0);
    qToLittleEndian<quint16>(quint16(hr * 100), p + 2);
    qToLittleEndian<quint16>(quint16(rr * 100), p + 4);
    qToLittleEndian<quint16>(quint16(temp * 100), p + 6);
    p[8] = uchar(act);
    p[9] = (hr > 150) ? 1 : 255;
    if (pk.size() == 12) qToLittleEndian<quint16>(quint16(hr * 100), p + 10);
    parsePacket(pk);
}

// Una vez por segundo: "foto" de los valores para guardarlos en la base de datos.
void BleManager::snapshotTick()
{
    if (m_state == "connected" && m_packets > 0)
        emit snapshot(m_hr, m_rr, m_temp, m_activity);
}
