/* ============================================================
   Waste Segregation - small shared UI helpers.
   ============================================================ */

function ratingBadge(rating) {
  if (!rating || rating === "NOT_RATED") {
    return '<span class="badge badge-neutral">Not rated yet</span>';
  }
  const cls = { GOOD: "badge-good", AVERAGE: "badge-average", POOR: "badge-poor" }[rating] || "badge-neutral";
  return `<span class="badge ${cls}">${rating.charAt(0) + rating.slice(1).toLowerCase()}</span>`;
}

function fmtDate(iso) {
  if (!iso) return "-";
  const d = new Date(iso.includes("T") || iso.includes(" ") ? iso.replace(" ", "T") + (iso.includes("Z") ? "" : "Z") : iso + "T00:00:00Z");
  if (isNaN(d)) return iso;
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

function fmtDateTime(iso) {
  if (!iso) return "-";
  const d = new Date(iso.replace(" ", "T") + (iso.includes("Z") ? "" : "Z"));
  if (isNaN(d)) return iso;
  return d.toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

function renderNavbar(active) {
  const el = document.getElementById("navbar");
  if (!el) return;
  const loggedIn = WasteSegAuth.isLoggedIn();
  const role = loggedIn ? WasteSegAuth.role() : null;
  const name = loggedIn ? WasteSegAuth.user().name : null;

  let links = "";
  if (loggedIn) {
    links = `
      <div class="nav-user">
        <span class="chip role-pill">${role}</span>
        <span>${name || ""}</span>
        <button class="btn btn-outline btn-sm" onclick="WasteSegAuth.logout()">Log out</button>
      </div>`;
  } else {
    links = `
      <div class="nav-links">
        <a href="/index.html#how-it-works">How it works</a>
        <a href="/login.html" class="btn btn-outline btn-sm">Log in</a>
        <a href="/register.html" class="btn btn-primary btn-sm">Register household</a>
      </div>`;
  }

  el.innerHTML = `
    <div class="topbar-inner">
      <a class="brand" href="${loggedIn ? WasteSegAuth.homeForRole() : '/index.html'}">
        <span class="brand-mark">S</span> Waste Segregation
      </a>
      ${links}
    </div>`;
}

function toast(msg, type) {
  let box = document.getElementById("toast-box");
  if (!box) {
    box = document.createElement("div");
    box.id = "toast-box";
    box.style.cssText = "position:fixed;bottom:20px;right:20px;z-index:200;display:flex;flex-direction:column;gap:10px;max-width:340px;";
    document.body.appendChild(box);
  }
  const t = document.createElement("div");
  t.className = "alert " + (type === "error" ? "alert-error" : type === "info" ? "alert-info" : "alert-success");
  t.style.cssText = "box-shadow:var(--shadow-md);margin:0;animation:fadein .15s ease;";
  t.textContent = msg;
  box.appendChild(t);
  setTimeout(() => t.remove(), 4200);
}

function setActiveTab(tabName) {
  document.querySelectorAll(".tabbar button").forEach((b) => {
    b.classList.toggle("active", b.dataset.tab === tabName);
  });
  document.querySelectorAll(".tab-panel").forEach((p) => {
    p.classList.toggle("active", p.id === "tab-" + tabName);
  });
  const url = new URL(window.location);
  url.searchParams.set("tab", tabName);
  window.history.replaceState({}, "", url);
}

function initTabs(defaultTab) {
  document.querySelectorAll(".tabbar button").forEach((b) => {
    b.addEventListener("click", () => setActiveTab(b.dataset.tab));
  });
  const url = new URL(window.location);
  const tab = url.searchParams.get("tab") || defaultTab;
  setActiveTab(tab);
}