<?php

namespace OPNsense\UnifiGateway\Api;

use OPNsense\Base\ApiMutableServiceControllerBase;

class ServiceController extends ApiMutableServiceControllerBase
{
    protected static $internalServiceClass = 'OPNsense\UnifiGateway\UnifiGateway';
    protected static $internalServiceEnabled = 'general.enabled';
    protected static $internalServiceName = 'unifigateway';
}
