(function () {
    "use strict";

    var messagesEl = document.getElementById("messages");
    var inputEl = document.getElementById("chat-input");
    var pendingFile = null;
    var waNumberForOtp = "";
    var lastOtpReply = "";
    var resendTimerId = null;
    var resendSecondsLeft = 0;

    function scrollToBottom() {
        messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    // Fallback tambahan untuk browser yang belum kenal meta
    // "interactive-widget=resizes-content" (mis. Samsung Internet, Chrome
    // Android versi lama) - visualViewport API sudah didukung jauh lebih
    // luas dan tetap melaporkan tinggi layar yang SUNGGUHAN terlihat saat
    // keyboard on-screen terbuka, walau layout viewport (dan CSS dvh) itu
    // sendiri tidak ikut menyusut di browser tsb. --app-vh dipakai sebagai
    // prioritas utama lewat CSS var(--app-vh, 100dvh) - kalau API ini tidak
    // didukung sama sekali, otomatis jatuh ke 100dvh seperti sebelumnya.
    function syncVisualViewportHeight() {
        if (!window.visualViewport) return;
        document.documentElement.style.setProperty("--app-vh", window.visualViewport.height + "px");
    }
    if (window.visualViewport) {
        syncVisualViewportHeight();
        window.visualViewport.addEventListener("resize", syncVisualViewportHeight);
    }

    function nowTime() {
        var d = new Date();
        return String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
    }

    function escapeHtml(s) {
        var div = document.createElement("div");
        div.textContent = s;
        return div.innerHTML;
    }

    function addMessage(sender, text) {
        var row = document.createElement("div");
        var isUser = sender === "user";
        row.className = "flex gap-3 max-w-[85%] msg-enter" + (isUser ? " self-end flex-row-reverse" : "");

        var avatarClass = isUser
            ? "w-8 h-8 rounded-full bg-slate-100 border border-slate-200 text-slate-500 flex items-center justify-center text-[13px] font-bold shrink-0 mt-1"
            : "w-8 h-8 rounded-full bg-gradient-to-tr from-amal-700 to-amal-500 text-white flex items-center justify-center text-[13px] shrink-0 mt-1 shadow-sm font-bold";
        var bubbleClass = isUser
            ? "px-4 py-3 rounded-2xl rounded-tr-sm bg-gradient-to-tr from-amal-700 to-amal-600 text-white text-[14px] leading-relaxed whitespace-pre-wrap shadow-sm"
            : "px-4 py-3 rounded-2xl rounded-tl-sm bg-white border border-amal-100 shadow-sm text-slate-700 text-[14px] leading-relaxed whitespace-pre-wrap";
        var timeClass = "text-[11px] text-slate-400 mt-1.5" + (isUser ? " text-right mr-1" : " ml-1");

        row.innerHTML =
            '<div class="' + avatarClass + '">' + (isUser ? "K" : "M") + "</div>" +
            '<div><div class="' + bubbleClass + '">' + escapeHtml(text) + "</div>" +
            '<div class="' + timeClass + '">' + nowTime() + "</div></div>";
        messagesEl.appendChild(row);
        scrollToBottom();
    }

    function showTyping() {
        var row = document.createElement("div");
        row.className = "flex gap-3 max-w-[85%] msg-enter";
        row.id = "typing-row";
        row.innerHTML =
            '<div class="w-8 h-8 rounded-full bg-gradient-to-tr from-amal-700 to-amal-500 text-white flex items-center justify-center text-[13px] font-bold shrink-0 mt-1 shadow-sm">M</div>' +
            '<div class="flex gap-1 px-4 py-3.5 bg-white border border-amal-100 rounded-2xl rounded-tl-sm shadow-sm">' +
            '<span class="w-1.5 h-1.5 rounded-full bg-amal-300 animate-bounce" style="animation-delay:0ms"></span>' +
            '<span class="w-1.5 h-1.5 rounded-full bg-amal-300 animate-bounce" style="animation-delay:150ms"></span>' +
            '<span class="w-1.5 h-1.5 rounded-full bg-amal-300 animate-bounce" style="animation-delay:300ms"></span>' +
            "</div>";
        messagesEl.appendChild(row);
        scrollToBottom();
    }

    function hideTyping() {
        var el = document.getElementById("typing-row");
        if (el) el.remove();
    }

    async function sendMessage() {
        var text = inputEl.value.trim();
        if (!text && !pendingFile) return;

        if (pendingFile) {
            await sendResiUpload(text);
            return;
        }

        addMessage("user", text);
        inputEl.value = "";
        autoExpand(inputEl);
        showTyping();

        try {
            var res = await fetch("/api/web-chat", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ message: text }),
            });
            var data = await res.json();
            hideTyping();
            addMessage("bot", data.reply);
            if (data.requires_otp) {
                openOtpModal();
            }
        } catch (err) {
            hideTyping();
            addMessage("bot", "Maaf, Mimin sedang gangguan koneksi. Coba lagi sebentar ya 🙏");
        }
    }

    async function sendResiUpload(caption) {
        if (!waNumberForOtp) {
            var input = prompt("Boleh Mimin tahu nomor WhatsApp Bapak/Ibu, untuk konfirmasi donasinya?");
            if (!input) return;
            waNumberForOtp = input.trim();
            localStorage.setItem("ra_wa_number", waNumberForOtp);
        }

        addMessage("user", (caption || "(mengirim bukti transfer)") + "\n📷 " + pendingFile.name);
        inputEl.value = "";
        autoExpand(inputEl);
        var fileToSend = pendingFile;
        clearResi();
        showTyping();

        var form = new FormData();
        form.append("file", fileToSend);
        form.append("wa_number", waNumberForOtp);
        form.append("caption", caption || "");

        try {
            var res = await fetch("/api/web-chat/upload-resi", { method: "POST", body: form });
            var data = await res.json();
            hideTyping();
            addMessage("bot", data.reply);
        } catch (err) {
            hideTyping();
            addMessage("bot", "Maaf, gagal mengunggah bukti transfernya. Coba lagi ya 🙏");
        }
    }

    function quickPrompt(text) {
        inputEl.value = text;
        autoExpand(inputEl);
        sendMessage();
    }

    function openGoogleSearch(query) {
        addMessage("bot", "Membuka pencarian \"" + query + "\" di tab baru ↗️");
        window.open("https://www.google.com/search?q=" + encodeURIComponent(query), "_blank", "noopener");
    }

    function openExternalLink(url, label) {
        addMessage("bot", "Membuka " + label + " di tab baru ↗️");
        window.open(url, "_blank", "noopener");
    }

    function handleKeydown(e) {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    }

    function autoExpand(el) {
        el.style.height = "auto";
        el.style.height = Math.min(el.scrollHeight, 120) + "px";
    }

    function triggerUpload() {
        document.getElementById("file-input").click();
    }

    function onFileChosen(e) {
        var file = e.target.files[0];
        if (!file) return;
        pendingFile = file;
        document.getElementById("resi-name").textContent = file.name;
        var chip = document.getElementById("resi-chip");
        chip.classList.remove("hidden");
        chip.classList.add("flex");
        inputEl.focus();
    }

    function clearResi() {
        pendingFile = null;
        var chip = document.getElementById("resi-chip");
        chip.classList.add("hidden");
        chip.classList.remove("flex");
        document.getElementById("file-input").value = "";
    }

    // ---------- Mobile sidebar drawer ----------
    function openSidebar() {
        var sidebar = document.getElementById("sidebar");
        sidebar.classList.remove("-translate-x-full");
        sidebar.classList.add("translate-x-0");
    }

    function closeSidebar() {
        var sidebar = document.getElementById("sidebar");
        sidebar.classList.add("-translate-x-full");
        sidebar.classList.remove("translate-x-0");
    }

    // ---------- OTP modal (3 langkah: nomor -> kode -> sukses) ----------
    function showOtpStep(step) {
        document.getElementById("otp-step-phone").classList.toggle("hidden", step !== "phone");
        document.getElementById("otp-step-code").classList.toggle("hidden", step !== "code");
        document.getElementById("otp-step-success").classList.toggle("hidden", step !== "success");
    }

    function openOtpModal() {
        hideOtpErrors();
        showOtpStep("phone");
        var saved = localStorage.getItem("ra_wa_number");
        if (saved) document.getElementById("otp-phone").value = saved.replace(/^62/, "");
        var modal = document.getElementById("otp-modal");
        modal.classList.remove("hidden");
        modal.classList.add("flex");
        requestAnimationFrame(function () {
            modal.classList.remove("opacity-0");
            document.getElementById("otp-card").classList.remove("scale-95");
        });
    }

    function closeOtpModal() {
        var modal = document.getElementById("otp-modal");
        modal.classList.add("opacity-0");
        document.getElementById("otp-card").classList.add("scale-95");
        stopResendTimer();
        setTimeout(function () {
            modal.classList.add("hidden");
            modal.classList.remove("flex");
        }, 300);
    }

    function hideOtpErrors() {
        document.getElementById("otp-error-phone").classList.add("hidden");
        document.getElementById("otp-error-code").classList.add("hidden");
    }

    function showOtpErrorPhone(msg) {
        var el = document.getElementById("otp-error-phone");
        el.textContent = msg;
        el.classList.remove("hidden");
    }

    function showOtpErrorCode(msg) {
        var el = document.getElementById("otp-error-code");
        el.textContent = msg;
        el.classList.remove("hidden");
    }

    function normalizePhone(raw) {
        var digits = raw.trim().replace(/[^0-9]/g, "");
        if (digits.startsWith("0")) digits = "62" + digits.slice(1);
        else if (!digits.startsWith("62")) digits = "62" + digits;
        return digits;
    }

    async function submitPhone() {
        var raw = document.getElementById("otp-phone").value.trim();
        hideOtpErrors();
        if (!raw) {
            showOtpErrorPhone("Nomor WhatsApp belum diisi.");
            return;
        }
        var number = normalizePhone(raw);
        var btn = document.getElementById("btn-submit-phone");
        btn.disabled = true;

        try {
            var res = await fetch("/api/web-otp/request", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ wa_number: number }),
            });
            var data = await res.json();
            btn.disabled = false;
            if (data.status !== "sukses") {
                showOtpErrorPhone(data.pesan || "Gagal mengirim kode OTP.");
                return;
            }
            waNumberForOtp = number;
            localStorage.setItem("ra_wa_number", number);
            document.getElementById("otp-phone-display").textContent = "+" + number;
            clearOtpDigits();
            showOtpStep("code");
            startResendTimer();
            focusFirstOtpDigit();
        } catch (err) {
            btn.disabled = false;
            showOtpErrorPhone("Gagal menghubungi server. Coba lagi ya.");
        }
    }

    function getOtpDigitInputs() {
        return Array.prototype.slice.call(document.querySelectorAll(".otp-digit"));
    }

    function clearOtpDigits() {
        getOtpDigitInputs().forEach(function (el) { el.value = ""; });
    }

    function focusFirstOtpDigit() {
        var inputs = getOtpDigitInputs();
        if (inputs[0]) inputs[0].focus();
    }

    function readOtpCode() {
        return getOtpDigitInputs().map(function (el) { return el.value; }).join("");
    }

    function setupOtpDigitInputs() {
        var inputs = getOtpDigitInputs();
        inputs.forEach(function (el, idx) {
            el.addEventListener("input", function () {
                el.value = el.value.replace(/[^0-9]/g, "").slice(0, 1);
                if (el.value && idx < inputs.length - 1) {
                    inputs[idx + 1].focus();
                }
                if (readOtpCode().length === inputs.length) {
                    submitOtp();
                }
            });
            el.addEventListener("keydown", function (e) {
                if (e.key === "Backspace" && !el.value && idx > 0) {
                    inputs[idx - 1].focus();
                }
            });
            el.addEventListener("paste", function (e) {
                e.preventDefault();
                var text = (e.clipboardData || window.clipboardData).getData("text").replace(/[^0-9]/g, "");
                if (!text) return;
                for (var i = 0; i < inputs.length; i++) {
                    inputs[i].value = text[i] || "";
                }
                var lastFilled = Math.min(text.length, inputs.length) - 1;
                if (lastFilled >= 0) inputs[lastFilled].focus();
                if (readOtpCode().length === inputs.length) {
                    submitOtp();
                }
            });
        });
    }

    async function submitOtp() {
        var code = readOtpCode();
        hideOtpErrors();
        if (code.length !== 6) {
            showOtpErrorCode("Masukkan 6 digit kode OTP.");
            return;
        }
        var btn = document.getElementById("btn-submit-otp");
        btn.disabled = true;

        try {
            var res = await fetch("/api/web-otp/verify", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ wa_number: waNumberForOtp, otp_code: code }),
            });
            var data = await res.json();
            btn.disabled = false;
            if (data.status !== "sukses") {
                showOtpErrorCode(data.pesan || "Kode OTP salah.");
                clearOtpDigits();
                focusFirstOtpDigit();
                return;
            }
            lastOtpReply = data.reply || "";
            stopResendTimer();
            showOtpStep("success");
        } catch (err) {
            btn.disabled = false;
            showOtpErrorCode("Gagal menghubungi server. Coba lagi ya.");
        }
    }

    async function resendOtp() {
        if (resendSecondsLeft > 0) return;
        hideOtpErrors();
        try {
            var res = await fetch("/api/web-otp/request", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ wa_number: waNumberForOtp }),
            });
            var data = await res.json();
            if (data.status !== "sukses") {
                showOtpErrorCode(data.pesan || "Gagal mengirim ulang kode.");
                return;
            }
            clearOtpDigits();
            focusFirstOtpDigit();
            startResendTimer();
        } catch (err) {
            showOtpErrorCode("Gagal menghubungi server. Coba lagi ya.");
        }
    }

    function startResendTimer() {
        stopResendTimer();
        resendSecondsLeft = 60;
        var btn = document.getElementById("otp-resend");
        var timerEl = document.getElementById("otp-timer");
        btn.disabled = true;
        timerEl.textContent = resendSecondsLeft;
        resendTimerId = setInterval(function () {
            resendSecondsLeft -= 1;
            if (resendSecondsLeft <= 0) {
                stopResendTimer();
                btn.textContent = "Kirim ulang kode";
                btn.disabled = false;
                return;
            }
            timerEl.textContent = resendSecondsLeft;
        }, 1000);
    }

    function stopResendTimer() {
        if (resendTimerId) {
            clearInterval(resendTimerId);
            resendTimerId = null;
        }
        var btn = document.getElementById("otp-resend");
        if (btn && resendSecondsLeft > 0) {
            btn.disabled = false;
        }
    }

    function finishOtp() {
        closeOtpModal();
        if (lastOtpReply) {
            addMessage("bot", lastOtpReply);
        }
    }

    document.getElementById("otp-modal").addEventListener("click", function (e) {
        if (e.target === this) closeOtpModal();
    });

    setupOtpDigitInputs();

    // expose handlers used by inline onclick/onkeydown attributes in chat.html
    window.sendMessage = sendMessage;
    window.quickPrompt = quickPrompt;
    window.openGoogleSearch = openGoogleSearch;
    window.openExternalLink = openExternalLink;
    window.handleKeydown = handleKeydown;
    window.autoExpand = autoExpand;
    window.triggerUpload = triggerUpload;
    window.onFileChosen = onFileChosen;
    window.clearResi = clearResi;
    window.openSidebar = openSidebar;
    window.closeSidebar = closeSidebar;
    window.closeOtpModal = closeOtpModal;
    window.submitPhone = submitPhone;
    window.submitOtp = submitOtp;
    window.resendOtp = resendOtp;
    window.finishOtp = finishOtp;
})();
