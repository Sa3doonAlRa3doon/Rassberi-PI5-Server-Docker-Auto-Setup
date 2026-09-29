<?php
// Supply initial credentials in PHP memory, never in the process command line.
$argv = [
    '/var/www/moodle/admin/cli/install_database.php',
    '--agree-license',
    '--fullname=School and Learning',
    '--shortname=School',
    '--adminuser=' . (getenv('MOODLE_ADMIN_USER') ?: 'saeed'),
    '--adminpass=' . getenv('MOODLE_ADMIN_PASSWORD'),
    '--adminemail=' . (getenv('MOODLE_ADMIN_EMAIL') ?: 'saeed@example.invalid'),
    '--lang=en',
];
$argc = count($argv);
$_SERVER['argv'] = $argv;
$_SERVER['argc'] = $argc;
require '/var/www/moodle/admin/cli/install_database.php';
