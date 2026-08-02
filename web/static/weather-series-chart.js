(() => {
  const NS = "http://www.w3.org/2000/svg";
  const WIDTH = 1600;
  const HEIGHT = 930;

  function node(name, attributes = {}, text = "") {
    const element = document.createElementNS(NS, name);
    for (const [key, value] of Object.entries(attributes)) {
      element.setAttribute(key, String(value));
    }
    if (text !== "") element.textContent = text;
    return element;
  }

  function number(value) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }

  function format(value, digits = 1) {
    const parsed = number(value);
    return parsed === null ? "—" : parsed.toFixed(digits);
  }

  function extent(values, minimumSpan = 1) {
    const finite = values.map(number).filter((value) => value !== null);
    if (!finite.length) return [0, minimumSpan];
    const low = Math.min(...finite);
    const high = Math.max(...finite);
    const span = Math.max(high - low, minimumSpan);
    return [low - span * 0.18, high + span * 0.2];
  }

  function linePath(points, key, x, y) {
    let started = false;
    return points.map((point, index) => {
      const value = number(point[key]);
      if (value === null) {
        started = false;
        return "";
      }
      const command = started ? "L" : "M";
      started = true;
      return `${command}${x(index).toFixed(1)},${y(value).toFixed(1)}`;
    }).join(" ");
  }

  function apparentTemperature(temperature, humidity) {
    const t = number(temperature);
    const rh = number(humidity);
    if (t === null || rh === null) return null;
    if (t < 26) return t;
    const fahrenheit = t * 9 / 5 + 32;
    const heatIndex = -42.379 + 2.04901523 * fahrenheit + 10.14333127 * rh
      - 0.22475541 * fahrenheit * rh - 0.00683783 * fahrenheit ** 2
      - 0.05481717 * rh ** 2 + 0.00122874 * fahrenheit ** 2 * rh
      + 0.00085282 * fahrenheit * rh ** 2
      - 0.00000199 * fahrenheit ** 2 * rh ** 2;
    return (heatIndex - 32) * 5 / 9;
  }

  function humidityColour(humidity) {
    const ratio = Math.max(0, Math.min(1, (number(humidity) ?? 0) / 100));
    const start = [255, 89, 0];
    const end = [62, 232, 210];
    const rgb = start.map((value, index) => Math.round(value + (end[index] - value) * ratio));
    return `rgb(${rgb.join(",")})`;
  }

  function precipitationColour(total) {
    if (total <= 9.9) return "#acebbf";
    if (total <= 24.9) return "#57d875";
    if (total <= 49.9) return "#1a9e2d";
    if (total <= 99.9) return "#097000";
    if (total <= 249.9) return "#740086";
    return "#e700e0";
  }

  function timeLabel(value, includeDate = false) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "—";
    return new Intl.DateTimeFormat("zh-CN", {
      month: includeDate ? "2-digit" : undefined,
      day: includeDate ? "2-digit" : undefined,
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
      timeZone: "Asia/Shanghai",
    }).format(date);
  }

  function dateLabel(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "—";
    return new Intl.DateTimeFormat("zh-CN", {
      month: "2-digit", day: "2-digit", timeZone: "Asia/Shanghai",
    }).format(date);
  }

  function addHumidityBar(svg) {
    const definitions = node("defs");
    const gradient = node("linearGradient", { id: "humidity-gradient", x1: 0, y1: 1, x2: 0, y2: 0 });
    gradient.append(
      node("stop", { offset: "0%", "stop-color": "#ff5900" }),
      node("stop", { offset: "100%", "stop-color": "#3ee8d2" }),
    );
    definitions.append(gradient);
    svg.append(definitions);
    svg.append(node("rect", { x: 34, y: 112, width: 34, height: 696, fill: "url(#humidity-gradient)", stroke: "#111", "stroke-width": 1 }));
    for (let value = 0; value <= 100; value += 20) {
      const y = 808 - value / 100 * 696;
      svg.append(
        node("line", { x1: 68, x2: 76, y1: y, y2: y, stroke: "#111" }),
        node("text", { x: 80, y: y + 5, "font-size": 14, fill: "#111" }, String(value)),
      );
    }
    svg.append(node("text", { x: 50, y: 95, "text-anchor": "middle", "font-size": 14 }, "湿度(%)"));
  }

  function addLegends(svg) {
    const x = 1460;
    const entries = [["#ef1f1f", "温度"], ["#f39a17", "体感温度"]];
    entries.forEach(([colour, label], index) => {
      const y = 230 + index * 28;
      svg.append(
        node("line", { x1: x, x2: x + 34, y1: y, y2: y, stroke: colour, "stroke-width": 4 }),
        node("text", { x: x + 44, y: y + 5, "font-size": 15 }, label),
      );
    });
    const rain = [
      ["#acebbf", "小雨"], ["#57d875", "中雨"], ["#1a9e2d", "大雨"],
      ["#097000", "暴雨"], ["#740086", "大暴雨"], ["#e700e0", "特大暴雨"],
    ];
    rain.forEach(([colour, label], index) => {
      const y = 330 + index * 29;
      svg.append(
        node("rect", { x, y: y - 14, width: 32, height: 17, fill: colour }),
        node("text", { x: x + 44, y, "font-size": 15 }, label),
      );
    });
  }

  function addWindArrow(svg, x, y, direction, speed) {
    const windDirection = number(direction);
    const windSpeed = number(speed);
    if (windSpeed === null || windSpeed < 0.15 || windDirection === null) {
      svg.append(node("circle", { cx: x, cy: y, r: 3.2, fill: "#8e9799" }));
      return;
    }
    svg.append(node("path", {
      d: "M0,-15 L-6,8 L0,4 L6,8 Z",
      fill: "#ed1c24",
      transform: `translate(${x} ${y}) rotate(${windDirection + 180})`,
    }));
  }

  function addInspection(svg, points, x, plot) {
    const group = node("g", { visibility: "hidden", "pointer-events": "none" });
    const line = node("line", { y1: plot.top, y2: plot.windBottom, stroke: "#176f9e", "stroke-width": 1.2, "stroke-dasharray": "5 5" });
    const box = node("rect", { width: 310, height: 87, fill: "#fff", stroke: "#333", "stroke-width": 1, opacity: 0.97 });
    const labels = [0, 1, 2, 3].map((index) => node("text", { "font-size": index === 0 ? 15 : 13, "font-weight": index === 0 ? 650 : 400, fill: "#111" }));
    group.append(line, box, ...labels);
    svg.append(group);
    const overlay = node("rect", { x: plot.left, y: plot.top, width: plot.right - plot.left, height: plot.windBottom - plot.top, fill: "transparent", cursor: "crosshair" });
    const inspect = (event) => {
      const pointer = svg.createSVGPoint();
      pointer.x = event.clientX;
      pointer.y = event.clientY;
      const local = pointer.matrixTransform(svg.getScreenCTM().inverse());
      const index = Math.max(0, Math.min(points.length - 1, Math.round((local.x - plot.left) / (plot.right - plot.left) * (points.length - 1))));
      const item = points[index];
      const px = x(index);
      const boxX = px > 1120 ? px - 320 : px + 10;
      const boxY = Math.max(plot.top + 8, Math.min(local.y - 38, plot.windBottom - 95));
      line.setAttribute("x1", px); line.setAttribute("x2", px);
      box.setAttribute("x", boxX); box.setAttribute("y", boxY);
      labels.forEach((label, labelIndex) => {
        label.setAttribute("x", boxX + 12);
        label.setAttribute("y", boxY + 20 + labelIndex * 19);
      });
      labels[0].textContent = timeLabel(item.time, true);
      labels[1].textContent = `温度 ${format(item.temperature)}°C  露点 ${format(item.dewpoint)}°C  湿度 ${format(item.humidity, 0)}%`;
      labels[2].textContent = `体感 ${format(item.apparent)}°C  气压 ${format(item.pressure)} hPa`;
      labels[3].textContent = `降水 ${format(item.precipitation)} mm  风 ${format(item.windSpeed)} m/s / ${format(item.windDirection, 0)}°`;
      group.setAttribute("visibility", "visible");
    };
    overlay.addEventListener("pointerenter", inspect);
    overlay.addEventListener("pointermove", inspect);
    overlay.addEventListener("pointerdown", inspect);
    overlay.addEventListener("pointerleave", () => group.setAttribute("visibility", "hidden"));
    svg.append(overlay);
  }

  function render(svg, configuration) {
    const started = performance.now();
    const points = (configuration.points || []).map((point) => ({
      ...point,
      apparent: number(point.apparent) ?? apparentTemperature(point.temperature, point.humidity),
    }));
    if (!points.length) return null;
    svg.setAttribute("viewBox", `0 0 ${WIDTH} ${HEIGHT}`);
    svg.replaceChildren(node("rect", { width: WIDTH, height: HEIGHT, fill: "#fff" }));

    const plot = { left: 205, right: 1405, top: 112, bottom: 640, windTop: 690, windBottom: 840 };
    const x = (index) => plot.left + index / Math.max(points.length - 1, 1) * (plot.right - plot.left);
    const title = configuration.title || "24h实况序列";
    svg.append(
      node("text", { x: WIDTH / 2, y: 49, "text-anchor": "middle", "font-size": 31, "font-weight": 650, fill: "#111" }, title),
      node("text", { x: 18, y: 31, "font-size": 16, fill: "#111" }, configuration.locationLine || ""),
      node("text", { x: 18, y: 54, "font-size": 15, fill: "#111" }, configuration.timeLine || ""),
      node("text", { x: 1578, y: 35, "text-anchor": "end", "font-size": 17, fill: "#111" }, "By @CloudyLake"),
      node("text", { x: 1578, y: 57, "text-anchor": "end", "font-size": 14, fill: "#111" }, "Version: 2.1.1"),
    );

    const rain = points.map((point) => Math.max(0, number(point.precipitation) ?? 0));
    const tailSum = (count) => rain.slice(-count).reduce((sum, value) => sum + value, 0);
    svg.append(node("text", { x: 1402, y: 24, "text-anchor": "end", "font-size": 12.5, fill: "#111" }, configuration.accumulationLines?.[0] || `近6时段累计降水量: ${tailSum(6).toFixed(1)} mm`));
    svg.append(node("text", { x: 1402, y: 42, "text-anchor": "end", "font-size": 12.5, fill: "#111" }, configuration.accumulationLines?.[1] || `近12时段累计降水量: ${tailSum(12).toFixed(1)} mm`));
    svg.append(node("text", { x: 1402, y: 60, "text-anchor": "end", "font-size": 12.5, fill: "#111" }, configuration.accumulationLines?.[2] || `全时段累计降水量: ${tailSum(points.length).toFixed(1)} mm`));

    addHumidityBar(svg);
    addLegends(svg);
    svg.append(
      node("rect", { x: plot.left, y: plot.top, width: plot.right - plot.left, height: plot.bottom - plot.top, fill: "none", stroke: "#222" }),
      node("rect", { x: plot.left, y: plot.windTop, width: plot.right - plot.left, height: plot.windBottom - plot.windTop, fill: "none", stroke: "#222" }),
    );

    points.forEach((point, index) => {
      svg.append(node("line", { x1: x(index), x2: x(index), y1: plot.top, y2: plot.windBottom, stroke: "#a9dce8", "stroke-width": 1.4, "stroke-dasharray": "3 5" }));
    });

    const temperatures = points.flatMap((point) => [point.temperature, point.dewpoint, point.apparent]);
    const [temperatureMin, temperatureMax] = extent(temperatures, 4);
    const yTemperature = (value) => 430 - (value - temperatureMin) / (temperatureMax - temperatureMin) * 275;
    for (let index = 0; index <= 4; index += 1) {
      const value = temperatureMin + index / 4 * (temperatureMax - temperatureMin);
      const y = yTemperature(value);
      svg.append(
        node("line", { x1: plot.left, x2: plot.right, y1: y, y2: y, stroke: "#e3e3e3", "stroke-width": 0.8 }),
        node("text", { x: plot.left - 12, y: y + 5, "text-anchor": "end", "font-size": 14 }, value.toFixed(0)),
      );
    }
    svg.append(node("text", { x: 160, y: 370, transform: "rotate(-90 160 370)", "text-anchor": "middle", "font-size": 15 }, "实况温度(°C)"));

    svg.append(
      node("path", { d: linePath(points, "apparent", x, yTemperature), fill: "none", stroke: "#f39a17", "stroke-width": 2.5 }),
      node("path", { d: linePath(points, "temperature", x, yTemperature), fill: "none", stroke: "#ef1f1f", "stroke-width": 3 }),
    );
    points.forEach((point, index) => {
      const temperature = number(point.temperature);
      const apparent = number(point.apparent);
      const dewpoint = number(point.dewpoint);
      if (apparent !== null) {
        svg.append(node("circle", { cx: x(index), cy: yTemperature(apparent), r: 9, fill: humidityColour(point.humidity), opacity: 0.93 }));
        svg.append(node("text", { x: x(index), y: 100, "text-anchor": "middle", "font-size": 12.5 }, format(point.humidity, 0)));
        svg.append(node("text", { x: x(index), y: 119, "text-anchor": "middle", "font-size": 12.5 }, format(apparent, 1)));
      }
      if (temperature !== null) {
        svg.append(
          node("circle", { cx: x(index), cy: yTemperature(temperature), r: 4.2, fill: "#ef1f1f" }),
          node("text", { x: x(index), y: yTemperature(temperature) - 10, "text-anchor": "middle", "font-size": 12.5 }, format(temperature, 1)),
        );
      }
      if (dewpoint !== null) {
        svg.append(node("text", { x: x(index), y: yTemperature(dewpoint) + 19, "text-anchor": "middle", "font-size": 12.5 }, format(dewpoint, 1)));
      }
    });
    svg.append(
      node("text", { x: plot.left - 10, y: 100, "text-anchor": "end", "font-size": 13 }, "湿度(%):"),
      node("text", { x: plot.left - 10, y: 119, "text-anchor": "end", "font-size": 13 }, "体感温度(°C):"),
      node("text", { x: plot.left + 4, y: yTemperature(number(points[0].temperature) ?? 0) - 32, "font-size": 13 }, "温度(°C)"),
      node("text", { x: plot.left + 4, y: yTemperature(number(points[0].dewpoint) ?? 0) + 39, "font-size": 13 }, "露点温度(°C)"),
    );

    const pressures = points.map((point) => number(point.pressure)).filter((value) => value !== null);
    const [pressureMin, pressureMax] = extent(pressures, 2);
    const yPressure = (value) => 570 - (value - pressureMin) / (pressureMax - pressureMin) * 85;
    let pressureArea = `M${x(0)},610 `;
    points.forEach((point, index) => {
      const value = number(point.pressure);
      pressureArea += value === null ? "" : `L${x(index)},${yPressure(value)} `;
    });
    pressureArea += `L${x(points.length - 1)},610 Z`;
    svg.append(node("path", { d: pressureArea, fill: "#dbdbff", opacity: 0.88 }));
    points.forEach((point, index) => {
      const value = number(point.pressure);
      if (value !== null) svg.append(node("text", { x: x(index), y: yPressure(value) - 4, "text-anchor": "middle", "font-size": 11.5 }, format(value, 1)));
      const seaLevel = number(point.seaLevelPressure);
      if (seaLevel !== null) svg.append(node("text", { x: x(index), y: yPressure(value ?? pressureMin) + 14, "text-anchor": "middle", "font-size": 10.5, fill: "#415d91" }, format(seaLevel, 1)));
    });

    const rainMaximum = Math.max(...rain, 0.1);
    const rainBarWidth = Math.max(8, (plot.right - plot.left) / points.length * 0.78);
    let cumulativeRain = 0;
    points.forEach((point, index) => {
      cumulativeRain += rain[index];
      const height = rain[index] / rainMaximum * 112;
      if (height > 0) svg.append(node("rect", { x: x(index) - rainBarWidth / 2, y: 620 - height, width: rainBarWidth, height, fill: precipitationColour(cumulativeRain) }));
      svg.append(node("text", { x: x(index), y: 633, "text-anchor": "middle", "font-size": 11.5 }, format(rain[index], 1)));
    });
    svg.append(node("text", { x: plot.left - 8, y: 633, "text-anchor": "end", "font-size": 13 }, "降水量(mm):"));

    const wind = points.map((point) => number(point.windSpeed) ?? 0);
    const windMaximum = Math.max(...wind, 1);
    const yWind = (value) => 810 - value / windMaximum * 84;
    svg.append(
      node("line", { x1: plot.left, x2: plot.right, y1: 810, y2: 810, stroke: "#111", "stroke-width": 1, "stroke-dasharray": "5 4" }),
      node("path", { d: linePath(points, "windSpeed", x, yWind), fill: "none", stroke: "#a9dce8", "stroke-width": 2.3 }),
      node("text", { x: 160, y: 770, transform: "rotate(-90 160 770)", "text-anchor": "middle", "font-size": 15 }, "风速(m/s)"),
    );
    points.forEach((point, index) => {
      const speed = number(point.windSpeed) ?? 0;
      addWindArrow(svg, x(index), yWind(speed), point.windDirection, speed);
      svg.append(
        node("text", { x: x(index), y: yWind(speed) - 18, "text-anchor": "middle", "font-size": 11.5 }, format(speed, 1)),
        node("text", { x: x(index), y: 866, "text-anchor": "middle", "font-size": points.length > 24 ? 10.5 : 12.5 }, timeLabel(point.time, false)),
      );
      if (configuration.includeDateLabels) {
        const previousDate = index ? dateLabel(points[index - 1].time) : null;
        const currentDate = dateLabel(point.time);
        if (index === 0 || currentDate !== previousDate) {
          svg.append(node("text", {
            x: x(index), y: 890, "text-anchor": index === 0 ? "start" : "middle",
            "font-size": 12.5, "font-weight": 650, fill: "#315d73",
          }, currentDate));
        }
      }
    });
    svg.append(node("text", { x: plot.left - 8, y: 866, "text-anchor": "end", "font-size": 13 }, "时次:"));
    addInspection(svg, points, x, plot);
    return performance.now() - started;
  }

  window.CloudyLakeWeatherSeriesRenderer = { render, apparentTemperature };
})();
