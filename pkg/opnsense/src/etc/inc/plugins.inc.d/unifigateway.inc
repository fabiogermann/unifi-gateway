<?php
/**
 * UniFi Gateway Emulator plugin for OPNsense.
 */

function unifigateway_enabled()
{
    global $config;
    return isset($config['OPNsense']['unifigateway']['general']['enabled']) &&
           $config['OPNsense']['unifigateway']['general']['enabled'] == 1;
}

function unifigateway_services()
{
    $services = array();
    if (!unifigateway_enabled()) {
        return $services;
    }
    $services[] = array(
        'description' => gettext('UniFi Gateway Emulator'),
        'configd' => array(
            'restart' => array('unifigateway restart'),
            'start' => array('unifigateway start'),
            'stop' => array('unifigateway stop'),
        ),
        'name' => 'unifi-gateway',
        'pidfile' => '/var/run/unifi-gateway.pid',
    );
    return $services;
}
