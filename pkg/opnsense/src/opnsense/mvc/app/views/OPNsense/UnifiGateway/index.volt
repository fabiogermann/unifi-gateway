{# UniFi Gateway Emulator — Services → UniFi Gateway #}
{# Tab-based layout following OPNsense design convention #}

<ul class="nav nav-tabs" id="unifigateway-tabs" data-tabs="tabs">
    <li class="active"><a data-toggle="tab" href="#tab-status">{{ lang._('Status') }}</a></li>
    <li><a data-toggle="tab" href="#tab_general">{{ lang._('General Settings') }}</a></li>
    <li><a data-toggle="tab" href="#tab_network">{{ lang._('Port Mapping') }}</a></li>
    <li><a data-toggle="tab" href="#tab_advanced">{{ lang._('Advanced') }}</a></li>
</ul>

<div class="tab-content content-box">

    {# ───────────────── STATUS TAB ───────────────── #}
    <div id="tab-status" class="tab-pane fade in active">
        <table class="table table-striped table-condensed">
            <tbody>
                <tr><th style="width:200px">{{ lang._('Service') }}</th><td id="svc-status">—</td></tr>
                <tr><th>{{ lang._('Adoption') }}</th><td id="adopt-state">—</td></tr>
                <tr><th>{{ lang._('Controller') }}</th><td id="adopt-controller">—</td></tr>
                <tr><th>{{ lang._('Device hostname') }}</th><td id="adopt-hostname">—</td></tr>
            </tbody>
        </table>

        <button id="btn-adopt" class="btn btn-primary" disabled="disabled">
            <span class="fa fa-fw fa-link"></span> {{ lang._('Adopt into controller') }}
        </button>
        <span id="adopt-hint" class="help-block">
            {{ lang._('Starts the adoption handshake. When the device shows as pending in the UniFi controller, click Adopt there — this window completes the exchange automatically.') }}
        </span>
        <pre id="adopt-output" style="display:none; margin-top:10px; max-height:220px; overflow:auto;"></pre>
    </div>

    {# Standard OPNsense forms: help, advanced mode and field validation. #}
    {{ partial("layout_partials/base_tabs_content", ['formData': settingsForm]) }}

</div>

<script>
$(document).ready(function() {
    $('[data-toggle="tooltip"]').tooltip();

    function refreshServiceStatus() {
        ajaxGet('/api/core/service/search', {}, function(data) {
            var status = 'unknown';
            if (data && data.rows) {
                for (var i = 0; i < data.rows.length; i++) {
                    if (data.rows[i].name === 'unifi-gateway') {
                        status = data.rows[i].running == 1 ? 'running' : 'stopped';
                        break;
                    }
                }
            }
            $("#svc-status").text(status);
        });
    }

    function refreshAdoption() {
        ajaxGet('/api/unifigateway/adopt/status', {}, function(data) {
            var adopted = data && data.adopted;
            $("#adopt-state").text(adopted ? 'adopted' : 'not adopted');
            $("#adopt-controller").text(data && data.controller ? data.controller : '—');
            $("#adopt-hostname").text(data && data.hostname ? data.hostname : '—');
            // Button is only armed while the device is NOT enrolled.
            $("#btn-adopt").prop('disabled', !!adopted);
        });
    }

    // Stock OPNsense form hydration and header service controls.
    mapDataToFormUI({
        'frm_general': '/api/unifigateway/settings/get',
        'frm_network': '/api/unifigateway/settings/get',
        'frm_advanced': '/api/unifigateway/settings/get'
    }).done(function() {
        formatTokenizersUI();
        $('.selectpicker').selectpicker('refresh');
        refreshServiceStatus();
        refreshAdoption();
    });
    updateServiceControlUI('unifigateway');

    $('#save_general, #save_network, #save_advanced').click(function() {
        var form = $(this).closest('form');
        saveFormToEndpoint('/api/unifigateway/settings/set', form.attr('id'), function() {
            updateServiceControlUI('unifigateway');
            refreshServiceStatus();
            refreshAdoption();
        });
    });

    $('#btn-adopt').click(function() {
        var btn = $(this);
        btn.prop('disabled', true);
        $("#adopt-output").show().text("Starting adoption handshake...\n");
        ajaxCall('/api/unifigateway/adopt/adopt', {}, function(data) {
            if (data && data.output) {
                $("#adopt-output").text(data.output);
            }
            if (data && data.message) {
                $("#adopt-output").append("\n" + data.message);
            }
            refreshAdoption();
            if (!(data && data.adopted)) {
                btn.prop('disabled', false);
            }
        }, 'POST');
    });
});
</script>
