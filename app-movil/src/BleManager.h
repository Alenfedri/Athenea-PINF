// =============================================================================
//  BleManager.h  -  "El traductor de VitaBand"
// -----------------------------------------------------------------------------
//  QUÉ ES:   Una clase de C++ que habla por Bluetooth Low Energy (BLE) con la
//            pulsera/banda VitaBand y le pasa los datos a la pantalla (QML).
//  ANALOGÍA: Es como un intérprete. La banda "habla" en bytes (números sueltos);
//            esta clase los traduce a "frecuencia cardíaca = 72 lpm", etc.
//  PROTOCOLO (sacado del TFG de VitaBand):
//      Servicio  12345678-1234-5678-1234-56789abcdef0
//      Carac. 1  ...abcdef1  (NOTIFY)  la banda envía paquetes de 10 bytes
//                                      (cada 10 s uno de 12 bytes con la media)
//      Carac. 2  ...abcdef2  (WRITE)   la app le dice a la banda qué señal ECG enviar
//  PAQUETE (cada dato de 2 bytes va "byte bajo primero", llamado little-endian):
//      bytes 0-1  ECG (con signo)          bytes 2-3  Frec. cardíaca  x100
//      bytes 4-5  Frec. respiratoria x100  bytes 6-7  Temperatura °C  x100
//      byte  8    Actividad (0 reposo,1 media,2 intensa)
//      byte  9    Aviso (0 depresión vital,1 taquicardia,2 colapso,255 ninguno)
//      bytes 10-11 (solo paquete de 12) media de frec. cardíaca x100
// =============================================================================
#pragma once
#include <QObject>
#include <QTimer>
#include <QVariantList>
#include <QBluetoothDeviceDiscoveryAgent>
#include <QBluetoothDeviceInfo>
#include <QLowEnergyController>
#include <QLowEnergyService>

class BleManager : public QObject
{
    Q_OBJECT
    // Las "Q_PROPERTY" son ventanitas por las que la pantalla (QML) puede
    // leer valores. Cuando un valor cambia, la pantalla se actualiza sola.
    Q_PROPERTY(QString state READ state NOTIFY stateChanged)          // disconnected|scanning|connecting|connected|error
    Q_PROPERTY(QString deviceName READ deviceName NOTIFY stateChanged)
    Q_PROPERTY(QString errorText READ errorText NOTIFY stateChanged)
    Q_PROPERTY(QVariantList devices READ devices NOTIFY devicesChanged)
    Q_PROPERTY(bool simulated READ simulated NOTIFY stateChanged)
    Q_PROPERTY(double heartRate READ heartRate NOTIFY vitalsChanged)
    Q_PROPERTY(double respRate READ respRate NOTIFY vitalsChanged)
    Q_PROPERTY(double temperature READ temperature NOTIFY vitalsChanged)
    Q_PROPERTY(double avgHeartRate READ avgHeartRate NOTIFY vitalsChanged)
    Q_PROPERTY(int activity READ activity NOTIFY vitalsChanged)
    Q_PROPERTY(int alert READ alert NOTIFY vitalsChanged)
    Q_PROPERTY(bool ecgFilterOff READ ecgFilterOff WRITE setEcgFilterOff NOTIFY ecgFilterChanged)

public:
    explicit BleManager(QObject *parent = nullptr);

    QString state() const { return m_state; }
    QString deviceName() const { return m_deviceName; }
    QString errorText() const { return m_error; }
    QVariantList devices() const { return m_deviceList; }
    bool simulated() const { return m_simulated; }
    double heartRate() const { return m_hr; }
    double respRate() const { return m_rr; }
    double temperature() const { return m_temp; }
    double avgHeartRate() const { return m_avg; }
    int activity() const { return m_activity; }
    int alert() const { return m_alert; }
    bool ecgFilterOff() const { return m_ecgFilterOff; }
    void setEcgFilterOff(bool off);

    // Q_INVOKABLE = "la pantalla puede llamar a esta función como un botón"
    Q_INVOKABLE void startScan();                 // RF-04 buscar dispositivos
    Q_INVOKABLE void connectTo(int index);        // RF-05 conectar al elegido
    Q_INVOKABLE void disconnectDevice();          // RF-06 desconectar
    Q_INVOKABLE void startSimulation();           // modo de pruebas sin banda
    Q_INVOKABLE void stopSimulation();

signals:
    void stateChanged();
    void devicesChanged();
    void vitalsChanged();
    void ecgFilterChanged();
    void ecgSample(int value);                    // una muestra de ECG (unas 100 por segundo)
    void unexpectedDisconnect();                  // RF-06 aviso de desconexión inesperada
    void snapshot(double hr, double rr, double temp, int activity); // 1 foto por segundo (para guardar)

private slots:
    void onDeviceDiscovered(const QBluetoothDeviceInfo &info);
    void onScanFinished();
    void onScanError();
    void onServiceDiscovered(const QBluetoothUuid &uuid);
    void onServiceStateChanged(QLowEnergyService::ServiceState s);
    void onCharacteristicChanged(const QLowEnergyCharacteristic &c, const QByteArray &value);
    void onControllerError(QLowEnergyController::Error e);
    void onControllerDisconnected();
    void simulationTick();
    void snapshotTick();

private:
    void setState(const QString &s, const QString &err = QString());
    void parsePacket(const QByteArray &data);
    void cleanupConnection();

    QString m_state = "disconnected", m_deviceName, m_error;
    bool m_simulated = false, m_ecgFilterOff = false, m_userDisconnect = false;
    double m_hr = 0, m_rr = 0, m_temp = 0, m_avg = 0;
    int m_activity = 255, m_alert = 255;
    qint64 m_packets = 0;

    QBluetoothDeviceDiscoveryAgent *m_agent = nullptr;
    QList<QBluetoothDeviceInfo> m_found;
    QVariantList m_deviceList;
    QLowEnergyController *m_controller = nullptr;
    QLowEnergyService *m_service = nullptr;
    QTimer m_simTimer, m_snapTimer;
    double m_simT = 0;
    int m_simCount = 0;
};
