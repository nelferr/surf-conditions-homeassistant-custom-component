/* Surf Conditions card: a coloured square for every hour of light, one row per day.
   Tap a square to see that hour's rating and what holds it back. */

const HOUR = 3600000;
const RATINGS = ["great", "good", "flat", "bad", "terrible"];
const WORDS = {
  great: "Great",
  good: "Good",
  flat: "Flat",
  bad: "Bad",
  terrible: "Terrible",
  dark: "Dark",
};

const STYLE = `
  :host { display: block; }
  .content { padding: 0 16px 16px; }
  .content.bare { padding-top: 16px; }
  .note { color: var(--secondary-text-color); }

  .strip {
    display: grid;
    grid-template-columns: max-content repeat(var(--columns), minmax(0, 1fr));
    gap: 4px 2px;
    align-items: center;
  }
  .label {
    font-size: 10px;
    line-height: 14px;
    text-align: center;
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
    color: var(--secondary-text-color);
  }
  .day {
    padding-right: 6px;
    font-size: 12px;
    font-weight: 500;
    white-space: nowrap;
    color: var(--secondary-text-color);
  }
  button.hour {
    position: relative;
    box-sizing: border-box;
    width: 100%;
    max-width: 30px;
    aspect-ratio: 1;
    justify-self: center;
    margin: 0;
    padding: 0;
    border: 0;
    border-radius: 4px;
    background: var(--color);
    cursor: pointer;
    -webkit-tap-highlight-color: transparent;
  }
  /* A slightly bigger target for fingers than the square itself. */
  button.hour::before { content: ""; position: absolute; inset: -3px -1px; }
  button.hour.past { opacity: 0.4; }
  button.hour.now::after {
    content: "";
    position: absolute;
    inset: 0;
    width: 34%;
    height: 34%;
    margin: auto;
    border-radius: 50%;
    background: var(--card-background-color, #fff);
  }
  button.hour.selected { outline: 2px solid var(--primary-text-color); outline-offset: 1px; }
  button.hour:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 1px; }

  .panel {
    display: flex;
    gap: 10px;
    align-items: flex-start;
    margin-top: 14px;
    padding: 10px 12px;
    border-radius: 8px;
    background: var(--secondary-background-color);
  }
  .swatch {
    flex: none;
    width: 12px;
    height: 12px;
    margin-top: 3px;
    border-radius: 3px;
    background: var(--color);
  }
  .when { font-size: 12px; line-height: 18px; color: var(--secondary-text-color); }
  .what { font-size: 14px; line-height: 20px; font-weight: 500; color: var(--primary-text-color); }
  .why { font-weight: 400; }

  .legend {
    display: flex;
    flex-wrap: wrap;
    gap: 4px 12px;
    margin-top: 12px;
    font-size: 11px;
    color: var(--secondary-text-color);
  }
  .legend span::before {
    content: "";
    display: inline-block;
    width: 9px;
    height: 9px;
    margin-right: 4px;
    border-radius: 2px;
    background: var(--color);
  }

  .great { --color: var(--green-color, #4caf50); }
  .good { --color: var(--light-green-color, #8bc34a); }
  .flat { --color: var(--blue-color, #2196f3); }
  .bad { --color: var(--orange-color, #ff9800); }
  .terrible { --color: var(--red-color, #f44336); }
  .dark, .unknown { --color: var(--disabled-color, #bdbdbd); }
`;

const ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
const escape = (text) => String(text).replace(/[&<>"']/g, (character) => ESCAPES[character]);
const pad = (number) => String(number).padStart(2, "0");
const hourOf = (slot) => Number(slot.time.slice(11, 13));

class SurfConditionsCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._selected = null; // the time of the tapped hour; null follows the clock
    this._drawn = null;
    this.shadowRoot.addEventListener("click", (event) => {
      const square = event.target.closest("button[data-time]");
      if (!square) return;
      const time = square.dataset.time;
      // Tapping the chosen hour again lets the panel follow the clock once more.
      this._selected = this._selected === time ? null : time;
      this._draw();
      const again = this.shadowRoot.querySelector(`button[data-time="${time}"]`);
      if (again) again.focus();
    });
  }

  static getStubConfig(hass) {
    const entity = Object.keys(hass.states).find(
      (id) => id.startsWith("sensor.") && Array.isArray(hass.states[id].attributes.forecast)
    );
    return { entity: entity || "" };
  }

  static getConfigForm() {
    const labels = { entity: "A spot's Rating sensor", title: "Title" };
    return {
      schema: [
        {
          name: "entity",
          required: true,
          selector: {
            entity: {
              filter: [{ integration: "surf_conditions", domain: "sensor", device_class: "enum" }],
            },
          },
        },
        { name: "title", selector: { text: {} } },
      ],
      computeLabel: (field) => labels[field.name],
    };
  }

  setConfig(config) {
    if (!config || typeof config.entity !== "string" || !config.entity) {
      throw new Error("Set entity to a spot's Rating sensor");
    }
    this._config = config;
    this._drawn = null;
    this._draw();
  }

  set hass(hass) {
    this._hass = hass;
    this._draw();
  }

  getCardSize() {
    return 4;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6 };
  }

  _draw() {
    const hass = this._hass;
    const config = this._config;
    if (!hass || !config) return;
    const stateObj = hass.states[config.entity];
    const hours = (stateObj && stateObj.attributes.forecast) || [];
    const now = Date.now();
    const current = hours.find((slot) => {
      const start = Date.parse(slot.time);
      return start <= now && now < start + HOUR;
    });
    if (this._selected && !hours.some((slot) => slot.time === this._selected)) this._selected = null;
    const shown = hours.find((slot) => slot.time === this._selected) || current;

    // The frontend hands over a new hass many times a minute; only redraw when something shows.
    const language = hass.locale && hass.locale.language;
    const drawn = [
      config.entity,
      config.title,
      stateObj && stateObj.last_updated,
      current && current.time,
      this._selected,
      language,
    ].join("|");
    if (drawn === this._drawn) return;
    this._drawn = drawn;

    const lit = hours.filter((slot) => slot.rating !== "dark");
    let body;
    if (!stateObj) {
      body = `<div class="note">${escape(config.entity)} is not available</div>`;
    } else if (!lit.length) {
      body = `<div class="note">No forecast yet</div>`;
    } else {
      body =
        this._strip(stateObj, lit, current, now) +
        this._panel(stateObj, shown, current) +
        this._legend(stateObj);
    }
    const header = config.title ? ` header="${escape(config.title)}"` : "";
    this.shadowRoot.innerHTML =
      `<style>${STYLE}</style>` +
      `<ha-card${header}><div class="content${config.title ? "" : " bare"}">${body}</div></ha-card>`;
  }

  _strip(stateObj, lit, current, now) {
    const first = Math.min(...lit.map(hourOf));
    const last = Math.max(...lit.map(hourOf));
    const columns = last - first + 1;
    const days = [...new Set(lit.map((slot) => slot.time.slice(0, 10)))];
    const every = columns > 14 ? 2 : 1; // long summer days have no room for every label

    let cells = "<span></span>";
    for (let hour = first; hour <= last; hour++) {
      cells += `<span class="label">${hour % every === 0 ? pad(hour) : ""}</span>`;
    }
    for (const day of days) {
      const weekday = this._weekday(day);
      cells += `<span class="day">${escape(weekday)}</span>`;
      for (let hour = first; hour <= last; hour++) {
        const slot = lit.find((item) => item.time.startsWith(`${day}T${pad(hour)}`));
        if (!slot) {
          cells += "<span></span>";
          continue;
        }
        const chosen = slot.time === this._selected;
        const classes = ["hour", slot.rating || "unknown"];
        if (Date.parse(slot.time) + HOUR <= now) classes.push("past");
        if (slot === current) classes.push("now");
        if (chosen) classes.push("selected");
        const word = this._word(stateObj, slot.rating);
        cells +=
          `<button class="${classes.join(" ")}" data-time="${escape(slot.time)}"` +
          ` title="${escape(`${pad(hour)}:00 ${word}`)}"` +
          ` aria-label="${escape(`${weekday} ${pad(hour)}:00, ${word}`)}"` +
          ` aria-pressed="${chosen}"></button>`;
      }
    }
    return `<div class="strip" style="--columns: ${columns}">${cells}</div>`;
  }

  _panel(stateObj, shown, current) {
    if (!shown) return `<div class="panel"><div class="when">No forecast for this hour</div></div>`;
    const hour = hourOf(shown);
    const span = `${pad(hour)}:00–${pad((hour + 1) % 24)}:00`;
    const when = `${this._weekday(shown.time.slice(0, 10))} ${span}${shown === current ? " · now" : ""}`;
    const rating = shown.rating || "unknown";
    let why = shown.reason || "";
    if (!why && rating === "great") why = "Everything is ideal";
    if (!why && rating === "dark") why = "Nothing is rated between last and first light";
    return (
      `<div class="panel"><span class="swatch ${rating}"></span><div>` +
      `<div class="when">${escape(when)}</div>` +
      `<div class="what">${escape(this._word(stateObj, shown.rating))}` +
      `${why ? `<span class="why"> · ${escape(why)}</span>` : ""}</div>` +
      `</div></div>`
    );
  }

  _legend(stateObj) {
    const entries = RATINGS.map(
      (rating) => `<span class="${rating}">${escape(this._word(stateObj, rating))}</span>`
    );
    return `<div class="legend">${entries.join("")}</div>`;
  }

  /* A rating in the user's language, from the sensor's own state translations. */
  _word(stateObj, rating) {
    if (!rating) return "Unknown";
    if (this._hass.formatEntityState) return this._hass.formatEntityState(stateObj, rating);
    return WORDS[rating] || rating;
  }

  _weekday(day) {
    const [year, month, date] = day.split("-").map(Number);
    const language = (this._hass.locale && this._hass.locale.language) || undefined;
    return new Date(year, month - 1, date).toLocaleDateString(language, { weekday: "short" });
  }
}

if (!customElements.get("surf-conditions-card")) {
  customElements.define("surf-conditions-card", SurfConditionsCard);
}
window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === "surf-conditions-card")) {
  window.customCards.push({
    type: "surf-conditions-card",
    name: "Surf Conditions",
    description: "A coloured square for every hour of light. Tap one to see why it is rated that way.",
    documentationURL: "https://github.com/nelferr/surf-conditions-homeassistant-custom-component",
  });
}
