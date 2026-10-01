/**
 * hp2530 faceplate card
 *
 * Adapted from netviz-faceplate-card.js in https://github.com/gun4as/HP-HA
 * Copyright (c) 2026 gun4as, MIT License (see LICENSE in this repository).
 * Changes: entities come from the hp2530 integration, link speed is read from
 * the link entity's attributes, PoE faults are drawn, wireless is removed.
 *
 * Geometry comes from the faceplate sensor's attributes and live state from
 * the other entities of the same device. Ports are matched by their `port` and
 * `metric` attributes, not by entity_id, so renaming an entity breaks nothing.
 *
 * Lovelace:
 *   type: custom:hp2530-faceplate-card
 *   device: <device_id>          # or:
 *   faceplate: sensor.my_switch_faceplate
 *   title: Rack switch           # optional
 *   min_width: 900               # optional: full size with a scrollbar
 */

const PLATFORM = "hp2530";

// The PoE dot must not rely on hue alone, so it carries a dark outline that
// reads on green, amber and grey alike.
const POE_COLOR = "#ff6d00";
const POE_FAULT_COLOR = "#e53935";
const POE_OUTLINE = "rgba(0,0,0,0.75)";
const POE_DOT_R = 2.6; // in the corner, next to the number
const POE_DOT_R_BIG = 4.5; // centred, once the numbers are hidden

const LABEL_FONT_SIZE = 8;
// Below this rendered size the port numbers are illegible: hide them and keep
// the colours and the tooltip.
const LABEL_MIN_PX = 5.5;

const LINK_COLORS = {
  down: "var(--disabled-color, #6f7378)",
  10: "#f2b632",
  100: "#f2b632",
  1000: "#3ec46d",
  10000: "#2ea3f2",
};

const POE_FAULTS = new Set(["fault", "other_fault"]);

const STATUS_TEXT = {
  disabled: "PoE disabled",
  fault: "PoE fault",
  other_fault: "PoE fault (other)",
  test: "PoE test",
};

class Hp2530FaceplateCard extends HTMLElement {
  setConfig(config) {
    if (!config.device && !config.faceplate) {
      throw new Error("Set either 'device' or a 'faceplate' entity");
    }
    this._config = config;
    this._built = false;
    this.innerHTML = "";
  }

  getCardSize() {
    return 4;
  }

  set hass(hass) {
    this._hass = hass;
    const faceplate = this._findFaceplate();
    if (!faceplate) {
      this._renderError("Faceplate entity not found");
      return;
    }
    const geometry = faceplate.attributes;
    if (!geometry.ports || !geometry.ports.length) {
      this._renderError("No ports in the faceplate attributes");
      return;
    }
    if (!this._built || this._geometryId !== faceplate.entity_id) {
      this._build(geometry, faceplate.entity_id);
    }
    this._update();
  }

  _findFaceplate() {
    const hass = this._hass;
    if (this._config.faceplate) {
      return hass.states[this._config.faceplate];
    }
    for (const entry of Object.values(hass.entities || {})) {
      if (entry.platform !== PLATFORM || entry.device_id !== this._config.device) continue;
      const state = hass.states[entry.entity_id];
      if (state && state.attributes && state.attributes.ports) return state;
    }
    return undefined;
  }

  /**
   * {port_id: {metric: entity_id}}, cached.
   *
   * `set hass` runs on every state change in the house, so the registry scan
   * is cached until the registry itself changes. A partial map is never
   * cached: at startup some states have not arrived yet.
   */
  _entityMap() {
    const hass = this._hass;
    const wanted = Object.keys(this._portNodes || {});
    if (
      this._map &&
      this._mapSource === hass.entities &&
      wanted.every((key) => this._map[key])
    ) {
      return this._map;
    }
    const deviceId =
      this._config.device || (hass.entities[this._faceplateId] || {}).device_id;
    const map = {};
    for (const entry of Object.values(hass.entities || {})) {
      if (entry.platform !== PLATFORM) continue;
      if (deviceId && entry.device_id !== deviceId) continue;
      const state = hass.states[entry.entity_id];
      const { port, metric } = (state && state.attributes) || {};
      if (!port || !metric) continue;
      if (!map[port]) map[port] = {};
      map[port][metric] = entry.entity_id;
    }
    if (wanted.length && wanted.every((key) => map[key])) {
      this._mapSource = hass.entities;
      this._map = map;
    }
    return map;
  }

  _portStates() {
    const hass = this._hass;
    const grouped = {};
    for (const [port, metrics] of Object.entries(this._entityMap())) {
      for (const [metric, entityId] of Object.entries(metrics)) {
        const state = hass.states[entityId];
        if (!state) continue;
        if (!grouped[port]) grouped[port] = {};
        grouped[port][metric] = state;
      }
    }
    return grouped;
  }

  _build(geometry, faceplateId) {
    const svgNs = "http://www.w3.org/2000/svg";
    this._faceplateId = faceplateId;
    this._geometryId = faceplateId;
    this._errorShown = null;
    this._map = null;
    this._mapSource = null;
    const width = geometry.width || 800;
    const height = geometry.height || 100;

    const card = document.createElement("ha-card");
    if (this._config.title || geometry.display) {
      card.header = this._config.title || geometry.display;
    }

    const minWidth = Number(this._config.min_width) || 0;
    const wrap = document.createElement("div");
    wrap.style.cssText = "padding:12px 16px 16px" + (minWidth ? ";overflow-x:auto" : "");

    const svg = document.createElementNS(svgNs, "svg");
    svg.setAttribute("viewBox", geometry.viewbox || `0 0 ${width} ${height}`);
    svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
    // Scale down to fit, but never blow a small faceplate up past 1.4x
    svg.style.cssText =
      "width:100%;height:auto;display:block;margin:0 auto" +
      (minWidth ? `;min-width:${minWidth}px` : `;max-width:${Math.round(width * 1.4)}px`);
    this._viewBoxWidth = width;
    this._labels = [];

    const chassis = document.createElementNS(svgNs, "rect");
    chassis.setAttribute("x", "4");
    chassis.setAttribute("y", "4");
    chassis.setAttribute("width", String(width - 8));
    chassis.setAttribute("height", String(height - 8));
    chassis.setAttribute("rx", "6");
    chassis.setAttribute("fill", "var(--card-background-color, #1c1c1c)");
    chassis.setAttribute("stroke", "var(--divider-color, #444)");
    chassis.setAttribute("stroke-width", "1.5");
    svg.appendChild(chassis);

    this._portNodes = {};
    for (const port of geometry.ports) {
      const group = document.createElementNS(svgNs, "g");
      group.style.cursor = "pointer";

      const body = document.createElementNS(svgNs, "rect");
      body.setAttribute("x", port.x);
      body.setAttribute("y", port.y);
      body.setAttribute("width", port.w);
      body.setAttribute("height", port.h);
      body.setAttribute("rx", port.kind === "sfp" ? "2" : "3");
      body.setAttribute("stroke", "var(--divider-color, #555)");
      body.setAttribute("stroke-width", "1");
      group.appendChild(body);

      let poeDot = null;
      if (port.poe) {
        poeDot = document.createElementNS(svgNs, "circle");
        poeDot.setAttribute("fill", "transparent");
        poeDot.setAttribute("stroke", "transparent");
        poeDot.setAttribute("stroke-width", "0.8");
        poeDot.setAttribute("pointer-events", "none");
        group.appendChild(poeDot);
      }

      const label = document.createElementNS(svgNs, "text");
      label.setAttribute("x", Number(port.x) + Number(port.w) / 2);
      label.setAttribute("y", Number(port.y) + Number(port.h) / 2 + 3);
      label.setAttribute("text-anchor", "middle");
      label.setAttribute("font-size", String(LABEL_FONT_SIZE));
      label.setAttribute("fill", "var(--primary-text-color, #eee)");
      label.setAttribute("pointer-events", "none");
      label.textContent = port.label;
      group.appendChild(label);
      this._labels.push(label);

      const tooltip = document.createElementNS(svgNs, "title");
      group.appendChild(tooltip);

      group.addEventListener("click", () => this._openPort(port.id));
      svg.appendChild(group);
      this._portNodes[port.id] = { body, poeDot, tooltip, def: port };
    }
    wrap.appendChild(svg);

    const swatch = (color, text, round) =>
      `<span style="display:inline-flex;align-items:center;gap:5px">` +
      `<span style="width:10px;height:10px;border-radius:${round ? "50%" : "2px"};` +
      `background:${color}${round ? `;box-shadow:0 0 0 1px ${POE_OUTLINE}` : ""}"></span>` +
      `${text}</span>`;
    const legend = document.createElement("div");
    legend.style.cssText =
      "display:flex;gap:14px;flex-wrap:wrap;padding-top:10px;" +
      "font-size:12px;color:var(--secondary-text-color)";
    legend.innerHTML =
      swatch("#3ec46d", "1G") +
      swatch("#f2b632", "10/100M") +
      swatch("var(--disabled-color,#6f7378)", "down") +
      swatch(POE_COLOR, "PoE", true) +
      swatch(POE_FAULT_COLOR, "PoE fault", true);
    wrap.appendChild(legend);

    this._summary = document.createElement("div");
    this._summary.style.cssText = "padding-top:6px;font-size:12px;color:var(--secondary-text-color)";
    wrap.appendChild(this._summary);

    card.appendChild(wrap);
    this.innerHTML = "";
    this.appendChild(card);
    this._applyPoeDotLayout(true);
    this._observeLabels(svg);
    this._built = true;
  }

  _observeLabels(svg) {
    const apply = () => {
      const rendered = svg.clientWidth || svg.getBoundingClientRect().width;
      if (!rendered || !this._viewBoxWidth) return;
      const show = (LABEL_FONT_SIZE * rendered) / this._viewBoxWidth >= LABEL_MIN_PX;
      if (show === this._labelsShown) return;
      this._labelsShown = show;
      for (const label of this._labels) label.style.display = show ? "" : "none";
      this._applyPoeDotLayout(show);
    };
    this._labelsShown = undefined;
    if (this._resizeObserver) this._resizeObserver.disconnect();
    if (typeof ResizeObserver === "function") {
      this._resizeObserver = new ResizeObserver(apply);
      this._resizeObserver.observe(svg);
    }
    apply();
  }

  /** With the numbers hidden the dot moves to the centre and grows. */
  _applyPoeDotLayout(labelsShown) {
    for (const node of Object.values(this._portNodes || {})) {
      if (!node.poeDot) continue;
      const p = node.def;
      const x = Number(p.x);
      const y = Number(p.y);
      node.poeDot.setAttribute("cx", labelsShown ? x + Number(p.w) - 4 : x + Number(p.w) / 2);
      node.poeDot.setAttribute("cy", labelsShown ? y + Number(p.h) - 4 : y + Number(p.h) / 2);
      node.poeDot.setAttribute("r", String(labelsShown ? POE_DOT_R : POE_DOT_R_BIG));
    }
  }

  disconnectedCallback() {
    if (this._resizeObserver) {
      this._resizeObserver.disconnect();
      this._resizeObserver = null;
    }
  }

  _update() {
    const states = this._portStates();
    let up = 0;
    let poeTotal = 0;
    let faults = 0;

    for (const [portId, node] of Object.entries(this._portNodes)) {
      const metrics = states[portId] || {};
      const link = metrics.link;
      const attrs = (link && link.attributes) || {};
      const isUp = link && link.state === "on";
      if (isUp) up += 1;

      const speed = Number(attrs.speed) || 0;
      node.body.setAttribute(
        "fill",
        isUp ? LINK_COLORS[speed] || LINK_COLORS[1000] : LINK_COLORS.down
      );

      const status = metrics.poe_status ? metrics.poe_status.state : undefined;
      const watts = metrics.poe_power ? Number(metrics.poe_power.state) : NaN;
      if (node.poeDot) {
        const fault = POE_FAULTS.has(status);
        const on = fault || status === "delivering" || watts > 0;
        if (fault) faults += 1;
        node.poeDot.setAttribute("fill", on ? (fault ? POE_FAULT_COLOR : POE_COLOR) : "transparent");
        node.poeDot.setAttribute("stroke", on ? POE_OUTLINE : "transparent");
      }
      if (!Number.isNaN(watts)) poeTotal += watts;

      const label = attrs.label || (metrics.poe_power || {}).attributes?.label;
      const lines = [`Port ${node.def.label}`];
      if (label && label !== `Port ${node.def.label}`) lines.push(label);
      lines.push(isUp ? `up ${speed} Mbit/s` : "down");
      if (metrics.rx_rate && metrics.tx_rate) {
        lines.push(`RX ${metrics.rx_rate.state} / TX ${metrics.tx_rate.state} Mbit/s`);
      }
      if (watts > 0) lines.push(`PoE ${watts.toFixed(1)} W`);
      if (STATUS_TEXT[status]) lines.push(STATUS_TEXT[status]);
      if (attrs.neighbor_port) lines.push(`via ${attrs.neighbor_port}`);
      node.tooltip.textContent = lines.join(" · ");
    }

    const total = Object.keys(this._portNodes).length;
    this._summary.textContent =
      `${up}/${total} up` +
      (poeTotal > 0 ? ` · PoE ${poeTotal.toFixed(1)} W` : "") +
      (faults ? ` · ${faults} PoE fault${faults === 1 ? "" : "s"}` : "");
  }

  /** Clicking a port opens the more-info dialog of its link entity. */
  _openPort(portId) {
    const states = this._portStates()[portId];
    if (!states) return;
    const target = states.link || Object.values(states)[0];
    if (!target) return;
    const event = new Event("hass-more-info", { bubbles: true, composed: true });
    event.detail = { entityId: target.entity_id };
    this.dispatchEvent(event);
  }

  _renderError(message) {
    if (this._errorShown === message) return;
    this._errorShown = message;
    this.innerHTML = `<ha-card><div style="padding:16px;color:var(--error-color)">${message}</div></ha-card>`;
    this._built = false;
  }
}

customElements.define("hp2530-faceplate-card", Hp2530FaceplateCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "hp2530-faceplate-card",
  name: "HP 2530 faceplate",
  description: "Switch front panel with link, speed and PoE state",
  preview: false,
});
