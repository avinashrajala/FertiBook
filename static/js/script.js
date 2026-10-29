// FertiBook - small helper scripts (the server always re-checks everything too)

document.addEventListener("DOMContentLoaded", function () {

  // 1. Mobile menu button
  var toggle = document.getElementById("navToggle");
  var links = document.getElementById("navLinks");
  if (toggle && links) {
    toggle.addEventListener("click", function () {
      var open = links.classList.toggle("open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }

  // 2. Close buttons on flash messages
  document.querySelectorAll(".flash-close").forEach(function (btn) {
    btn.addEventListener("click", function () { btn.parentElement.remove(); });
  });

  // 3. Ask "Are you sure?" before forms that have data-confirm
  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      if (!window.confirm(form.getAttribute("data-confirm"))) { event.preventDefault(); }
    });
  });

  // 4. Booking page: show total price while typing  (Total = Quantity x Price per Bag)
  var qty = document.getElementById("quantity");
  var totalBox = document.getElementById("totalPrice");
  if (qty && totalBox) {
    var price = parseFloat(qty.getAttribute("data-price"));
    var update = function () {
      var q = parseInt(qty.value, 10);
      var total = (isNaN(q) || q < 1) ? 0 : q * price;
      totalBox.textContent = "\u20B9" + total.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    };
    qty.addEventListener("input", update);
    update();
  }

  // 5. Simple form checks before sending (register + booking)
  function markInvalid(field, bad) { field.classList.toggle("invalid", bad); }

  var register = document.getElementById("registerForm");
  if (register) {
    register.addEventListener("submit", function (event) {
      var problems = [];
      var name = document.getElementById("name");
      var email = document.getElementById("email");
      var phone = document.getElementById("phone");
      var pw = document.getElementById("password");
      var confirmPw = document.getElementById("confirm");

      var badName = name.value.trim().length < 2;
      var badEmail = !/^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$/.test(email.value.trim());
      var badPhone = !/^[6-9]\d{9}$/.test(phone.value.trim());
      var badPw = pw.value.length < 6 || !/[A-Za-z]/.test(pw.value) || !/\d/.test(pw.value);
      var badConfirm = pw.value !== confirmPw.value;

      markInvalid(name, badName); markInvalid(email, badEmail); markInvalid(phone, badPhone);
      markInvalid(pw, badPw); markInvalid(confirmPw, badConfirm);

      if (badName) problems.push("Enter your full name.");
      if (badEmail) problems.push("Enter a valid email.");
      if (badPhone) problems.push("Phone must be 10 digits starting with 6-9.");
      if (badPw) problems.push("Password needs 6+ characters, a letter and a number.");
      if (badConfirm) problems.push("Passwords do not match.");
      if (problems.length) { event.preventDefault(); alert(problems.join("\n")); }
    });
  }

  var bookForm = document.getElementById("bookForm");
  if (bookForm) {
    bookForm.addEventListener("submit", function (event) {
      var q = parseInt(qty.value, 10);
      var max = parseInt(qty.getAttribute("max"), 10);
      var address = document.getElementById("address");
      var badQty = isNaN(q) || q < 1 || q > max;
      var badAddr = address.value.trim().length < 10;
      markInvalid(qty, badQty); markInvalid(address, badAddr);
      if (badQty || badAddr) {
        event.preventDefault();
        alert(badQty ? "Enter between 1 and " + max + " bags." : "Enter a full delivery address (at least 10 characters).");
      }
    });
  }
});
