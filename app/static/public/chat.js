(function () {
    "use strict";

    var messagesEl = document.getElementById("messages");
    var inputEl = document.getElementById("chat-input");
    var pendingFile = null;
    var waNumberForOtp = "";

    function scrollToBottom() {
        messagesEl.scrollTop = messagesEl.scrollHeight;
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
        row.className = "flex gap-2 max-w-[78%]" + (isUser ? " self-end flex-row-reverse" : "");

        var avatarClass = isUser
            ? "w-6.5 h-6.5 rounded-full bg-slate-100 border border-slate-200 text-slate-500 flex items-center justify-center text-[11px] font-bold shrink-0 mt-0.5"
            : "w-6.5 h-6.5 rounded-full bg-emerald-600 text-white flex items-center justify-center text-[11px] font-bold shrink-0 mt-0.5";
        var bubbleClass = isUser
            ? "px-3.5 py-2.5 rounded-2xl rounded-br-md bg-emerald-600 text-white text-[13.5px] leading-relaxed whitespace-pre-wrap"
            : "px-3.5 py-2.5 rounded-2xl rounded-bl-md bg-slate-100 text-slate-900 text-[13.5px] leading-relaxed whitespace-pre-wrap";
        var timeClass = "text-[10.5px] text-slate-400 mt-1" + (isUser ? " text-right" : "");

        row.innerHTML =
            '<div class="' + avatarClass + '">' + (isUser ? "K" : "M") + "</div>" +
            '<div><div class="' + bubbleClass + '">' + escapeHtml(text) + "</div>" +
            '<div class="' + timeClass + '">' + nowTime() + "</div></div>";
        messagesEl.appendChild(row);
        scrollToBottom();
    }

    function showTyping() {
        var row = document.createElement("div");
        row.className = "flex gap-2 max-w-[78%]";
        row.id = "typing-row";
        row.innerHTML =
            '<div class="w-6.5 h-6.5 rounded-full bg-emerald-600 text-white flex items-center justify-center text-[11px] font-bold shrink-0 mt-0.5">M</div>' +
            '<div class="flex gap-1 px-3.5 py-3 bg-slate-100 rounded-2xl rounded-bl-md">' +
            '<span class="w-1.5 h-1.5 rounded-full bg-slate-400 animate-bounce" style="animation-delay:0ms"></span>' +
            '<span class="w-1.5 h-1.5 rounded-full bg-slate-400 animate-bounce" style="animation-delay:150ms"></span>' +
            '<span class="w-1.5 h-1.5 rounded-full bg-slate-400 animate-bounce" style="animation-delay:300ms"></span>' +
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
                openOtp();
            }
        } catch (err) {
            hideTyping();
            addMessage("bot", "Maaf, Mimin sedang gangguan koneksi. Coba lagi sebentar ya 🙏");
        }
    }

    async function sendResiUpload(caption) {
        if (!waNumberForOtp) {
            var input = prompt("Boleh Mimin tahu nomor WhatsApp Kakak, untuk konfirmasi donasinya?");
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

    // ---------- OTP modal ----------
    function openOtp() {
        document.getElementById("otp-step-number").classList.remove("hidden");
        document.getElementById("otp-step-code").classList.add("hidden");
        document.getElementById("otp-step-desc").textContent = "Masukkan nomor WhatsApp Kakak, Mimin akan kirimkan kode verifikasi lewat WhatsApp.";
        hideOtpError();
        var saved = localStorage.getItem("ra_wa_number");
        if (saved) document.getElementById("wa-number").value = saved;
        var modal = document.getElementById("otp-modal");
        modal.classList.remove("hidden");
        modal.classList.add("flex");
    }

    function closeOtp() {
        var modal = document.getElementById("otp-modal");
        modal.classList.add("hidden");
        modal.classList.remove("flex");
    }

    function showOtpError(msg) {
        var el = document.getElementById("otp-error");
        el.textContent = msg;
        el.classList.remove("hidden");
    }
    function hideOtpError() {
        document.getElementById("otp-error").classList.add("hidden");
    }
    function showOtpError2(msg) {
        var el = document.getElementById("otp-error-2");
        el.textContent = msg;
        el.classList.remove("hidden");
    }

    async function submitWaNumber() {
        var number = document.getElementById("wa-number").value.trim();
        hideOtpError();
        if (!number) {
            showOtpError("Nomor WhatsApp belum diisi.");
            return;
        }

        try {
            var res = await fetch("/api/web-otp/request", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ wa_number: number }),
            });
            var data = await res.json();
            if (data.status !== "sukses") {
                showOtpError(data.pesan || "Gagal mengirim kode OTP.");
                return;
            }
            waNumberForOtp = number;
            localStorage.setItem("ra_wa_number", number);
            document.getElementById("otp-step-number").classList.add("hidden");
            document.getElementById("otp-step-code").classList.remove("hidden");
            document.getElementById("otp-step-desc").textContent = "Kode verifikasi sudah Mimin kirim ke WhatsApp " + number + ".";
        } catch (err) {
            showOtpError("Gagal menghubungi server. Coba lagi ya.");
        }
    }

    async function submitOtpCode() {
        var code = document.getElementById("otp-code").value.trim();
        var el2 = document.getElementById("otp-error-2");
        el2.classList.add("hidden");
        if (!code) {
            showOtpError2("Kode OTP belum diisi.");
            return;
        }

        try {
            var res = await fetch("/api/web-otp/verify", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ wa_number: waNumberForOtp, otp_code: code }),
            });
            var data = await res.json();
            if (data.status !== "sukses") {
                showOtpError2(data.pesan || "Kode OTP salah.");
                return;
            }
            closeOtp();
            addMessage("bot", data.reply);
        } catch (err) {
            showOtpError2("Gagal menghubungi server. Coba lagi ya.");
        }
    }

    document.getElementById("otp-modal").addEventListener("click", function (e) {
        if (e.target === this) closeOtp();
    });

    // expose handlers used by inline onclick/onkeydown attributes in chat.html
    window.sendMessage = sendMessage;
    window.quickPrompt = quickPrompt;
    window.openGoogleSearch = openGoogleSearch;
    window.handleKeydown = handleKeydown;
    window.autoExpand = autoExpand;
    window.triggerUpload = triggerUpload;
    window.onFileChosen = onFileChosen;
    window.clearResi = clearResi;
    window.closeOtp = closeOtp;
    window.submitWaNumber = submitWaNumber;
    window.submitOtpCode = submitOtpCode;
})();
