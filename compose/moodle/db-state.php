<?php
// Query without loading Moodle, so a partially initialized database is detected.
try {
    $pdo = new PDO(
        'pgsql:host=' . (getenv('MOODLE_DB_HOST') ?: 'db') . ';port=5432;dbname=' . (getenv('MOODLE_DB_NAME') ?: 'moodle'),
        getenv('MOODLE_DB_USER') ?: 'moodle',
        getenv('MOODLE_DB_PASSWORD'),
        [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]
    );
    $tables = (int)$pdo->query("SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")->fetchColumn();
    if ($tables === 0) {
        echo "empty\n";
    } else {
        $dbversion = $pdo->query("SELECT value FROM mdl_config WHERE name='version'")->fetchColumn();
        define('MOODLE_INTERNAL', true);
        require '/var/www/moodle/public/version.php';
        echo ($dbversion !== false && (float)$dbversion === (float)$version) ? "ready\n" : "upgrade-required\n";
    }
} catch (Throwable $e) {
    // Do not include a connection string or password in container logs.
    fwrite(STDERR, "Moodle database query failed. Inspect database health and schema.\n");
    exit(1);
}
