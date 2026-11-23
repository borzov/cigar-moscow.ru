(function (Drupal, once) {
  Drupal.behaviors.clubAgeConfirmation = {
    attach(context) {
      once('club-age', '[data-club-age]', context).forEach((dialog) => {
        const key = 'aficionados.age18';
        try {
          if (localStorage.getItem(key) === 'yes') return;
        } catch {
          // The visitor can still confirm if browser storage is unavailable.
        }
        const choices = dialog.querySelector('[data-age-choices]');
        const denied = dialog.querySelector('[data-age-denied]');
        const confirm = dialog.querySelector('[data-age-confirm]');
        const back = dialog.querySelector('[data-age-back]');
        dialog.addEventListener('cancel', (event) => event.preventDefault());
        confirm.addEventListener('click', () => {
          try { localStorage.setItem(key, 'yes'); } catch {}
          dialog.close();
          document.getElementById('main-content').focus();
        });
        dialog.querySelector('[data-age-decline]').addEventListener('click', () => {
          choices.hidden = true;
          denied.hidden = false;
          back.focus();
        });
        back.addEventListener('click', () => {
          denied.hidden = true;
          choices.hidden = false;
          confirm.focus();
        });
        dialog.showModal();
      });
    },
  };
})(Drupal, once);
