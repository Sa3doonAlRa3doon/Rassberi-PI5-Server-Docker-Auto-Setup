<?php
ob_start();
require '/usr/local/bin/moodle-db-state.php';
$state = trim(ob_get_clean());
if ($state !== 'ready') {
    fwrite(STDERR, "Moodle schema is not ready.\n");
    exit(1);
}
