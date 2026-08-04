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
const ticksButton = document.querySelector("#colorbar-ticks");
const ticksNote = document.querySelector("#translator-ticks-note");

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
    ticksButton.disabled = false;
    autoDetectColorbar();
    generatePalette();
    applyReadTicks();
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
    // A generous chroma floor keeps near-grey segments of a gradient (e.g. the
    // middle of cividis) connected so the whole bar is detected as one blob.
    mask[index] = pixels[offset + 3] > 80 && chroma >= 8 && lightness > 5 && lightness < 252 ? 1 : 0;
  }
  const seen = new Uint8Array(mask.length);
  const components = [];
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
    if (area < Math.max(8, width * height * 0.0008)) continue;
    components.push({
      minX, maxX, minY, maxY, area,
      boxWidth: maxX - minX + 1,
      boxHeight: maxY - minY + 1,
    });
  }
  if (!components.length) return null;
  // A bar whose middle is white or grey (e.g. coolwarm) is detected as several
  // stacked blobs, so merge components that line up along the same axis with a
  // small gap between them until nothing more merges.
  let merged = true;
  while (merged) {
    merged = false;
    for (let i = 0; i < components.length; i += 1) {
      for (let j = i + 1; j < components.length; j += 1) {
        const a = components[i];
        const b = components[j];
        const xOverlap = Math.min(a.maxX, b.maxX) - Math.max(a.minX, b.minX);
        const yOverlap = Math.min(a.maxY, b.maxY) - Math.max(a.minY, b.minY);
        const xGap = Math.max(a.minX, b.minX) - Math.min(a.maxX, b.maxX);
        const yGap = Math.max(a.minY, b.minY) - Math.min(a.maxY, b.maxY);
        const verticalNeighbour = xOverlap > -Math.min(a.boxWidth, b.boxWidth) * 0.6 && yGap < 40 && yGap > -30;
        const horizontalNeighbour = yOverlap > -Math.min(a.boxHeight, b.boxHeight) * 0.6 && xGap < 40 && xGap > -30;
        if (verticalNeighbour || horizontalNeighbour) {
          components[i] = {
            minX: Math.min(a.minX, b.minX),
            maxX: Math.max(a.maxX, b.maxX),
            minY: Math.min(a.minY, b.minY),
            maxY: Math.max(a.maxY, b.maxY),
            area: a.area + b.area,
            boxWidth: Math.max(a.maxX, b.maxX) - Math.min(a.minX, b.minX) + 1,
            boxHeight: Math.max(a.maxY, b.maxY) - Math.min(a.minY, b.minY) + 1,
          };
          components.splice(j, 1);
          merged = true;
          break;
        }
      }
      if (merged) break;
    }
  }
  let best = null;
  for (const component of components) {
    const elongation = Math.max(component.boxWidth / Math.max(component.boxHeight, 1), component.boxHeight / Math.max(component.boxWidth, 1));
    const score = component.area * Math.min(elongation, 12);
    if (!best || score > best.score) best = component;
  }
  if (!best) return null;
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

// ---- Tick-label OCR: read the numeric scale printed beside the colorbar ----
// Runs fully in the browser: the tick text is located on one side of the crop,
// split into characters by connected components, and each character is matched
// against locally rendered font templates. Numbers are then re-assembled and
// mapped to the colorbar axis so the minimum/maximum can be filled in.

const TARGET_W = 20;
const TARGET_H = 26;
const GLYPH_SET = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "-", "."];
let glyphTemplates = null;

function ensureGlyphTemplates() {
  if (glyphTemplates) return glyphTemplates;
  const fonts = ["sans-serif", "Arial", "Helvetica", "Tahoma", "Segoe UI", "DejaVu Sans"];
  const all = [];
  for (const font of fonts) {
    for (const glyph of GLYPH_SET) {
      const binary = renderGlyphTemplate(glyph, font);
      if (binary) all.push({ glyph, font, binary });
    }
  }
  const unique = [];
  for (const candidate of all) {
    const duplicate = unique.some((existing) => (
      existing.glyph === candidate.glyph
      && glyphIoU(existing.binary, candidate.binary) > 0.95
    ));
    if (!duplicate) unique.push(candidate);
  }
  glyphTemplates = unique;
  return glyphTemplates;
}

function renderGlyphTemplate(glyph, fontFamily) {
  const side = 48;
  const canvas = document.createElement("canvas");
  canvas.width = side;
  canvas.height = side;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  context.clearRect(0, 0, side, side);
  context.font = `${Math.round(side * 0.6)}px ${fontFamily}`;
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.fillStyle = "#000";
  context.fillText(glyph, side / 2, side / 2 + 1);
  return binaryFromImage(context.getImageData(0, 0, side, side).data, side, side);
}

function binaryFromImage(data, width, height) {
  let minX = width;
  let maxX = -1;
  let minY = height;
  let maxY = -1;
  let count = 0;
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const offset = (y * width + x) * 4;
      const red = data[offset];
      const green = data[offset + 1];
      const blue = data[offset + 2];
      const alpha = data[offset + 3];
      if (alpha > 100 && Math.max(red, green, blue) < 150) {
        count += 1;
        minX = Math.min(minX, x); maxX = Math.max(maxX, x);
        minY = Math.min(minY, y); maxY = Math.max(maxY, y);
      }
    }
  }
  if (count < 3 || maxX < minX || maxY < minY) return null;
  return normalizeBinary(data, width, height, minX, maxX, minY, maxY);
}

function normalizeBinary(data, width, height, minX, maxX, minY, maxY) {
  const boxWidth = maxX - minX + 1;
  const boxHeight = maxY - minY + 1;
  // Contain-scale into the target cell (never wider/taller than the cell) so
  // wide glyphs like a minus sign stay intact instead of overflowing.
  const scale = Math.min(TARGET_H / boxHeight, TARGET_W / boxWidth);
  const targetWidth = Math.max(1, Math.round(boxWidth * scale));
  const targetHeight = Math.max(1, Math.round(boxHeight * scale));
  const out = new Uint8Array(TARGET_W * TARGET_H);
  const offsetX = Math.round((TARGET_W - targetWidth) / 2);
  const offsetY = Math.round((TARGET_H - targetHeight) / 2);
  for (let y = 0; y < targetHeight; y += 1) {
    const sourceY = minY + Math.min(boxHeight - 1, Math.floor(y / scale));
    for (let x = 0; x < targetWidth; x += 1) {
      const sourceX = minX + Math.min(boxWidth - 1, Math.floor(x / scale));
      const offset = (sourceY * width + sourceX) * 4;
      const red = data[offset];
      const green = data[offset + 1];
      const blue = data[offset + 2];
      const alpha = data[offset + 3];
      if (alpha > 100 && Math.max(red, green, blue) < 150) {
        out[(offsetY + y) * TARGET_W + offsetX + x] = 1;
      }
    }
  }
  return { data: out };
}

function glyphIoU(left, right, offsetX = 0, offsetY = 0) {
  let intersection = 0;
  let union = 0;
  for (let y = 0; y < TARGET_H; y += 1) {
    for (let x = 0; x < TARGET_W; x += 1) {
      const sourceX = x + offsetX;
      const sourceY = y + offsetY;
      const inside = sourceX >= 0 && sourceX < TARGET_W && sourceY >= 0 && sourceY < TARGET_H;
      const leftValue = inside ? left.data[sourceY * TARGET_W + sourceX] : 0;
      const rightValue = right.data[y * TARGET_W + x];
      if (leftValue && rightValue) intersection += 1;
      if (leftValue || rightValue) union += 1;
    }
  }
  return union ? intersection / union : 0;
}

function matchGlyph(binary) {
  const templates = ensureGlyphTemplates();
  let best = null;
  for (const template of templates) {
    // Allow a one-pixel shift so slightly misaligned glyphs (sub-pixel font
    // rasterisation differences) still match their template.
    let score = 0;
    for (let offsetY = -1; offsetY <= 1; offsetY += 1) {
      for (let offsetX = -1; offsetX <= 1; offsetX += 1) {
        score = Math.max(score, glyphIoU(binary, template.binary, offsetX, offsetY));
      }
    }
    if (!best || score > best.score) best = { glyph: template.glyph, score };
  }
  return best;
}

function tickTextCandidates() {
  if (!state.loaded || !state.crop) return [];
  const crop = state.crop;
  const search = Math.min(190, Math.max(70, Math.round(Math.max(crop.width, crop.height) * 3.5)));
  const pad = 22;
  const candidates = [];
  // Labels may sit on any side of the bar, so probe all four sides and let the
  // OCR stage pick the side that yields the most valid numbers. This is
  // independent of the crop aspect ratio, which can be misleading.
  const leftW = Math.min(search, crop.x + pad);
  if (crop.x >= 8 || leftW > pad) {
    candidates.push({
      x0: Math.max(0, crop.x - leftW), y0: Math.max(0, crop.y - pad),
      x1: crop.x + pad, y1: Math.min(imageCanvas.height, crop.y + crop.height + pad),
      side: "left",
    });
  }
  const rightW = Math.min(search, imageCanvas.width - crop.x + pad);
  if (crop.x + crop.width + rightW > crop.x + crop.width + 8) {
    candidates.push({
      x0: Math.max(0, crop.x + crop.width - pad), y0: Math.max(0, crop.y - pad),
      x1: Math.min(imageCanvas.width, crop.x + crop.width + rightW), y1: Math.min(imageCanvas.height, crop.y + crop.height + pad),
      side: "right",
    });
  }
  const topH = Math.min(search, crop.y + pad);
  if (crop.y >= 8 || topH > pad) {
    candidates.push({
      x0: Math.max(0, crop.x - pad), y0: Math.max(0, crop.y - topH),
      x1: Math.min(imageCanvas.width, crop.x + crop.width + pad), y1: crop.y + pad,
      side: "top",
    });
  }
  const bottomH = Math.min(search, imageCanvas.height - crop.y + pad);
  if (crop.y + crop.height + bottomH > crop.y + crop.height + 8) {
    candidates.push({
      x0: Math.max(0, crop.x - pad), y0: Math.max(0, crop.y + crop.height - pad),
      x1: Math.min(imageCanvas.width, crop.x + crop.width + pad), y1: Math.min(imageCanvas.height, crop.y + crop.height + bottomH),
      side: "bottom",
    });
  }
  return candidates;
}

function segmentTickCharacters(region) {
  const width = region.x1 - region.x0;
  const height = region.y1 - region.y0;
  const data = imageContext.getImageData(region.x0, region.y0, width, height).data;
  const mask = new Uint8Array(width * height);
  for (let index = 0; index < mask.length; index += 1) {
    const offset = index * 4;
    mask[index] = data[offset + 3] > 100 && Math.max(data[offset], data[offset + 1], data[offset + 2]) < 150 ? 1 : 0;
  }
  const seen = new Uint8Array(mask.length);
  const characters = [];
  for (let seed = 0; seed < mask.length; seed += 1) {
    if (!mask[seed] || seen[seed]) continue;
    const queue = [seed];
    seen[seed] = 1;
    let cursor = 0;
    let count = 0;
    let minX = width;
    let maxX = 0;
    let minY = height;
    let maxY = 0;
    while (cursor < queue.length) {
      const index = queue[cursor++];
      const x = index % width;
      const y = Math.floor(index / width);
      count += 1;
      minX = Math.min(minX, x); maxX = Math.max(maxX, x);
      minY = Math.min(minY, y); maxY = Math.max(maxY, y);
      for (let dy = -1; dy <= 1; dy += 1) {
        for (let dx = -1; dx <= 1; dx += 1) {
          if (!dx && !dy) continue;
          const nx = x + dx;
          const ny = y + dy;
          if (nx < 0 || nx >= width || ny < 0 || ny >= height) continue;
          const next = ny * width + nx;
          if (mask[next] && !seen[next]) {
            seen[next] = 1;
            queue.push(next);
          }
        }
      }
    }
    const boxWidth = maxX - minX + 1;
    const boxHeight = maxY - minY + 1;
    if (count < 3 || boxWidth < 2 || boxHeight < 2) continue;
    if (boxHeight > height * 0.92) continue;
    // Drop border lines and long tick marks: a glyph is roughly square-ish and
    // never spans half the search strip.
    if (boxWidth > width * 0.5 || boxHeight > height * 0.5) continue;
    characters.push({ minX, minY, boxWidth, boxHeight, count });
  }
  return characters;
}

function readTicksFromRegion(region) {
  const characters = segmentTickCharacters(region);
  const recognized = [];
  for (const character of characters) {
    const data = imageContext.getImageData(
      region.x0 + character.minX,
      region.y0 + character.minY,
      character.boxWidth,
      character.boxHeight,
    ).data;
    const binary = binaryFromImage(data, character.boxWidth, character.boxHeight);
    if (!binary) continue;
    const match = matchGlyph(binary);
    if (match && match.score > 0.46) recognized.push({ ...character, glyph: match.glyph });
  }
  if (!recognized.length) return { ticks: [], side: region.side };
  const vertical = region.side === "left" || region.side === "right";
  // For a vertical colorbar the numbers are stacked one row per tick, so group
  // by vertical position; for a horizontal one they sit side by side, so group
  // by horizontal position. Within a group the glyphs are then read left to
  // right (vertical colorbar) or top to bottom (horizontal colorbar).
  recognized.sort((a, b) => (vertical
    ? (a.minY - b.minY) || (a.minX - b.minX)
    : (a.minX - b.minX) || (a.minY - b.minY)));
  const groups = [];
  let current = null;
  for (const character of recognized) {
    if (!current) {
      current = [character];
      groups.push(current);
      continue;
    }
    const last = current[current.length - 1];
    const gap = vertical
      ? character.minY - (last.minY + last.boxHeight)
      : character.minX - (last.minX + last.boxWidth);
    if (gap <= 10) {
      current.push(character);
    } else {
      current = [character];
      groups.push(current);
    }
  }
  const ticks = [];
  for (const group of groups) {
    group.sort((a, b) => (vertical ? a.minX - b.minX : a.minY - b.minY));
    let text = group.map((character) => character.glyph).join("");
    // A minus that is not at the start of a tick is a decimal point, which is
    // too small to be told apart from a minus reliably.
    if (text.includes("-") && !text.startsWith("-")) text = text.replace(/-/g, ".");
    const value = parseFloat(text);
    if (!Number.isFinite(value)) continue;
    const centerY = group.reduce((sum, character) => sum + character.minY + character.boxHeight / 2, 0) / group.length;
    const centerX = group.reduce((sum, character) => sum + character.minX + character.boxWidth / 2, 0) / group.length;
    const position = vertical
      ? (region.y0 + centerY - state.crop.y) / state.crop.height
      : (region.x0 + centerX - state.crop.x) / state.crop.width;
    ticks.push({ value, position: clamp(position, 0, 1), text });
  }
  const seenValues = new Set();
  const uniqueTicks = ticks.filter((tick) => !seenValues.has(tick.value) && seenValues.add(tick.value));
  uniqueTicks.sort((a, b) => a.value - b.value);
  return { ticks: uniqueTicks, side: region.side };
}

function readTicks() {
  if (!state.loaded || !state.crop) return { ticks: [], side: null };
  const candidates = tickTextCandidates();
  if (!candidates.length) return { ticks: [], side: null };
  // Try every side and keep the one that yields the most valid numbers. Dark
  // pixel counts alone are unreliable because border lines are dark too.
  let best = null;
  for (const region of candidates) {
    const result = readTicksFromRegion(region);
    if (result.ticks.length > 0 && (!best || result.ticks.length > best.ticks.length)) best = result;
  }
  return best || { ticks: [], side: null };
}

function applyReadTicks() {
  const result = readTicks();
  if (!result.ticks.length) {
    ticksNote.textContent = "未识别到刻度数字；可手动输入最小/最大值。";
    return;
  }
  const values = result.ticks.map((tick) => tick.value);
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  minimumInput.value = minimum;
  maximumInput.value = maximum;
  const sideText = { left: "左侧", right: "右侧", top: "上方", bottom: "下方" }[result.side] || "";
  ticksNote.textContent = `${sideText}识别到刻度：${result.ticks.map((tick) => tick.text).join(", ")} → 自动填入 ${minimum} ~ ${maximum}。`;
  generatePalette();
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
ticksButton.addEventListener("click", applyReadTicks);
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
