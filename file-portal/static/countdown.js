document.querySelectorAll('.countdown').forEach(el => {
  const expires = parseInt(el.dataset.expires, 10) * 1000;
  const tick = () => {
    const ms = expires - Date.now();
    if (ms <= 0) {
      el.textContent = 'expired';
      el.classList.add('expired');
      const btn = document.getElementById('download-btn');
      if (btn) { btn.classList.add('disabled'); btn.removeAttribute('href'); }
      return;
    }
    const s = Math.floor(ms / 1000);
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
    el.textContent = (h ? h + 'h ' : '') + m + 'm ' + String(sec).padStart(2, '0') + 's left';
    setTimeout(tick, 1000);
  };
  tick();
});
