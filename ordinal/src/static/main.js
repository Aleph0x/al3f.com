document.addEventListener("DOMContentLoaded", () => {
  setupLatestFilter();
  setupSectionFilter();
  setupChangelogFilter();
  setupActivityHover();
  setupLazyMedia();
  setupLightbox();
});

function setupLatestFilter() {
  const input = document.getElementById("latest-filter");
  if (!input) return;
  const cards = Array.from(document.querySelectorAll(".latest-grid .card"));
  input.addEventListener("input", () => {
    const query = input.value.trim().toLowerCase();
    cards.forEach((card) => {
      const title = card.dataset.title || "";
      const domain = card.dataset.domain || "";
      const match = !query || title.includes(query) || domain.includes(query);
      card.style.display = match ? "" : "none";
    });
  });
}

function setupSectionFilter() {
  const input = document.getElementById("section-filter");
  if (!input) return;
  const cards = Array.from(
    document.querySelectorAll(".domain-card-grid .card")
  );
  const params = new URLSearchParams(window.location.search);
  const preset = params.get("q") || params.get("division") || params.get("domain");
  if (preset) {
    input.value = preset.replace(/\+/g, " ");
  }
  input.addEventListener("input", () => {
    const query = input.value.trim().toLowerCase();
    cards.forEach((card) => {
      const title = (card.dataset.title || "").toLowerCase();
      const domain = (card.dataset.domain || "").toLowerCase();
      const division = (card.dataset.division || "").toLowerCase();
      const match =
        !query ||
        title.includes(query) ||
        domain.includes(query) ||
        division.includes(query);
      card.style.display = match ? "" : "none";
    });
  });
  if (preset) {
    input.dispatchEvent(new Event("input"));
  }
}

function setupChangelogFilter() {
  const buttons = Array.from(
    document.querySelectorAll(".pill-filters [data-filter]")
  );
  const rows = Array.from(
    document.querySelectorAll(".changelog-table .table-row, .changelog ul li")
  );
  if (buttons.length === 0 || rows.length === 0) return;

  const apply = (filter) => {
    rows.forEach((row) => {
      const action = row.dataset.action || "commit";
      row.style.display = filter === "all" || action === filter ? "" : "none";
    });
  };

  buttons.forEach((btn) => {
    btn.addEventListener("click", () => {
      buttons.forEach((b) => b.setAttribute("aria-pressed", "false"));
      btn.setAttribute("aria-pressed", "true");
      apply(btn.dataset.filter);
    });
  });

  apply("all");
}

function setupActivityHover() {
  const info = document.getElementById("activity-info");
  const cells = Array.from(document.querySelectorAll(".activity-graph .cell"));
  if (!info || cells.length === 0) return;
  cells.forEach((cell) => {
    cell.addEventListener("mouseenter", () => {
      const date = cell.dataset.date || "";
      const count = cell.dataset.count || "0";
      info.textContent = `${date} · ${count} change(s)`;
    });
  });
}

function setupLazyMedia() {
  const media = Array.from(document.querySelectorAll("img:not([loading]), video"));
  if ("loading" in HTMLImageElement.prototype) {
    media.forEach((el) => {
      if (el.tagName.toLowerCase() === "img") {
        el.loading = "lazy";
      }
    });
    return;
  }
  const obs = new IntersectionObserver(
    (entries, observer) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        const el = entry.target;
        if (el.dataset.src) el.src = el.dataset.src;
        observer.unobserve(el);
      });
    },
    { rootMargin: "200px" }
  );
  media.forEach((el) => obs.observe(el));
}

function setupLightbox() {
  const images = Array.from(document.querySelectorAll("main img"));
  if (images.length === 0) return;

  const overlay = document.createElement("div");
  overlay.className = "lightbox-overlay";
  const img = document.createElement("img");
  overlay.appendChild(img);
  overlay.addEventListener("click", () => overlay.classList.remove("open"));
  document.body.appendChild(overlay);

  images.forEach((el) => {
    el.classList.add("lightboxable");
    el.addEventListener("click", () => {
      img.src = el.src;
      overlay.classList.add("open");
    });
  });
}
