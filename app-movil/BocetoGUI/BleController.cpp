#include "BleController.h"
#include <QDebug>

BleController::BleController(QObject *parent) : QObject(parent) {}
bool BleController::isConnected() const { return m_connected; }
int BleController::heartRate() const { return m_hr; }
int BleController::respRate() const { return m_rr; }
double BleController::temperature() const { return m_temp; }

void BleController::scanDevices() {
    qDebug() << "Buscando dispositivos VitaBand (RF-04)...";
    // Simulamos encontrar un dispositivo
    emit deviceFound("VitaBand-001", "00:11:22:33:44:55");
}

void BleController::connectToDevice(const QString &address) {
    qDebug() << "Conectando a" << address << "(RF-05)...";
    m_connected = true;
    emit connectionChanged();
    
    // Simulamos la recepción de mediciones (RF-07)
    m_hr = 75;
    m_rr = 16;
    m_temp = 36.5;
    emit metricsChanged();
}

void BleController::disconnectDevice() {
    qDebug() << "Desconectando dispositivo (RF-06)...";
    m_connected = false;
    emit connectionChanged();
}

void BleController::startActivity() {
    qDebug() << "Iniciando registro de actividad deportiva (RF-30)...";
}

void BleController::stopActivity() {
    qDebug() << "Finalizando actividad (RF-31)...";
}
