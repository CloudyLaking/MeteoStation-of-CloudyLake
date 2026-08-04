// Shared location search suggestions for the forecast pages: combines the
// station registry (national + worldwide) with the administrative place index
// (province / city / district names) into one custom dropdown. Selecting an
// item fills the input with a station id or a place name; the backend resolves
// both (plus "lat,lon" pairs) when the form is submitted.
function initLocationSuggest(input, panel, { minChars = 2, onPick } = {}) {
  let timer = null;
  let items = [];
  let index = -1;

  function close() {
    panel.hidden = true;
    items = [];
    index = -1;
  }

  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function placeLevel(level) {
    return { province: "省", city: "市", district: "区县" }[level] || (level || "地名");
  }

  function pick(item) {
    input.value = item.value;
    close();
    if (onPick) onPick(item);
  }

  function render(list) {
    panel.replaceChildren(...list.map((item, position) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "station-suggestion";
      button.dataset.index = String(position);
      const title = document.createElement("strong");
      title.textContent = item.title;
      const meta = document.createElement("small");
      meta.textContent = `${item.meta} · ${item.latitude.toFixed(2)},${item.longitude.toFixed(2)}`;
      button.append(title, meta);
      button.addEventListener("mousedown", (event) => {
        event.preventDefault();
        pick(item);
      });
      return button;
    }));
    panel.hidden = false;
  }

  function highlight(position) {
    index = position;
    panel.querySelectorAll(".station-suggestion").forEach((item) => {
      item.classList.toggle("is-highlighted", Number(item.dataset.index) === position);
    });
    panel.querySelector(`[data-index="${position}"]`)?.scrollIntoView({ block: "nearest" });
  }

  async function search() {
    const query = input.value.trim();
    if (query.length < minChars || query.includes(",") || query.includes("，")) {
      close();
      return;
    }
    try {
      const [stationResponse, placeResponse] = await Promise.all([
        fetch(`/api/v1/stations/search?q=${encodeURIComponent(query)}&limit=6`),
        fetch(`/api/v1/places/search?q=${encodeURIComponent(query)}&limit=6`),
      ]);
      const stations = stationResponse.ok ? (await stationResponse.json()).stations || [] : [];
      const places = placeResponse.ok ? (await placeResponse.json()).places || [] : [];
      const combined = [
        ...stations.map((station) => ({
          kind: "station",
          value: station.wmo_id,
          title: station.display_name,
          meta: `WMO ${station.wmo_id}`,
          latitude: station.latitude,
          longitude: station.longitude,
        })),
        ...places.map((place) => ({
          kind: "place",
          value: place.name,
          title: place.name,
          meta: placeLevel(place.level),
          latitude: place.latitude,
          longitude: place.longitude,
        })),
      ];
      items = combined.slice(0, 10);
      if (!items.length) {
        close();
        return;
      }
      render(items);
    } catch {
      close();
    }
  }

  input.addEventListener("input", () => {
    window.clearTimeout(timer);
    timer = window.setTimeout(search, 180);
  });
  input.addEventListener("keydown", (event) => {
    if (panel.hidden) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      highlight(Math.min(items.length - 1, index + 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      highlight(Math.max(0, index - 1));
    } else if (event.key === "Enter") {
      const item = items[index];
      if (item) {
        event.preventDefault();
        pick(item);
      }
    } else if (event.key === "Escape") {
      close();
    }
  });
  document.addEventListener("pointerdown", (event) => {
    if (!input.closest(".station-search-box")) close();
  });
}
