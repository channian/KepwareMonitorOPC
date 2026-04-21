// Kepware Monitor Web UI — Shared JS

function openModal(id) {
    var el = document.getElementById(id);
    if (el) el.classList.add('show');
}
function closeModal(id) {
    var el = document.getElementById(id);
    if (el) el.classList.remove('show');
}

function toggleAvatarMenu() {
    var menu = document.getElementById('avatarMenu');
    if (menu) menu.classList.toggle('show');
}
document.addEventListener('click', function(e) {
    var btn = document.getElementById('avatarBtn');
    var menu = document.getElementById('avatarMenu');
    if (menu && btn && !btn.contains(e.target)) {
        menu.classList.remove('show');
    }
});

function changePassword() {
    var oldPw = document.getElementById('oldPassword').value;
    var newPw = document.getElementById('newPassword').value;
    var confirmPw = document.getElementById('confirmPassword').value;
    var alertEl = document.getElementById('changePwAlert');

    if (!oldPw || !newPw) {
        showInlineAlert(alertEl, 'err', '請填寫所有欄位');
        return;
    }
    if (newPw !== confirmPw) {
        showInlineAlert(alertEl, 'err', '新密碼與確認密碼不一致');
        return;
    }

    fetch('/api/change-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ old_password: oldPw, new_password: newPw }),
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.ok) {
            showInlineAlert(alertEl, 'ok', '密碼修改成功');
            setTimeout(function() {
                closeModal('changePwModal');
                document.getElementById('oldPassword').value = '';
                document.getElementById('newPassword').value = '';
                document.getElementById('confirmPassword').value = '';
                alertEl.classList.remove('show');
            }, 1500);
        } else {
            showInlineAlert(alertEl, 'err', data.error || '修改失敗');
        }
    })
    .catch(function(err) {
        showInlineAlert(alertEl, 'err', '請求失敗: ' + err);
    });
}

function showInlineAlert(el, type, msg) {
    el.className = 'alert-banner a-' + type + ' show';
    el.textContent = msg;
}

function showPageAlert(id, type, msg) {
    var el = document.getElementById(id);
    if (!el) return;
    el.className = 'alert-banner a-' + type + ' show';
    el.textContent = msg;
    if (type !== 'warn') {
        setTimeout(function() { el.classList.remove('show'); }, 3000);
    }
}

function escapeHtml(text) {
    var div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML.replace(/"/g, '&quot;');
}

function reinitIcons() {
    if (typeof lucide !== 'undefined') lucide.createIcons();
}
