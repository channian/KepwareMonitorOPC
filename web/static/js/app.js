// Kepware Monitor Web UI - Shared JS

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
