// Mounts a Razorpay Payment Button into every [data-pay] element.
// If no button id is configured yet, falls back to an email order link so the page never breaks.
(function () {
  var cfg = window.CT_CONFIG || {};
  document.querySelectorAll('[data-pay]').forEach(function (mount) {
    var product = mount.getAttribute('data-pay');
    var id = cfg[product + '_button_id'];
    if (id) {
      var form = document.createElement('form');
      var s = document.createElement('script');
      s.src = 'https://checkout.razorpay.com/v1/payment-button.js';
      s.setAttribute('data-payment_button_id', id);
      s.async = true;
      form.appendChild(s);
      mount.appendChild(form);
    } else {
      var label = mount.getAttribute('data-label') || 'Order now';
      var subject = encodeURIComponent('Order: ' + (product === 'ai' ? 'AI bill fix pack' : 'AWS fix pack') + ' ($299)');
      var a = document.createElement('a');
      a.className = 'btn';
      a.href = 'mailto:' + (cfg.contact_email || 'abhijeet@cloudthrift.io') + '?subject=' + subject;
      a.textContent = label;
      mount.appendChild(a);
    }
  });
})();
