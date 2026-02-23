// Kepware Monitor Web UI - Shared JS

/**
 * 深/淺色模式切換
 */
(function () {
    const saved = localStorage.getItem('theme') || 'light';
    document.documentElement.setAttribute('data-bs-theme', saved);
    document.addEventListener('DOMContentLoaded', () => {
        const icon = document.getElementById('themeIcon');
        if (icon) icon.className = saved === 'dark' ? 'bi bi-sun-fill' : 'bi bi-moon-fill';
    });
})();

function toggleTheme() {
    const current = document.documentElement.getAttribute('data-bs-theme');
    const next = current === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-bs-theme', next);
    localStorage.setItem('theme', next);
    const icon = document.getElementById('themeIcon');
    if (icon) icon.className = next === 'dark' ? 'bi bi-sun-fill' : 'bi bi-moon-fill';
}

/**
 * 修改密碼（base.html 的 modal 使用）
 */
function changePassword() {
    const oldPw = document.getElementById('oldPassword').value;
    const newPw = document.getElementById('newPassword').value;
    const confirmPw = document.getElementById('confirmPassword').value;
    const alert = document.getElementById('changePwAlert');

    if (!oldPw || !newPw) {
        alert.className = 'alert alert-danger';
        alert.textContent = '請填寫所有欄位';
        alert.classList.remove('d-none');
        return;
    }

    if (newPw !== confirmPw) {
        alert.className = 'alert alert-danger';
        alert.textContent = '新密碼與確認密碼不一致';
        alert.classList.remove('d-none');
        return;
    }

    fetch('/api/change-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ old_password: oldPw, new_password: newPw }),
    })
    .then(r => r.json())
    .then(data => {
        if (data.ok) {
            alert.className = 'alert alert-success';
            alert.textContent = '密碼修改成功';
            alert.classList.remove('d-none');
            setTimeout(() => {
                bootstrap.Modal.getInstance(document.getElementById('changePwModal')).hide();
                document.getElementById('oldPassword').value = '';
                document.getElementById('newPassword').value = '';
                document.getElementById('confirmPassword').value = '';
                alert.classList.add('d-none');
            }, 1500);
        } else {
            alert.className = 'alert alert-danger';
            alert.textContent = data.error || '修改失敗';
            alert.classList.remove('d-none');
        }
    })
    .catch(err => {
        alert.className = 'alert alert-danger';
        alert.textContent = '請求失敗: ' + err;
        alert.classList.remove('d-none');
    });
}
