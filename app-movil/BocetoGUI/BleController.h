#ifndef BLECONTROLLER_H
#define BLECONTROLLER_H
#include <QObject>
#include <QString>

class BleController : public QObject {
    Q_OBJECT
    Q_PROPERTY(bool isConnected READ isConnected NOTIFY connectionChanged)
    Q_PROPERTY(int heartRate READ heartRate NOTIFY metricsChanged)
    Q_PROPERTY(int respRate READ respRate NOTIFY metricsChanged)
    Q_PROPERTY(double temperature READ temperature NOTIFY metricsChanged)
public:
    explicit BleController(QObject *parent = nullptr);
    bool isConnected() const;
    int heartRate() const;
    int respRate() const;
    double temperature() const;

public slots:
    void scanDevices();
    void connectToDevice(const QString &address);
    void disconnectDevice();
    void startActivity();
    void stopActivity();

signals:
    void connectionChanged();
    void metricsChanged();
    void deviceFound(const QString &name, const QString &address);
    void errorOccurred(const QString &errorMsg);

private:
    bool m_connected = false;
    int m_hr = 0;
    int m_rr = 0;
    double m_temp = 0.0;
};
#endif
