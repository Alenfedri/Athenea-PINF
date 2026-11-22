// =============================================================================
//  DatabaseManager.cpp  -  Implementación del archivero (SQLite)
//  Cada función lleva un comentario que explica qué hace con palabras sencillas.
// =============================================================================
#include "DatabaseManager.h"
#include <QSqlQuery>
#include <QSqlError>
#include <QStandardPaths>
#include <QDir>
#include <QDateTime>
#include <QCryptographicHash>
#include <QUuid>
#include <QJsonDocument>
#include <QJsonArray>
#include <QJsonObject>
#include <QFile>
#include <QRegularExpression>
#include <QSettings>
#include <QDebug>
#include <QtMath>

static qint64 nowMs() { return QDateTime::currentMSecsSinceEpoch(); }

DatabaseManager::DatabaseManager(QObject *parent) : QObject(parent)
{
    // Reloj para que la pantalla vea avanzar los segundos de una actividad.
    m_clock.setInterval(1000);
    connect(&m_clock, &QTimer::timeout, this, &DatabaseManager::activityTick);
    m_lastSync = QSettings().value("lastSync", 0).toLongLong();
}

// ---------------------------------------------------------------------------
//  Abrir (o crear) el archivo de la base de datos
// ---------------------------------------------------------------------------
bool DatabaseManager::open()
{
    // Carpeta privada de la app (el sistema la reserva solo para esta app).
    const QString dir = QStandardPaths::writableLocation(QStandardPaths::AppDataLocation);
    QDir().mkpath(dir);
    m_db = QSqlDatabase::addDatabase("QSQLITE");
    m_db.setDatabaseName(dir + "/vitaband.sqlite");
    if (!m_db.open()) { qWarning() << "No se pudo abrir la BD:" << m_db.lastError(); return false; }
    exec("PRAGMA foreign_keys = ON");
    createTables();
    return true;
}

bool DatabaseManager::exec(const QString &sql, const QVariantList &args)
{
    QSqlQuery q(m_db);
    q.prepare(sql);
    for (const auto &a : args) q.addBindValue(a);   //los "?" del SQL se rellenan con args
    if (!q.exec()) { qWarning() << "SQL:" << q.lastError().text() << sql; return false; }
    return true;
}

// Las tablas de mierda. Solo se crean si aún no existen.
void DatabaseManager::createTables()
{
    exec("CREATE TABLE IF NOT EXISTS users ("
         " id INTEGER PRIMARY KEY AUTOINCREMENT,"
         " username TEXT UNIQUE NOT NULL,"       // UNIQUE = no puede haber dos iguales (RF-41)
         " name TEXT, surname TEXT, email TEXT,"
         " salt TEXT NOT NULL, pass_hash TEXT NOT NULL,"   // NUNCA se guarda la contraseña en claro
         " created_at INTEGER)");
    exec("CREATE TABLE IF NOT EXISTS activities ("
         " id INTEGER PRIMARY KEY AUTOINCREMENT,"
         " user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,"
         " type TEXT, start_ts INTEGER, end_ts INTEGER,"
         " avg_hr REAL, max_hr REAL, min_hr REAL, avg_rr REAL, avg_temp REAL,"
         " synced INTEGER DEFAULT 0)");
    exec("CREATE TABLE IF NOT EXISTS measurements ("
         " id INTEGER PRIMARY KEY AUTOINCREMENT,"
         " uuid TEXT UNIQUE NOT NULL,"             // identificador único: evita duplicados al sincronizar (RF-20)
         " user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,"
         " ts INTEGER NOT NULL,"                   // fecha y hora en milisegundos (RF-13)
         " hr REAL, rr REAL, temp REAL, activity INTEGER,"
         " kind TEXT NOT NULL,"                    // 'periodic' o 'activity' (RF-43)
         " activity_id INTEGER REFERENCES activities(id) ON DELETE CASCADE,"
         " synced INTEGER DEFAULT 0)");            // 0 = pendiente, 1 = ya enviado (RF-21, 28)
    exec("CREATE INDEX IF NOT EXISTS idx_meas_user_ts ON measurements(user_id, ts)");  // búsquedas rápidas
}

// ---------------------------------------------------------------------------
//  Usuarios
// ---------------------------------------------------------------------------
QString DatabaseManager::hash(const QString &salt, const QString &pw)
{   // "Sal + contraseña" -> huella SHA-256. Es una huella: no se puede volver atrás.
    return QCryptographicHash::hash((salt + pw).toUtf8(), QCryptographicHash::Sha256).toHex();
}

QString DatabaseManager::registerUser(const QString &name, const QString &surname, const QString &username,
                                      const QString &email, const QString &password, const QString &confirm)
{
    static const QRegularExpression mailRe(R"(^[^@\s]+@[^@\s]+\.[^@\s]+$)");
    if (name.trimmed().isEmpty() || surname.trimmed().isEmpty() || username.trimmed().size() < 3) return "invalid";
    if (!mailRe.match(email).hasMatch()) return "email";
    if (password.size() < 6) return "weak";
    if (password != confirm) return "mismatch";

    QSqlQuery q(m_db);
    q.prepare("SELECT 1 FROM users WHERE username = ?");
    q.addBindValue(username.trimmed());
    if (q.exec() && q.next()) return "exists";

    const QString salt = QUuid::createUuid().toString(QUuid::WithoutBraces);
    exec("INSERT INTO users(username,name,surname,email,salt,pass_hash,created_at) VALUES(?,?,?,?,?,?,?)",
         {username.trimmed(), name.trimmed(), surname.trimmed(), email.trimmed(), salt, hash(salt, password), nowMs()});
    return login(username, password) ? QString() : "invalid";   // tras registrarse, entra directamente
}

bool DatabaseManager::login(const QString &username, const QString &password)
{
    QSqlQuery q(m_db);
    q.prepare("SELECT id,name,salt,pass_hash FROM users WHERE username = ?");
    q.addBindValue(username.trimmed());
    if (!q.exec() || !q.next()) return false;
    if (hash(q.value(2).toString(), password) != q.value(3).toString()) return false;
    m_userId = q.value(0).toInt();
    m_displayName = q.value(1).toString();
    purgeOld(30);       // al entrar, limpia mediciones periódicas de más de 30 días (RF-40)
    emit sessionChanged(); emit dataChanged();
    return true;
}

void DatabaseManager::logout()
{
    if (activityActive()) finishActivity();
    m_userId = 0; m_displayName.clear();
    emit sessionChanged();
}

bool DatabaseManager::deleteAccount()
{
    if (!loggedIn()) return false;
    const bool ok = exec("DELETE FROM users WHERE id = ?", {m_userId});  // ON DELETE CASCADE borra sus datos
    logout();
    return ok;
}

// ---------------------------------------------------------------------------
//  Guardado automático (RF-12, 26, 30, 37)
// ---------------------------------------------------------------------------
void DatabaseManager::onSnapshot(double hr, double rr, double temp, int activity)
{
    if (!loggedIn() || hr <= 0) return;      // sin sesión o sin dato válido: no se guarda
    ++m_tick;
    if (activityActive()) saveMeasurement(hr, rr, temp, activity, "activity", m_activityId);   // detallado: 1/segundo
    if (m_tick % 10 == 0)  saveMeasurement(hr, rr, temp, activity, "periodic", 0);             // periódico: 1 cada 10 s
}

void DatabaseManager::saveMeasurement(double hr, double rr, double t, int act, const QString &kind, qint64 activityId)
{
    exec("INSERT INTO measurements(uuid,user_id,ts,hr,rr,temp,activity,kind,activity_id,synced) VALUES(?,?,?,?,?,?,?,?,?,0)",
         {QUuid::createUuid().toString(QUuid::WithoutBraces), m_userId, nowMs(), hr, rr, t, act, kind,
          activityId > 0 ? QVariant(activityId) : QVariant()});
    if (m_tick % 10 == 0) emit dataChanged();   // no avisar cada segundo para no saturar la pantalla
}

// ---------------------------------------------------------------------------
//  Actividades deportivas
// ---------------------------------------------------------------------------
int DatabaseManager::activitySeconds() const
{
    return activityActive() ? int((nowMs() - m_activityStart) / 1000) : 0;
}

void DatabaseManager::startActivity(const QString &type)
{
    if (!loggedIn() || activityActive()) return;
    m_activityStart = nowMs();
    m_activityType = type;
    QSqlQuery q(m_db);
    q.prepare("INSERT INTO activities(user_id,type,start_ts) VALUES(?,?,?)");
    q.addBindValue(m_userId); q.addBindValue(type); q.addBindValue(m_activityStart);
    q.exec();
    m_activityId = q.lastInsertId().toLongLong();
    m_clock.start();
    emit activityChanged();
}

QVariantMap DatabaseManager::finishActivity()
{
    QVariantMap out;
    if (!activityActive()) return out;
    const qint64 end = nowMs();
    QSqlQuery q(m_db);
    q.prepare("SELECT AVG(hr),MAX(hr),MIN(hr),AVG(rr),AVG(temp) FROM measurements WHERE activity_id = ?");
    q.addBindValue(m_activityId);
    q.exec();
    if (q.next()) {
        out = {{"type", m_activityType}, {"start", m_activityStart}, {"end", end}, {"seconds", int((end - m_activityStart) / 1000)},
               {"avgHr", q.value(0)}, {"maxHr", q.value(1)}, {"minHr", q.value(2)}, {"avgRr", q.value(3)}, {"avgTemp", q.value(4)}};
        exec("UPDATE activities SET end_ts=?,avg_hr=?,max_hr=?,min_hr=?,avg_rr=?,avg_temp=? WHERE id=?",
             {end, q.value(0), q.value(1), q.value(2), q.value(3), q.value(4), m_activityId});
    }
    out["id"] = m_activityId;
    m_clock.stop();
    m_activityId = 0; m_activityType.clear();
    emit activityChanged(); emit dataChanged();
    return out;
}

QVariantList DatabaseManager::activities()
{
    QVariantList list;
    QSqlQuery q(m_db);
    q.prepare("SELECT id,type,start_ts,end_ts,avg_hr,max_hr,min_hr,avg_rr FROM activities "
              "WHERE user_id=? AND end_ts IS NOT NULL ORDER BY start_ts DESC LIMIT 50");
    q.addBindValue(m_userId);
    q.exec();
    while (q.next())
        list << QVariantMap{{"id", q.value(0)}, {"type", q.value(1)}, {"start", q.value(2)},
                            {"seconds", int((q.value(3).toLongLong() - q.value(2).toLongLong()) / 1000)},
                            {"avgHr", q.value(4)}, {"maxHr", q.value(5)}, {"minHr", q.value(6)}, {"avgRr", q.value(7)}};
    return list;
}

// ---------------------------------------------------------------------------
//  Consultas
// ---------------------------------------------------------------------------
QVariantList DatabaseManager::history(qint64 fromMs, qint64 toMs, const QString &kind, int limit)
{
    QVariantList list;
    QString sql = "SELECT ts,hr,rr,temp,activity,kind FROM measurements WHERE user_id=? AND ts BETWEEN ? AND ?";
    if (kind == "periodic" || kind == "activity") sql += " AND kind = '" + kind + "'";   // kind viene de una lista cerrada
    sql += " ORDER BY ts DESC LIMIT ?";
    QSqlQuery q(m_db);
    q.prepare(sql);
    q.addBindValue(m_userId); q.addBindValue(fromMs); q.addBindValue(toMs); q.addBindValue(limit);
    q.exec();
    while (q.next())
        list << QVariantMap{{"ts", q.value(0)}, {"hr", q.value(1)}, {"rr", q.value(2)},
                            {"temp", q.value(3)}, {"activity", q.value(4)}, {"kind", q.value(5)}};
    return list;
}

QVariantList DatabaseManager::series(qint64 fromMs, qint64 toMs, const QString &field, int maxPoints)
{
    // 'field' solo puede ser una de estas palabras (así nadie puede "colar" SQL).
    static const QStringList ok = {"hr", "rr", "temp", "activity"};
    if (!ok.contains(field)) return {};
    QSqlQuery q(m_db);
    q.prepare("SELECT ts," + field + " FROM measurements WHERE user_id=? AND kind='periodic' AND ts BETWEEN ? AND ? ORDER BY ts");
    q.addBindValue(m_userId); q.addBindValue(fromMs); q.addBindValue(toMs);
    q.exec();
    QList<QPair<qint64, double>> raw;
    while (q.next()) raw.append({q.value(0).toLongLong(), q.value(1).toDouble()});

    // Resumir: si hay demasiados puntos, se agrupan y se hace la media (RF-16).
    const int step = qMax(1, int(qCeil(double(raw.size()) / maxPoints)));
    QVariantList out;
    qint64 lastT = 0;
    const qint64 gap = 120000;                  // más de 2 minutos sin datos = hueco (RF-27)
    for (int i = 0; i < raw.size(); i += step) {
        double sum = 0; int n = 0;
        for (int j = i; j < qMin(i + step, int(raw.size())); ++j) { sum += raw[j].second; ++n; }
        const qint64 t = raw[i].first;
        if (lastT && t - lastT > gap * step)
            out << QVariantMap{{"t", lastT + 1}, {"v", QVariant()}};  // v vacío = "aquí no hay medición"
        out << QVariantMap{{"t", t}, {"v", sum / n}};
        lastT = t;
    }
    return out;
}

QVariantList DatabaseManager::activitySeries(qint64 activityId, const QString &field)
{   // Puntos (1 por segundo) de una actividad concreta, para dibujar su gráfica (RF-32)
    static const QStringList ok = {"hr", "rr", "temp", "activity"};
    if (!ok.contains(field)) return {};
    QSqlQuery q(m_db);
    q.prepare("SELECT ts," + field + " FROM measurements WHERE activity_id=? ORDER BY ts");
    q.addBindValue(activityId);
    q.exec();
    QVariantList out;
    while (q.next()) out << QVariantMap{{"t", q.value(0)}, {"v", q.value(1)}};
    return out;
}

QVariantMap DatabaseManager::stats(qint64 fromMs, qint64 toMs)
{
    QSqlQuery q(m_db);
    q.prepare("SELECT COUNT(*),AVG(hr),MIN(hr),MAX(hr),AVG(rr),MIN(rr),MAX(rr),AVG(temp),MIN(temp),MAX(temp) "
              "FROM measurements WHERE user_id=? AND ts BETWEEN ? AND ?");
    q.addBindValue(m_userId); q.addBindValue(fromMs); q.addBindValue(toMs);
    q.exec();
    QVariantMap m;
    if (q.next()) m = {{"count", q.value(0)}, {"hrAvg", q.value(1)}, {"hrMin", q.value(2)}, {"hrMax", q.value(3)},
                       {"rrAvg", q.value(4)}, {"rrMin", q.value(5)}, {"rrMax", q.value(6)},
                       {"tAvg", q.value(7)}, {"tMin", q.value(8)}, {"tMax", q.value(9)}};
    return m;
}

QVariantList DatabaseManager::activityDistribution(qint64 fromMs, qint64 toMs)
{   // Cuántas mediciones hubo en reposo / media / intensa (para el gráfico de barras)
    QVariantList out;
    for (int level = 0; level < 3; ++level) {
        QSqlQuery q(m_db);
        q.prepare("SELECT COUNT(*) FROM measurements WHERE user_id=? AND ts BETWEEN ? AND ? AND activity=?");
        q.addBindValue(m_userId); q.addBindValue(fromMs); q.addBindValue(toMs); q.addBindValue(level);
        q.exec();
        out << (q.next() ? q.value(0).toInt() : 0);
    }
    return out;
}

QStringList DatabaseManager::observations(qint64 fromMs, qint64 toMs)
{   // Reglas sencillas y orientativas (RF-23, 25). Distinguen reposo de ejercicio.
    QStringList out;
    auto avg = [&](const QString &col, int act) {
        QSqlQuery q(m_db);
        q.prepare("SELECT AVG(" + col + "),COUNT(*) FROM measurements WHERE user_id=? AND ts BETWEEN ? AND ? AND activity" + (act == 0 ? "=0" : ">=1"));
        q.addBindValue(m_userId); q.addBindValue(fromMs); q.addBindValue(toMs);
        q.exec();
        return q.next() && q.value(1).toInt() >= 5 ? q.value(0).toDouble() : -1.0;
    };
    const double hrRest = avg("hr", 0), hrAct = avg("hr", 1), temp = avg("temp", 0), rrRest = avg("rr", 0);
    if (hrRest > 0) out << QString("REST_HR:%1").arg(hrRest, 0, 'f', 0);
    if (hrRest > 100) out << "HIGH_REST_HR";
    if (hrRest > 0 && hrRest < 50) out << "LOW_REST_HR";
    if (hrAct > 0)  out << QString("ACT_HR:%1").arg(hrAct, 0, 'f', 0);
    if (rrRest > 20) out << "HIGH_REST_RR";
    if (temp > 37.8) out << "HIGH_TEMP";
    if (out.isEmpty()) out << "NO_DATA";
    return out;   // La pantalla traduce estos códigos al idioma elegido.
}

// ---------------------------------------------------------------------------
//  Sincronización: se crea un archivo JSON con lo pendiente. La app de PC
//  (que no forma parte de este proyecto) leerá este formato.
// ---------------------------------------------------------------------------
QString DatabaseManager::exportPending()
{
    QJsonArray arr;
    QSqlQuery q(m_db);
    q.prepare("SELECT uuid,ts,hr,rr,temp,activity,kind,activity_id FROM measurements WHERE user_id=? AND synced=0 ORDER BY ts");
    q.addBindValue(m_userId);
    q.exec();
    while (q.next())
        arr << QJsonObject{{"uuid", q.value(0).toString()}, {"ts", q.value(1).toLongLong()}, {"hr", q.value(2).toDouble()},
                           {"rr", q.value(3).toDouble()}, {"temp", q.value(4).toDouble()}, {"activity", q.value(5).toInt()},
                           {"kind", q.value(6).toString()}, {"activityId", q.value(7).toLongLong()}};
    QJsonObject root{{"version", 1}, {"user", m_displayName}, {"exportedAt", nowMs()}, {"measurements", arr}};
    const QString dir = QStandardPaths::writableLocation(QStandardPaths::AppDataLocation) + "/exports";
    QDir().mkpath(dir);
    const QString path = dir + "/sync_" + QDateTime::currentDateTime().toString("yyyyMMdd_HHmmss") + ".json";
    QFile f(path);
    if (!f.open(QIODevice::WriteOnly)) return QString();
    f.write(QJsonDocument(root).toJson(QJsonDocument::Compact));
    return path;
}

void DatabaseManager::markSynced()
{
    exec("UPDATE measurements SET synced=1 WHERE user_id=? AND synced=0", {m_userId});
    m_lastSync = nowMs();
    QSettings().setValue("lastSync", m_lastSync);
    emit dataChanged();
}

int DatabaseManager::pendingCount() const
{
    QSqlQuery q(m_db);
    q.prepare("SELECT COUNT(*) FROM measurements WHERE user_id=? AND synced=0");
    q.addBindValue(m_userId);
    return q.exec() && q.next() ? q.value(0).toInt() : 0;
}

// ---------------------------------------------------------------------------
//  Borrado y política de conservación (RF-38, 40, 44, 46)
// ---------------------------------------------------------------------------
void DatabaseManager::deleteMeasurements()
{   // Borra solo el historial periódico; las actividades guardadas se conservan.
    exec("DELETE FROM measurements WHERE user_id=? AND kind='periodic'", {m_userId});
    emit dataChanged();
}

void DatabaseManager::deleteEverything()
{
    exec("DELETE FROM measurements WHERE user_id=?", {m_userId});
    exec("DELETE FROM activities WHERE user_id=?", {m_userId});
    emit dataChanged();
}

void DatabaseManager::purgeOld(int days)
{   // Mediciones periódicas con más de 'days' días: fuera. Las de actividad no se tocan.
    exec("DELETE FROM measurements WHERE user_id=? AND kind='periodic' AND ts < ?",
         {m_userId, nowMs() - qint64(days) * 86400000LL});
}
