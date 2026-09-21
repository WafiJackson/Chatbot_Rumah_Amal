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

    // Balasan bot pakai sintaks gaya WhatsApp (*teks*) untuk bold - WA
    // client-nya sendiri yang menerjemahkan itu jadi tebal, tapi halaman web
    // biasa tidak kenal sintaks itu sama sekali, jadi tanda bintangnya cuma
    // ikut tercetak apa adanya. Dipanggil SETELAH escapeHtml() (prinsip sama
    // seperti linkify()) supaya isi di antara bintang tetap teks yang sudah
    // aman, cuma dibungkus tag <strong> yang aman. Tidak menyeberang baris
    // ([^\n*]) supaya bintang di baris berbeda tidak salah berpasangan.
    function boldify(escapedHtml) {
        return escapedHtml.replace(/\*([^\n*]+)\*/g, "<strong>$1</strong>");
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

    // Avatar bot Mimin: logo statis Rumah Amal (sama seperti halaman pilih
    // channel), bukan maskot SVG - supaya identitas bot konsisten di semua
    // halaman publik.
    function botAvatarHtml() {
        return '<img src="/static/public/bot-icon.png" alt="Mimin AI" class="w-10 h-10 shrink-0 mt-0.5 bot-idle">';
    }

    // Avatar user: siluet tamu netral (bukan huruf inisial "K") - identitas
    // pengunjung web belum tentu terverifikasi saat mengirim pesan, jadi
    // avatar generik lebih jujur daripada seolah-olah sudah tahu namanya.
    function guestAvatarSvg() {
        return (
            '<div class="w-8 h-8 rounded-full bg-slate-200 flex items-center justify-center shrink-0 mt-1.5">' +
            '<svg viewBox="0 0 24 24" fill="currentColor" class="w-5 h-5 text-slate-400">' +
            '<path fill-rule="evenodd" d="M18.685 19.097A9.723 9.723 0 0021.75 12c0-5.385-4.365-9.75-9.75-9.75S2.25 6.615 2.25 12a9.723 9.723 0 003.065 7.097A9.716 9.716 0 0012 21.75a9.716 9.716 0 006.685-2.653zm-12.54-1.285A7.486 7.486 0 0112 15a7.486 7.486 0 015.855 2.812A8.224 8.224 0 0112 20.25a8.224 8.224 0 01-5.855-2.438zM15.75 9a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0z" clip-rule="evenodd"/>' +
            "</svg></div>"
        );
    }

    function addMessage(sender, text) {
        var row = document.createElement("div");
        var isUser = sender === "user";
        row.className = "flex items-start gap-3.5 max-w-[92%] md:max-w-[80%] msg-spring" + (isUser ? " self-end flex-row-reverse" : "");

        var avatarHtml = isUser ? guestAvatarSvg() : botAvatarHtml();
        var bubbleClass = isUser
            ? "p-3.5 md:p-4 rounded-2xl rounded-tr-none bg-amal-600 text-white text-[13.5px] leading-relaxed whitespace-pre-wrap shadow-sm font-medium"
            : "p-5 rounded-2xl rounded-tl-none bg-white border border-slate-200/90 shadow-card-soft text-slate-800 text-[13.5px] leading-relaxed whitespace-pre-wrap";
        var timeClass = "block text-[11px] text-slate-400 font-mono mt-1.5" + (isUser ? " text-right mr-1" : " ml-1");

        row.innerHTML =
            avatarHtml +
            '<div><div class="' + bubbleClass + '">' + linkify(boldify(escapeHtml(text))) + "</div>" +
            '<span class="' + timeClass + '">' + nowTime() + "</span></div>";
        messagesEl.appendChild(row);
        scrollToBottom();
    }

    function showTyping() {
        var row = document.createElement("div");
        row.className = "flex items-start gap-3.5 msg-spring";
        row.id = "typing-row";
        row.innerHTML =
            botAvatarHtml() +
            '<div class="px-4 py-3.5 bg-white rounded-2xl rounded-tl-none border border-slate-200/90 flex items-center gap-1.5 shadow-sm">' +
            '<span class="w-2 h-2 rounded-full bg-amal-600 animate-bounce"></span>' +
            '<span class="w-2 h-2 rounded-full bg-amal-600 animate-bounce" style="animation-delay:150ms"></span>' +
            '<span class="w-2 h-2 rounded-full bg-amal-600 animate-bounce" style="animation-delay:300ms"></span>' +
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

    // ---------- Mobile sidebar drawer ----------
    function openSidebar() {
        var sidebar = document.getElementById("sidebar");
        sidebar.classList.remove("-translate-x-full");
        sidebar.classList.add("translate-x-0");
        var backdrop = document.getElementById("sidebar-backdrop");
        if (backdrop) backdrop.classList.remove("hidden");
    }

    function closeSidebar() {
        var sidebar = document.getElementById("sidebar");
        sidebar.classList.add("-translate-x-full");
        sidebar.classList.remove("translate-x-0");
        var backdrop = document.getElementById("sidebar-backdrop");
        if (backdrop) backdrop.classList.add("hidden");
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

    // Tombol navbar/sidebar (data-navfx): magnet magnify + specular rim -
    // transform-only (translateY+scale, BUKAN width/height), digerakkan GPU
    // tanpa reflow. Sengaja HANYA elemen nav-like ini yang dapat efek ini,
    // bukan seluruh halaman - area pesan dipakai lama untuk baca/ketik.
    function initNavfx() {
        var navfxTargets = Array.prototype.slice.call(document.querySelectorAll("[data-navfx]"));
        if (!navfxTargets.length) return;
        var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        if (reduceMotion) return;

        function clamp01(x) { return x < 0 ? 0 : x > 1 ? 1 : x; }
        var RADIUS = 130;

        function resetNavfx() {
            navfxTargets.forEach(function (el) {
                el.style.transform = "translateY(0) scale(1)";
                el.style.setProperty("--spec-bright", "0");
            });
        }

        // Pengecekan "(hover: hover) and (pointer: fine)" sengaja TIDAK
        // dipakai di sini - di laptop layar sentuh, Chrome sering salah
        // melaporkan hover tidak tersedia walau dipakai dengan mouse/trackpad
        // biasa, sehingga efeknya mati total. pointermove sendiri sudah aman
        // dipakai di perangkat sentuh (tap biasa tidak memicu event ini).
        window.addEventListener("pointermove", function (e) {
            navfxTargets.forEach(function (el) {
                var r = el.getBoundingClientRect();
                var dx = e.clientX - (r.left + r.width / 2);
                var dy = e.clientY - (r.top + r.height / 2);
                var dist = Math.sqrt(dx * dx + dy * dy);
                var v = clamp01(1 - dist / RADIUS);
                var eased = v * v * (3 - 2 * v);

                el.style.transform = "translateY(" + (-3 * eased).toFixed(2) + "px) scale(" + (1 + 0.06 * eased).toFixed(3) + ")";
                el.style.setProperty("--spec-angle", Math.atan2(dy, dx).toFixed(4) + "rad");
                el.style.setProperty("--spec-bright", (eased * 0.9).toFixed(3));
            });
        }, { passive: true });

        window.addEventListener("pointerleave", resetNavfx);
        document.addEventListener("mouseleave", resetNavfx);
    }

    // Latar shader topografi WebGL (murni, tanpa library) - identik dengan
    // pilih_channel.html & admin/base.html supaya seluruh sistem konsisten.
    function initTopoShader() {
        var canvas = document.getElementById("topo-canvas");
        var gl = canvas && canvas.getContext("webgl", { alpha: true, premultipliedAlpha: true, antialias: false, depth: false });
        if (!gl) return;
        gl.enable(gl.BLEND);
        gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
        gl.clearColor(0, 0, 0, 0);

        var vsSource = "attribute vec2 a_position; void main(){ gl_Position=vec4(a_position,0.0,1.0); }";
        var fsSource = [
            "precision highp float;", "uniform vec2 u_resolution;", "uniform float u_time;", "uniform float u_dpr;",
            "vec3 permute(vec3 x){ return mod(((x*34.0)+1.0)*x, 289.0); }",
            "float snoise(vec2 v){",
            "  const vec4 C = vec4(0.211324865405187, 0.366025403784439, -0.577350269189626, 0.024390243902439);",
            "  vec2 i = floor(v + dot(v, C.yy)); vec2 x0 = v - i + dot(i, C.xx);",
            "  vec2 i1; i1 = (x0.x > x0.y) ? vec2(1.0,0.0) : vec2(0.0,1.0);",
            "  vec4 x12 = x0.xyxy + C.xxzz; x12.xy -= i1; i = mod(i, 289.0);",
            "  vec3 p = permute(permute(i.y + vec3(0.0, i1.y, 1.0)) + i.x + vec3(0.0, i1.x, 1.0));",
            "  vec3 m = max(0.5 - vec3(dot(x0,x0), dot(x12.xy,x12.xy), dot(x12.zw,x12.zw)), 0.0);",
            "  m = m*m; m = m*m;",
            "  vec3 x = 2.0 * fract(p * C.www) - 1.0; vec3 h = abs(x) - 0.5; vec3 ox = floor(x + 0.5);",
            "  vec3 a0 = x - ox; m *= 1.79284291400159 - 0.85373472095314 * (a0*a0 + h*h);",
            "  vec3 g; g.x = a0.x*x0.x + h.x*x0.y; g.yz = a0.yz*x12.xz + h.yz*x12.yw;",
            "  return 130.0 * dot(m, g);", "}",
            "void main(){",
            "  vec2 st = gl_FragCoord.xy / u_resolution.xy; st.x *= u_resolution.x / u_resolution.y;",
            "  float gridSize = 46.0 * u_dpr; vec2 gridSt = gl_FragCoord.xy / gridSize; vec2 gridFract = fract(gridSt);",
            "  float lineThickness = 1.0 / gridSize;",
            "  float gridLines = step(1.0 - lineThickness, gridFract.x) + step(1.0 - lineThickness, gridFract.y);",
            "  gridLines = clamp(gridLines, 0.0, 1.0) * 0.22;",
            "  vec2 noisePos = st * 1.4 + vec2(u_time * 0.012, u_time * 0.02);",
            "  float n = snoise(noisePos) * 0.5 + 0.5; float bandVal = n * 9.0;",
            "  float triangleWave = abs(fract(bandVal) - 0.5) * 2.0;",
            "  float topoLines = smoothstep(0.09, 0.0, triangleWave) * 0.85;",
            "  vec3 gridColor = vec3(0.075, 0.42, 0.231);",
            "  vec3 topoColor = vec3(0.965, 0.769, 0.271);",
            "  float lineAlpha = clamp(gridLines + topoLines, 0.0, 1.0);",
            "  vec3 lineColor = mix(gridColor, topoColor, step(0.001, topoLines));",
            "  gl_FragColor = vec4(lineColor * lineAlpha, lineAlpha);", "}"
        ].join("\n");
        function createShader(type, source) { var s = gl.createShader(type); gl.shaderSource(s, source); gl.compileShader(s); return s; }
        var vertexShader = createShader(gl.VERTEX_SHADER, vsSource);
        var fragmentShader = createShader(gl.FRAGMENT_SHADER, fsSource);
        var program = gl.createProgram();
        gl.attachShader(program, vertexShader); gl.attachShader(program, fragmentShader); gl.linkProgram(program); gl.useProgram(program);
        var positionBuffer = gl.createBuffer();
        gl.bindBuffer(gl.ARRAY_BUFFER, positionBuffer);
        gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
        var positionLocation = gl.getAttribLocation(program, "a_position");
        gl.enableVertexAttribArray(positionLocation);
        gl.vertexAttribPointer(positionLocation, 2, gl.FLOAT, false, 0, 0);
        var resolutionLocation = gl.getUniformLocation(program, "u_resolution");
        var timeLocation = gl.getUniformLocation(program, "u_time");
        var dprLocation = gl.getUniformLocation(program, "u_dpr");
        function resizeCanvas() {
            var dpr = window.devicePixelRatio || 1;
            canvas.width = canvas.clientWidth * dpr; canvas.height = canvas.clientHeight * dpr;
            gl.viewport(0, 0, canvas.width, canvas.height);
            gl.uniform2f(resolutionLocation, canvas.width, canvas.height); gl.uniform1f(dprLocation, dpr);
        }
        window.addEventListener("resize", resizeCanvas); resizeCanvas();
        var reduceMotionShader = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        var startTime = performance.now();
        function render(time) {
            gl.clear(gl.COLOR_BUFFER_BIT);
            gl.uniform1f(timeLocation, (time - startTime) * 0.001);
            gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
            if (!reduceMotionShader) requestAnimationFrame(render);
        }
        requestAnimationFrame(render);
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
    initNavfx();
    initTopoShader();

    // Reveal fade-up saat halaman dimuat (pola sama seperti pilih_channel.html/admin).
    setTimeout(function () {
        document.querySelectorAll(".reveal").forEach(function (el, i) {
            setTimeout(function () { el.classList.add("in"); }, i * 120);
        });
    }, 100);

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
