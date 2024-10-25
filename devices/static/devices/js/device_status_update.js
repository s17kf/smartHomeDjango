function updateDevice(deviceId, newState) {
    $('#device_status_show_' + deviceId).hide();
    $('#device_status_loading_' + deviceId).show();
    oldState = newState === 'on' ? 'off' : 'on';
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
            alert('AJAX request failed: ' + error);
        }
    });
}
