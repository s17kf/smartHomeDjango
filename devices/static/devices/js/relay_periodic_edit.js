const SHOW_EDIT_BUTTONS_TIMEOUT_SECONDS = 120;

function show_edit_buttons_clicked() {
    if (!window.localStorage) {
        return;
    }
    window.localStorage.setItem("rp_show_edit_buttons_time", (Math.floor(Date.now() / 1000)).toString());
    show_edit_buttons()
}

function hide_edit_buttons() {
    if (!window.localStorage) {
        return;
    }
    window.localStorage.removeItem("rp_show_edit_buttons_time");
    $(".rp_edit_buttons").hide();
    $(".show_rp_edit_buttons").show();
}

function show_edit_buttons_if_needed() {
    if (!window.localStorage || !window.localStorage.getItem("rp_show_edit_buttons_time")) {
        return;
    }
    let show_edit_buttons_time = parseInt(window.localStorage.getItem("rp_show_edit_buttons_time"));
    let current_time = Math.floor(Date.now() / 1000);
    if (current_time - show_edit_buttons_time < SHOW_EDIT_BUTTONS_TIMEOUT_SECONDS) {
        show_edit_buttons();
    } else {
        window.localStorage.removeItem("rp_show_edit_buttons_time");
    }
}

function show_edit_buttons() {
    $(".rp_edit_buttons").show();
    $(".show_rp_edit_buttons").hide();
}
