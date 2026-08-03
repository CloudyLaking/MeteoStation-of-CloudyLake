const fileInput = document.querySelector("#colorbar-file");
const dropzone = document.querySelector("#colorbar-dropzone");
const canvasShell = document.querySelector("#translator-canvas-shell");
const sourceCanvas = document.querySelector("#colorbar-source-canvas");
const sourceContext = sourceCanvas.getContext("2d", { willReadFrequently: true });
const imageCanvas = document.createElement("canvas");
const imageContext = imageCanvas.getContext("2d", { willReadFrequently: true });
const selectionNote = document.querySelector("#translator-selection-note");
const autoButton = document.querySelector("#colorbar-auto");
const resetButton = document.querySelector("#colorbar-reset");
const generateButton = document.querySelector("#colorbar-generate");
const orientationInput = document.querySelector("#colorbar-orientation");
const modeInput = document.querySelector("#colorbar-mode");
const countInput = document.querySelector("#colorbar-count");
const formatInput = document.querySelector("#colorbar-format");
const minimumInput = document.querySelector("#colorbar-min");
const maximumInput = document.querySelector("#colorbar-max");
const reverseInput = document.querySelector("#colorbar-reverse");
const outputSection = document.querySelector("#translator-output");
const palette = document.querySelector("#translator-palette");
const swatches = document.querySelector("#translator-swatches");
const codeOutput = document.querySelector("#colorbar-code");
const resultNote = document.querySelector("#translator-result-note");
const copyButton = document.querySelector("#colorbar-copy");
const downloadButton = document.querySelector("#colorbar-download");

const state = {
  loaded: false,
  crop: null,
  dragging: false,
  dragStart: null,
  colors: [],
  orientation: "vertical",
};

function clamp(value, minimum, maximum) {
  return Math.min(maximum, Math.max(minimum, value));
}

function normalizedCrop(start, end) {
  const x = clamp(Math.min(start.x, end.x), 0, imageCanvas.width - 1);
  const y = clamp(Math.min(start.y, end.y), 0, imageCanvas.height - 1);
  const right = clamp(Math.max(start.x, end.x), x + 1, imageCanvas.width);
  const bottom = clamp(Math.max(start.y, end.y), y + 1, imageCanvas.height);
  return { x, y, width: right - x, height: bottom - y };
}

function canvasPoint(event) {
  const bounds = sourceCanvas.getBoundingClientRect();
  return {
    x: (event.clientX - bounds.left) / bounds.width * sourceCanvas.width,
    y: (event.clientY - bounds.top) / bounds.height * sourceCanvas.height,
  };
}

function drawSource() {
  if (!state.loaded) return;
  sourceContext.clearRect(0, 0, sourceCanvas.width, sourceCanvas.height);
  sourceContext.drawImage(imageCanvas, 0, 0);
  if (!state.crop) return;
  const crop = state.crop;
  sourceContext.save();
  sourceContext.fillStyle = "rgba(12, 31, 42, 0.34)";
  sourceContext.beginPath();
  sourceContext.rect(0, 0, sourceCanvas.width, sourceCanvas.height);
  sourceContext.rect(crop.x, crop.y, crop.width, crop.height);
  sourceContext.fill("evenodd");
  sourceContext.strokeStyle = "#f2c94c";
  sourceContext.lineWidth = Math.max(2, sourceCanvas.width / 700);
  sourceContext.setLineDash([8, 6]);
  sourceContext.strokeRect(crop.x, crop.y, crop.width, crop.height);
  sourceContext.restore();
}

function setCrop(crop, message = "已更新框选区域。") {
  const x = clamp(Math.round(crop.x), 0, Math.max(0, imageCanvas.width - 2));
  const y = clamp(Math.round(crop.y), 0, Math.max(0, imageCanvas.height - 2));
  state.crop = {
    x,
    y,
    width: clamp(Math.round(crop.width), 2, imageCanvas.width - x),
    height: clamp(Math.round(crop.height), 2, imageCanvas.height - y),
  };
  selectionNote.textContent = `${message} ${state.crop.width} × ${state.crop.height} px`;
  drawSource();
}

async function loadImage(file) {
  if (!file || !file.type.startsWith("image/")) {
    selectionNote.textContent = "请选择有效的图片文件。";
    return;
  }
  const imageUrl = URL.createObjectURL(file);
  const image = new Image();
  try {
    await new Promise((resolve, reject) => {
      image.onload = resolve;
      image.onerror = reject;
      image.src = imageUrl;
    });
    const scale = Math.min(1, 1800 / Math.max(image.naturalWidth, image.naturalHeight));
    const width = Math.max(1, Math.round(image.naturalWidth * scale));
    const height = Math.max(1, Math.round(image.naturalHeight * scale));
    imageCanvas.width = width;
    imageCanvas.height = height;
    sourceCanvas.width = width;
    sourceCanvas.height = height;
    imageContext.clearRect(0, 0, width, height);
    imageContext.drawImage(image, 0, 0, width, height);
    state.loaded = true;
    canvasShell.hidden = false;
    autoButton.disabled = false;
    resetButton.disabled = false;
    generateButton.disabled = false;
    autoDetectColorbar();
    generatePalette();
  } finally {
    URL.revokeObjectURL(imageUrl);
  }
}

function componentDetection() {
  const maxSide = 220;
  const scale = Math.min(1, maxSide / Math.max(imageCanvas.width, imageCanvas.height));
  const width = Math.max(1, Math.round(imageCanvas.width * scale));
  const height = Math.max(1, Math.round(imageCanvas.height * scale));
  const detector = document.createElement("canvas");
  detector.width = width;
  detector.height = height;
  const context = detector.getContext("2d", { willReadFrequently: true });
  context.drawImage(imageCanvas, 0, 0, width, height);
  const pixels = context.getImageData(0, 0, width, height).data;
  const mask = new Uint8Array(width * height);
  for (let index = 0; index < mask.length; index += 1) {
    const offset = index * 4;
    const red = pixels[offset];
    const green = pixels[offset + 1];
    const blue = pixels[offset + 2];
    const maximum = Math.max(red, green, blue);
    const minimum = Math.min(red, green, blue);
    const chroma = maximum - minimum;
    const lightness = (maximum + minimum) / 2;
    mask[index] = pixels[offset + 3] > 80 && chroma >= 14 && lightness > 10 && lightness < 250 ? 1 : 0;
  }
  const seen = new Uint8Array(mask.length);
  let best = null;
  for (let seed = 0; seed < mask.length; seed += 1) {
    if (!mask[seed] || seen[seed]) continue;
    const queue = [seed];
    seen[seed] = 1;
    let cursor = 0;
    let area = 0;
    let minX = width;
    let maxX = 0;
    let minY = height;
    let maxY = 0;
    while (cursor < queue.length) {
      const index = queue[cursor++];
      const x = index % width;
      const y = Math.floor(index / width);
      area += 1;
      minX = Math.min(minX, x); maxX = Math.max(maxX, x);
      minY = Math.min(minY, y); maxY = Math.max(maxY, y);
      const neighbours = [index - 1, index + 1, index - width, index + width];
      neighbours.forEach((next, direction) => {
        if (next < 0 || next >= mask.length || seen[next] || !mask[next]) return;
        if (direction === 0 && x === 0) return;
        if (direction === 1 && x === width - 1) return;
        seen[next] = 1;
        queue.push(next);
      });
    }
    const boxWidth = maxX - minX + 1;
    const boxHeight = maxY - minY + 1;
    const elongation = Math.max(boxWidth / Math.max(boxHeight, 1), boxHeight / Math.max(boxWidth, 1));
    const score = area * Math.min(elongation, 12);
    if (!best || score > best.score) best = { minX, maxX, minY, maxY, area, score };
  }
  if (!best || best.area < Math.max(8, width * height * 0.0008)) return null;
  const inverse = 1 / scale;
  const padding = Math.max(1, Math.round(inverse));
  return {
    x: clamp(best.minX * inverse - padding, 0, imageCanvas.width - 2),
    y: clamp(best.minY * inverse - padding, 0, imageCanvas.height - 2),
    width: clamp((best.maxX - best.minX + 1) * inverse + padding * 2, 2, imageCanvas.width),
    height: clamp((best.maxY - best.minY + 1) * inverse + padding * 2, 2, imageCanvas.height),
  };
}

function autoDetectColorbar() {
  if (!state.loaded) return;
  const detected = componentDetection();
  if (detected) {
    setCrop(detected, "已自动框选候选色条；如有偏差可重新拖动框选。");
  } else {
    setCrop({ x: 0, y: 0, width: imageCanvas.width, height: imageCanvas.height }, "未找到明确色带，已使用整张图片；请手动框选。");
  }
}

function median(values) {
  const sorted = [...values].sort((left, right) => left - right);
  return sorted[Math.floor(sorted.length / 2)] ?? 0;
}

function rgbToHex(red, green, blue) {
  return `#${[red, green, blue].map((value) => clamp(Math.round(value), 0, 255).toString(16).padStart(2, "0")).join("")}`.toUpperCase();
}

function sampleColors() {
  if (!state.crop) return [];
  const crop = state.crop;
  const mode = modeInput.value;
  const count = clamp(Number.parseInt(countInput.value, 10) || 12, 2, 64);
  countInput.value = count;
  const orientation = orientationInput.value === "auto"
    ? (crop.height >= crop.width ? "vertical" : "horizontal")
    : orientationInput.value;
  const data = imageContext.getImageData(crop.x, crop.y, crop.width, crop.height).data;
  const colors = [];
  const axisLength = orientation === "vertical" ? crop.height : crop.width;
  const crossLength = orientation === "vertical" ? crop.width : crop.height;
  for (let index = 0; index < count; index += 1) {
    const position = mode === "discrete" ? (index + 0.5) / count : index / Math.max(count - 1, 1);
    const axisCenter = clamp(Math.round(position * (axisLength - 1)), 0, axisLength - 1);
    const reds = [];
    const greens = [];
    const blues = [];
    for (let axisOffset = -2; axisOffset <= 2; axisOffset += 1) {
      const axis = clamp(axisCenter + axisOffset, 0, axisLength - 1);
      for (let sample = 0; sample < 11; sample += 1) {
        const cross = clamp(Math.round((0.22 + sample / 10 * 0.56) * (crossLength - 1)), 0, crossLength - 1);
        const x = orientation === "vertical" ? cross : axis;
        const y = orientation === "vertical" ? axis : cross;
        const offset = (y * crop.width + x) * 4;
        if (data[offset + 3] < 80) continue;
        reds.push(data[offset]); greens.push(data[offset + 1]); blues.push(data[offset + 2]);
      }
    }
    colors.push(rgbToHex(median(reds), median(greens), median(blues)));
  }
  state.orientation = orientation;
  return reverseInput.checked ? colors.reverse() : colors;
}

function numericRange() {
  let minimum = Number(minimumInput.value);
  let maximum = Number(maximumInput.value);
  if (!Number.isFinite(minimum)) minimum = 0;
  if (!Number.isFinite(maximum)) maximum = 1;
  if (minimum === maximum) maximum = minimum + 1;
  return [minimum, maximum];
}

function generatedCode(colors) {
  const mode = modeInput.value;
  const format = formatInput.value;
  const [minimum, maximum] = numericRange();
  const positions = colors.map((_, index) => index / Math.max(colors.length - 1, 1));
  if (format === "matplotlib") {
    const colorList = colors.map((color) => `    "${color}",`).join("\n");
    if (mode === "discrete") {
      return `import numpy as np\nfrom matplotlib.colors import ListedColormap, BoundaryNorm\n\ncolors = [\n${colorList}\n]\nbounds = np.linspace(${minimum}, ${maximum}, ${colors.length + 1})\ncmap = ListedColormap(colors, name="translated_colorbar")\nnorm = BoundaryNorm(bounds, cmap.N)`;
    }
    return `from matplotlib.colors import LinearSegmentedColormap\n\ncolors = [\n${colorList}\n]\ncmap = LinearSegmentedColormap.from_list(\n    "translated_colorbar", colors, N=256\n)`;
  }
  if (format === "plotly") {
    const stops = colors.map((color, index) => `    [${positions[index].toFixed(4)}, "${color}"],`).join("\n");
    return `colorscale = [\n${stops}\n]\n\n# Example: px.imshow(data, color_continuous_scale=colorscale, range_color=[${minimum}, ${maximum}])`;
  }
  if (format === "css") {
    const direction = state.orientation === "vertical" ? "to bottom" : "to right";
    const stops = colors.map((color, index) => `${color} ${(positions[index] * 100).toFixed(1)}%`).join(", ");
    return `background: linear-gradient(${direction}, ${stops});`;
  }
  return JSON.stringify({
    name: "translated_colorbar",
    mode,
    orientation: state.orientation,
    minimum,
    maximum,
    colors: colors.map((color, index) => ({
      position: Number(positions[index].toFixed(6)),
      value: Number((minimum + positions[index] * (maximum - minimum)).toFixed(6)),
      color,
    })),
  }, null, 2);
}

function renderPalette(colors) {
  const direction = state.orientation === "vertical" ? "to bottom" : "to right";
  palette.style.background = `linear-gradient(${direction}, ${colors.join(", ")})`;
  palette.classList.toggle("is-vertical", state.orientation === "vertical");
  swatches.replaceChildren(...colors.map((color, index) => {
    const item = document.createElement("span");
    item.style.setProperty("--swatch", color);
    item.textContent = `${String(index + 1).padStart(2, "0")} ${color}`;
    return item;
  }));
}

function generatePalette() {
  if (!state.loaded || !state.crop) return;
  const colors = sampleColors();
  state.colors = colors;
  renderPalette(colors);
  codeOutput.value = generatedCode(colors);
  outputSection.hidden = false;
  resultNote.textContent = `${state.orientation === "vertical" ? "纵向" : "横向"}色条 · ${modeInput.value === "continuous" ? "连续" : "离散"}模式 · ${colors.length} 色 · @CloudyLake`;
}

sourceCanvas.addEventListener("pointerdown", (event) => {
  if (!state.loaded) return;
  state.dragging = true;
  state.dragStart = canvasPoint(event);
  sourceCanvas.setPointerCapture(event.pointerId);
  setCrop(normalizedCrop(state.dragStart, state.dragStart), "正在框选：");
});
sourceCanvas.addEventListener("pointermove", (event) => {
  if (!state.dragging) return;
  setCrop(normalizedCrop(state.dragStart, canvasPoint(event)), "正在框选：");
});
sourceCanvas.addEventListener("pointerup", (event) => {
  if (!state.dragging) return;
  state.dragging = false;
  setCrop(normalizedCrop(state.dragStart, canvasPoint(event)), "已手动框选色条。");
  generatePalette();
});

fileInput.addEventListener("change", () => loadImage(fileInput.files[0]));
dropzone.addEventListener("dragover", (event) => { event.preventDefault(); dropzone.classList.add("is-dragging"); });
dropzone.addEventListener("dragleave", () => dropzone.classList.remove("is-dragging"));
dropzone.addEventListener("drop", (event) => {
  event.preventDefault();
  dropzone.classList.remove("is-dragging");
  loadImage([...event.dataTransfer.files].find((file) => file.type.startsWith("image/")));
});
document.addEventListener("paste", (event) => {
  const item = [...event.clipboardData.items].find((entry) => entry.type.startsWith("image/"));
  if (item) loadImage(item.getAsFile());
});
autoButton.addEventListener("click", () => { autoDetectColorbar(); generatePalette(); });
resetButton.addEventListener("click", () => {
  setCrop({ x: 0, y: 0, width: imageCanvas.width, height: imageCanvas.height }, "已使用整张图片。");
  generatePalette();
});
generateButton.addEventListener("click", generatePalette);
[orientationInput, modeInput, countInput, formatInput, minimumInput, maximumInput, reverseInput].forEach((input) => {
  input.addEventListener("change", generatePalette);
});
copyButton.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(codeOutput.value);
  } catch {
    codeOutput.select();
    document.execCommand("copy");
  }
  copyButton.textContent = "已复制";
  window.setTimeout(() => { copyButton.textContent = "复制代码"; }, 1400);
});
downloadButton.addEventListener("click", () => {
  const extensions = { matplotlib: "py", plotly: "py", css: "css", json: "json" };
  const blob = new Blob([codeOutput.value], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `translated-colorbar.${extensions[formatInput.value]}`;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
});
