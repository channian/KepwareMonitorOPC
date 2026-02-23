// Kepware Monitor Web UI - Shared JS

/**
 * 深/淺色模式切換按鈕
 */
(function () {
    function setup() {
        // 初始化圖示
        var theme = document.documentElement.getAttribute('data-bs-theme') || 'light';
        var icon = document.getElementById('themeIcon');
        if (icon) icon.className = theme === 'dark' ? 'bi bi-sun-fill' : 'bi bi-moon-fill';

        // 綁定按鈕
        var btn = document.getElementById('themeToggle');
        if (btn) {
            btn.addEventListener('click', function () {
                var cur = document.documentElement.getAttribute('data-bs-theme') || 'light';
                var next = cur === 'dark' ? 'light' : 'dark';
                document.documentElement.setAttribute('data-bs-theme', next);
                localStorage.setItem('theme', next);
                var ic = document.getElementById('themeIcon');
                if (ic) ic.className = next === 'dark' ? 'bi bi-sun-fill' : 'bi bi-moon-fill';
            });
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', setup);
    } else {
        setup();
    }
})();

/**
 * 修改密碼（base.html 的 modal 使用）
 */
function changePassword() {
    var oldPw = document.getElementById('oldPassword').value;
    var newPw = document.getElementById('newPassword').value;
    var confirmPw = document.getElementById('confirmPassword').value;
    var alertEl = document.getElementById('changePwAlert');

    if (!oldPw || !newPw) {
        alertEl.className = 'alert alert-danger';
        alertEl.textContent = '請填寫所有欄位';
        alertEl.classList.remove('d-none');
        return;
    }

    if (newPw !== confirmPw) {
        alertEl.className = 'alert alert-danger';
        alertEl.textContent = '新密碼與確認密碼不一致';
        alertEl.classList.remove('d-none');
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
            alertEl.className = 'alert alert-success';
            alertEl.textContent = '密碼修改成功';
            alertEl.classList.remove('d-none');
            setTimeout(function() {
                bootstrap.Modal.getInstance(document.getElementById('changePwModal')).hide();
                document.getElementById('oldPassword').value = '';
                document.getElementById('newPassword').value = '';
                document.getElementById('confirmPassword').value = '';
                alertEl.classList.add('d-none');
            }, 1500);
        } else {
            alertEl.className = 'alert alert-danger';
            alertEl.textContent = data.error || '修改失敗';
            alertEl.classList.remove('d-none');
        }
    })
    .catch(function(err) {
        alertEl.className = 'alert alert-danger';
        alertEl.textContent = '請求失敗: ' + err;
        alertEl.classList.remove('d-none');
    });
}
