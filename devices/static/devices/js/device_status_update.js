function updateDevice(deviceId, newState) {
    $('#device_status_show_' + deviceId).hide();
    $('#device_status_loading_' + deviceId).show();
    const oldState = newState === 'on' ? 'off' : 'on';
    $.ajax({
        // RELAY_UPDATE_URL variable has to be defined in the template
        url: RELAY_UPDATE_URL.replace('0', deviceId),
        type: 'POST',
        data: {
            'state': newState,
            // CSRF_TOKEN variable has to be defined in the template
            'csrfmiddlewaretoken': CSRF_TOKEN
        },
        success: function (response) {
            // Bez ważnej sesji widok przekierowuje na stronę logowania – zamiast
            // JSON przychodzi HTML. Przeładowanie strony prowadzi do logowania.
            if (typeof response !== 'object') {
                window.location.reload();
                return;
            }
            if (response.status === 'success') {
                $('#device_status_show_' + deviceId).show();
                $('#device_status_loading_' + deviceId).hide();
            } else {
                $('#device_status_show_' + deviceId).show();
                $('#device_status_loading_' + deviceId).hide();
                $('#radio_' + deviceId + '_' + oldState).prop('checked', true);
                alert('Error: ' + response.message);
            }
        },
        error: function (xhr, status, error) {
            $('#device_status_show_' + deviceId).show();
            $('#device_status_loading_' + deviceId).hide();
            $('#radio_' + deviceId + '_' + oldState).prop('checked', true);
            alert('AJAX request failed: ' + error);
        }
    });
}
