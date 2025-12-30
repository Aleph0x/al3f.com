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
  const cards = Array.from(document.querySelectorAll(".section-card"));
  input.addEventListener("input", () => {
    const query = input.value.trim().toLowerCase();
    cards.forEach((card) => {
      const title = (card.dataset.title || "").toLowerCase();
      const domain = (card.dataset.domain || "").toLowerCase();
      const match = !query || title.includes(query) || domain.includes(query);
      card.style.display = match ? "" : "none";
    });
  });
}

function setupChangelogFilter() {
  const input = document.getElementById("changelog-filter");
  const select = document.getElementById("changelog-action");
  const entries = Array.from(
    document.querySelectorAll(".changelog-table .table-row, .changelog ul li")
  );
  if (!input || !select || entries.length === 0) return;

  const apply = () => {
    const query = input.value.trim().toLowerCase();
    const action = select.value;
    entries.forEach((li) => {
      const liAction = li.dataset.action || "";
      const path = li.dataset.path || "";
      const actionMatch = action === "all" || liAction === action;
      const textMatch = !query || path.includes(query);
      li.style.display = actionMatch && textMatch ? "" : "none";
    });
  };

  input.addEventListener("input", apply);
  select.addEventListener("change", apply);
}

function setupActivityHover() {
  const info = document.getElementById("activity-info");
  const cells = Array.from(document.querySelectorAll(".activity-graph .cell"));
  if (!info || cells.length === 0) return;
  cells.forEach((cell) => {
    cell.addEventListener("mouseenter", () => {
      info.textContent = cell.getAttribute("title");
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
