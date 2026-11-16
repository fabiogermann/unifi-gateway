#!/usr/local/bin/php
<?php
/**
 * Refresh OPNsense's merged menu after package installation/removal.
 * Uses the framework's own cache API rather than assuming its path.
 */
$root = '/usr/local/opnsense/mvc/app';
require_once "$root/config/AppConfig.php";
require_once "$root/library/OPNsense/Autoload/Loader.php";
(new \OPNsense\Autoload\Loader([
    "$root/controllers",
    "$root/models",
    "$root/library",
    "$root/config",
]))->register();
$config = include "$root/config/config.php";
$menu = new \OPNsense\Base\Menu\MenuSystem();
$menu->invalidateCache();
$menu->persist(false);
if ($menu->getItem('Services.UnifiGateway') === null) {
    fwrite(STDERR, "UniFi Gateway menu registration missing\n");
    exit(1);
}
echo "OPNsense menu cache refreshed\n";
