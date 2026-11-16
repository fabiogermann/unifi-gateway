<?php

namespace OPNsense\UnifiGateway\Api;

use OPNsense\Base\ApiMutableModelControllerBase;
use OPNsense\Core\Backend;

class SettingsController extends ApiMutableModelControllerBase
{
    protected static $internalModelName = 'unifigateway';
    protected static $internalModelClass = 'OPNsense\UnifiGateway\UnifiGateway';

    /**
     * Persist settings first, then regenerate the daemon configuration from
     * the saved model. Restart the (lightweight, single-process) daemon when
     * the plugin is enabled so changes take effect immediately.
     */
    public function setAction()
    {
        $result = parent::setAction();
        if (isset($result['result']) && $result['result'] === 'saved') {
            $backend = new Backend();
            $backend->configdRun('unifigateway generate-config');
            $mdl = new \OPNsense\UnifiGateway\UnifiGateway();
            if ((string)$mdl->general->enabled === '1') {
                $backend->configdRun('unifigateway restart');
            }
        }
        return $result;
    }
}
