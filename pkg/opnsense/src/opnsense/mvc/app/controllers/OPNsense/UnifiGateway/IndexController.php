<?php

namespace OPNsense\UnifiGateway;

use OPNsense\Base\IndexController as BaseIndexController;

class IndexController extends BaseIndexController
{
    public function indexAction()
    {
        $this->view->title = gettext('Services: UniFi Gateway');
        $this->view->settingsForm = $this->getForm('settings');
        $this->view->pick('OPNsense/UnifiGateway/index');
    }
}
