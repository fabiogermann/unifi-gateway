<?php

namespace OPNsense\UnifiGateway\Api;

use OPNsense\Base\ApiControllerBase;
use OPNsense\Core\Backend;

/**
 * Adoption (inform/enroll) endpoints. The adopt action refuses to run when
 * the device already holds an authkey — the UI also greys the button out,
 * but the gate is enforced server-side here.
 */
class AdoptController extends ApiControllerBase
{
    public function statusAction()
    {
        $backend = new Backend();
        $out = trim((string)$backend->configdRun('unifigateway adoption-status'));
        $data = json_decode($out, true);
        if (!is_array($data)) {
            return ['adopted' => false, 'error' => $out !== '' ? $out : 'no status'];
        }
        return $data;
    }

    public function adoptAction()
    {
        if (!$this->request->isPost()) {
            return ['status' => 'failed', 'message' => gettext('POST required')];
        }
        $status = $this->statusAction();
        if (!empty($status['adopted'])) {
            return ['status' => 'failed', 'message' => gettext('Device is already adopted')];
        }
        $backend = new Backend();
        $out = trim((string)$backend->configdRun('unifigateway adopt'));
        $after = $this->statusAction();
        return [
            'status' => !empty($after['adopted']) ? 'ok' : 'pending',
            'adopted' => !empty($after['adopted']),
            'output' => $out,
        ];
    }
}
