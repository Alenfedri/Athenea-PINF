// =============================================================================
//  DatabaseManager.h  -  "El archivero de VitaBand"
// -----------------------------------------------------------------------------
//  QUÉ ES:   Guarda en el móvil, en un único archivo (SQLite), todo lo que la
//            app debe recordar: usuarios, mediciones y actividades deportivas.
//  ANALOGÍA: Un archivador con tres cajones: USUARIOS, MEDICIONES, ACTIVIDADES.
//            Aunque cierres la app o te quedes sin Internet, el archivo sigue ahí.
// =============================================================================
#pragma once
#include <QObject>
#include <QSqlDatabase>
#include <QTimer>
#include <QVariantList>
#include <QVariantMap>

class DatabaseManager : public QObject
{
    Q_OBJECT
    Q_PROPERTY(bool loggedIn READ loggedIn NOTIFY sessionChanged)
    Q_PROPERTY(QString userName READ userName NOTIFY sessionChanged)
    Q_PROPERTY(bool activityActive READ activityActive NOTIFY activityChanged)
    Q_PROPERTY(QString activityType READ activityType NOTIFY activityChanged)
    Q_PROPERTY(int activitySeconds READ activitySeconds NOTIFY activityTick)
    Q_PROPERTY(int pendingCount READ pendingCount NOTIFY dataChanged)   // medidas sin sincronizar
    Q_PROPERTY(qint64 lastSync READ lastSync NOTIFY dataChanged)

public:
    explicit DatabaseManager(QObject *parent = nullptr);
    bool open();

    bool loggedIn() const { return m_userId > 0; }
    QString userName() const { return m_displayName; }
    bool activityActive() const { return m_activityId > 0; }
    QString activityType() const { return m_activityType; }
    int activitySeconds() const;
    int pendingCount() const;
    qint64 lastSync() const { return m_lastSync; }

    // ---- Cuenta de usuario (RF-01, 02, 41) ----
    // Devuelve "" si todo fue bien, o un código de error ("exists", "invalid"...)
    Q_INVOKABLE QString registerUser(const QString &name, const QString &surname, const QString &username,
                                     const QString &email, const QString &password, const QString &confirm);
    Q_INVOKABLE bool login(const QString &username, const QString &password);
    Q_INVOKABLE void logout();
    Q_INVOKABLE bool deleteAccount();                                    // RF-39

    // ---- Actividades deportivas (RF-30, 31, 32, 50) ----
    Q_INVOKABLE void startActivity(const QString &type);
    Q_INVOKABLE QVariantMap finishActivity();                            // devuelve el resumen
    Q_INVOKABLE QVariantList activities();

    // ---- Consultas para pantallas (RF-09, 15, 16, 22, 24) ----
    Q_INVOKABLE QVariantList history(qint64 fromMs, qint64 toMs, const QString &kind, int limit = 300);
    Q_INVOKABLE QVariantList series(qint64 fromMs, qint64 toMs, const QString &field, int maxPoints = 120);
    Q_INVOKABLE QVariantList activitySeries(qint64 activityId, const QString &field);
    Q_INVOKABLE QVariantMap stats(qint64 fromMs, qint64 toMs);
    Q_INVOKABLE QStringList observations(qint64 fromMs, qint64 toMs);    // textos orientativos, NO diagnósticos
    Q_INVOKABLE QVariantList activityDistribution(qint64 fromMs, qint64 toMs);

    // ---- Sincronización con el PC (RF-18..21, 28) ----
    Q_INVOKABLE QString exportPending();       // crea un archivo JSON con lo pendiente
    Q_INVOKABLE void markSynced();             // marca lo pendiente como enviado

    // ---- Borrado y mantenimiento (RF-38, 40, 46) ----
    Q_INVOKABLE void deleteMeasurements();                 // borra el historial (conserva actividades)
    Q_INVOKABLE void deleteEverything();                   // borra TODO el historial del usuario
    Q_INVOKABLE void purgeOld(int days = 30);

public slots:
    void onSnapshot(double hr, double rr, double temp, int activity);   // llega 1 vez por segundo

signals:
    void sessionChanged();
    void activityChanged();
    void activityTick();
    void dataChanged();

private:
    bool exec(const QString &sql, const QVariantList &args = {});
    void createTables();
    void saveMeasurement(double hr, double rr, double t, int act, const QString &kind, qint64 activityId);
    static QString hash(const QString &salt, const QString &pw);

    QSqlDatabase m_db;
    int m_userId = 0;
    QString m_displayName;
    qint64 m_activityId = 0, m_activityStart = 0, m_lastSync = 0;
    QString m_activityType;
    int m_tick = 0;
    QTimer m_clock;
};
