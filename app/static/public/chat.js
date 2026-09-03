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
        // requestAnimationFrame, BUKAN langsung sinkron - balasan panjang
        // (mis. katalog 9 program) butuh waktu untuk browser selesai reflow
        // sebelum scrollHeight yang benar bisa dibaca. Mengukur secara
        // sinkron persis setelah appendChild() bisa membaca nilai basi
        // (reflow belum selesai), memicu reflow kedua yang mendadak di
        // tengah keyboard HP sedang terbuka - salah satu dugaan penyebab
        // keyboard "tenggelam"/tertutup sendiri saat balasan bot kepanjangan
        // (dilaporkan lewat HP asli, 3 Sep 2026).
        requestAnimationFrame(function () {
            messagesEl.scrollTop = messagesEl.scrollHeight;
        });
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

    // Ubah URL/domain polos (mis. "Website Resmi: rumahamal.usk.ac.id", tanpa
    // "https://" sama sekali - begitulah bot menuliskannya di balasan asli)
    // jadi tautan yang bisa ditekan. HARUS dipanggil SETELAH escapeHtml(),
    // bukan sebelumnya - beroperasi di atas teks yang sudah di-escape supaya
    // tetap aman dari XSS. Domain-polos butuh TLD alfabet (bukan cuma digit)
    // supaya angka seperti "Rp1.000.000" tidak ikut kesangkut jadi "link".
    function linkify(escapedHtml) {
        return escapedHtml.replace(
            /(https?:\/\/[^\s<]+)|(?<![\w@])(\b(?:[a-z0-9-]+\.)+[a-z]{2,}(?:\.[a-z]{2,})*\b)/gi,
            function (cocokUtuh, urlPenuh, domainPolos) {
                var url = urlPenuh || domainPolos;
                var trailing = "";
                var potongTrailing = url.match(/[.,;:!?)\]]+$/);
                if (potongTrailing) {
                    trailing = potongTrailing[0];
                    url = url.slice(0, url.length - trailing.length);
                }
                var href = urlPenuh ? url : "https://" + url;
                return '<a href="' + href + '" target="_blank" rel="noopener noreferrer" class="underline">' + url + "</a>" + trailing;
            }
        );
    }

    // Avatar bot Mimin (badan bulat + peci), warnanya ikut tema lewat CSS
    // custom property --bot-body/--bot-body-stroke/--bot-face (lihat chat.html)
    // supaya markup yang sama otomatis benar di mode terang maupun gelap.
    function botAvatarSvg() {
        return (
            '<svg viewBox="0 0 36 36" class="bot-avatar mt-1">' +
            '<path d="M11 9 Q11 2 18 2 Q25 2 25 9 Z" fill="#1A1A1A"/>' +
            '<rect x="10.5" y="7.8" width="15" height="1.4" rx="0.7" fill="#000" opacity="0.35"/>' +
            '<ellipse cx="15" cy="4.5" rx="2.3" ry="1" fill="#3D3D3D" opacity="0.7"/>' +
            '<rect x="5" y="9" width="26" height="22" rx="8" fill="var(--bot-body)" stroke="var(--bot-body-stroke)" stroke-width="1"/>' +
            '<rect x="9" y="13" width="18" height="10" rx="4" fill="var(--bot-face)"/>' +
            '<g class="bot-eyes">' +
            '<circle cx="14" cy="18" r="2" fill="#fff"/>' +
            '<circle cx="22" cy="18" r="2" fill="#fff"/>' +
            '<circle cx="14.6" cy="17.3" r="0.6" fill="#F6C445"/>' +
            '<circle cx="22.6" cy="17.3" r="0.6" fill="#F6C445"/>' +
            "</g></svg>"
        );
    }

    // Avatar user: siluet tamu netral (bukan huruf inisial "K") - identitas
    // pengunjung web belum tentu terverifikasi saat mengirim pesan, jadi
    // avatar generik lebih jujur daripada seolah-olah sudah tahu namanya.
    function guestAvatarSvg() {
        return (
            '<div class="w-8 h-8 rounded-full bg-slate-200 dark:bg-amal-800 flex items-center justify-center shrink-0 mt-1">' +
            '<svg viewBox="0 0 24 24" fill="currentColor" class="w-5 h-5 text-slate-400 dark:text-amal-400">' +
            '<path fill-rule="evenodd" d="M18.685 19.097A9.723 9.723 0 0021.75 12c0-5.385-4.365-9.75-9.75-9.75S2.25 6.615 2.25 12a9.723 9.723 0 003.065 7.097A9.716 9.716 0 0012 21.75a9.716 9.716 0 006.685-2.653zm-12.54-1.285A7.486 7.486 0 0112 15a7.486 7.486 0 015.855 2.812A8.224 8.224 0 0112 20.25a8.224 8.224 0 01-5.855-2.438zM15.75 9a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0z" clip-rule="evenodd"/>' +
            "</svg></div>"
        );
    }

    function addMessage(sender, text) {
        var row = document.createElement("div");
        var isUser = sender === "user";
        row.className = "flex gap-3 max-w-[85%] msg-enter" + (isUser ? " self-end flex-row-reverse" : "");

        var avatarHtml = isUser ? guestAvatarSvg() : botAvatarSvg();
        var bubbleClass = isUser
            ? "px-4 py-3 rounded-2xl rounded-tr-sm bg-gradient-to-tr from-amal-700 to-amal-600 text-white text-[14px] leading-relaxed whitespace-pre-wrap shadow-sm"
            : "px-4 py-3 rounded-2xl rounded-tl-sm bg-white dark:bg-amal-800 border border-amal-100 dark:border-amal-700 shadow-sm text-slate-700 dark:text-amal-50 text-[14px] leading-relaxed whitespace-pre-wrap";
        var timeClass = "text-[11px] text-slate-400 dark:text-amal-500 mt-1.5" + (isUser ? " text-right mr-1" : " ml-1");

        row.innerHTML =
            avatarHtml +
            '<div><div class="' + bubbleClass + '">' + linkify(escapeHtml(text)) + "</div>" +
            '<div class="' + timeClass + '">' + nowTime() + "</div></div>";
        messagesEl.appendChild(row);
        scrollToBottom();
    }

    function showTyping() {
        var row = document.createElement("div");
        row.className = "flex gap-3 max-w-[85%] msg-enter";
        row.id = "typing-row";
        row.innerHTML =
            botAvatarSvg() +
            '<div class="flex gap-1 px-4 py-3.5 bg-white dark:bg-amal-800 border border-amal-100 dark:border-amal-700 rounded-2xl rounded-tl-sm shadow-sm">' +
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

    // Kalau input sedang fokus (keyboard HP terbuka) SEBELUM balasan bot
    // masuk, minta browser fokus ulang SETELAH DOM balasan (yang bisa saja
    // panjang, mis. katalog program) selesai dirender. Beberapa browser HP
    // menutup keyboard sendiri saat konten di sekitar elemen yang fokus
    // berubah drastis - reassert fokus adalah mitigasi standar dipakai
    // widget chat produksi untuk kasus ini, dan aman dipanggil walau
    // keyboard sebenarnya tidak sempat tertutup (fokus ulang ke elemen yang
    // sudah fokus adalah no-op).
    function pertahankanFokusInput(sudahFokusSebelumnya) {
        if (!sudahFokusSebelumnya) return;
        requestAnimationFrame(function () {
            if (document.activeElement !== inputEl) inputEl.focus();
        });
    }

    async function sendMessage() {
        var text = inputEl.value.trim();
        if (!text && !pendingFile) return;

        if (pendingFile) {
            await sendResiUpload(text);
            return;
        }

        var sudahFokus = document.activeElement === inputEl;
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
        pertahankanFokusInput(sudahFokus);
    }

    async function sendResiUpload(caption) {
        if (!waNumberForOtp) {
            var input = prompt("Boleh Mimin tahu nomor WhatsApp Bapak/Ibu, untuk konfirmasi donasinya?");
            if (!input) return;
            waNumberForOtp = input.trim();
            localStorage.setItem("ra_wa_number", waNumberForOtp);
        }

        var sudahFokus = document.activeElement === inputEl;
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
        pertahankanFokusInput(sudahFokus);
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

    // ---------- Toggle tema terang/gelap ----------
    function toggleTheme() {
        var isDark = document.documentElement.classList.toggle("dark");
        localStorage.setItem("ra_theme", isDark ? "dark" : "light");
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
    window.toggleTheme = toggleTheme;
    window.closeOtpModal = closeOtpModal;
    window.submitPhone = submitPhone;
    window.submitOtp = submitOtp;
    window.resendOtp = resendOtp;
    window.finishOtp = finishOtp;
})();
