<?php
// Environment-only configuration: secrets are not baked into the image.
unset($CFG);
global $CFG;
$CFG = new stdClass();
$CFG->dbtype = 'pgsql';
$CFG->dblibrary = 'native';
$CFG->dbhost = getenv('MOODLE_DB_HOST') ?: 'db';
$CFG->dbname = getenv('MOODLE_DB_NAME') ?: 'moodle';
$CFG->dbuser = getenv('MOODLE_DB_USER') ?: 'moodle';
$CFG->dbpass = getenv('MOODLE_DB_PASSWORD');
$CFG->prefix = 'mdl_';
$CFG->dboptions = ['dbpersist' => false, 'dbport' => 5432, 'dbsocket' => ''];
$CFG->wwwroot = rtrim(getenv('MOODLE_WWWROOT'), '/');
$CFG->dataroot = '/var/moodledata';
$CFG->cachedir = '/var/moodlecache/cache';
$CFG->localcachedir = '/var/moodlecache/localcache';
$CFG->tempdir = '/var/moodlecache/temp';
$CFG->backuptempdir = '/var/moodlecache/backuptemp';
$CFG->session_handler_class = '\core\session\file';
$CFG->session_file_save_path = '/var/moodlecache/sessions';
$CFG->directorypermissions = 02770;
$CFG->admin = 'admin';
$CFG->timezone = getenv('TZ') ?: 'Asia/Dubai';
$CFG->disableupdateautodeploy = true;
$CFG->upgradekey = getenv('MOODLE_DB_PASSWORD');
require_once(__DIR__ . '/lib/setup.php');
