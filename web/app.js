const RANKS = "AKQJT98765432";
const COLORS = {
  fold: "#3d5a80",
  check: "#2a9d8f",
  call: "#2a9d8f",
  open: "#e07a3d",
  "3bet": "#7b4b94",
  allin: "#c44536",
  bet_33: "#e6b15c",
  bet_75: "#e07a3d",
  bet_100: "#c44536",
  raise_33: "#e6b15c",
  raise_75: "#e07a3d",
  raise_100: "#9b3a3a",
};

const POSITIONS = ["UTG", "UTG+1", "MP", "HJ", "CO", "BTN", "SB", "BB"];

let meta = null;
let history = "";
let selectedHand = null;

const $ = (id) => document.getElementById(id);

function color(action) {
  return COLORS[action] || "#8d867c";
}

function classAt(row, col) {
  if (row === col) return RANKS[row] + RANKS[row];
  const hi = RANKS[Math.min(row, col)];
  const lo = RANKS[Math.max(row, col)];
  return hi + lo + (col > row ? "s" : "o");
}

async function loadMeta() {
  const res = await fetch("/api/preflop/meta");
  meta = await res.json();
  const lim = meta.limits;
  $("preflop-meta").textContent =
    `${meta.algorithm} · ${meta.iterations} iterations · open ${lim.open_bb}bb · 3-bet ${lim.three_bet_bb}bb · 4-bet ${lim.four_bet} when ≤${lim.four_bet_max_players_remaining} remain · ${lim.boards} showdown boards`;
  renderRfi();
  renderLegend(["fold", "call", "open", "3bet", "allin"]);
  await openNode(nodeForHistory(""));
}

function nodeSummaries(hist) {
  return meta.nodes.filter((n) => n.history === hist);
}

function nodeForHistory(hist) {
  const found = nodeSummaries(hist);
  return found[0] || null;
}

function renderRfi() {
  const box = $("rfi-seats");
  box.innerHTML = "";
  POSITIONS.forEach((pos, i) => {
    if (pos === "BB") return;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = pos;
    btn.onclick = () => openNode(nodeForHistory("f".repeat(i)));
    box.appendChild(btn);
  });
}

function renderLegend(actions) {
  const ul = $("legend");
  ul.innerHTML = "";
  actions.forEach((a) => {
    const li = document.createElement("li");
    li.innerHTML = `<i class="swatch" style="background:${color(a)}"></i>${a}`;
    ul.appendChild(li);
  });
}

async function openNode(summary) {
  $("terminal-note").hidden = true;
  if (!summary) {
    $("terminal-note").hidden = false;
    $("matrix-title").textContent = "Hand over";
    $("matrix-sub").textContent = history;
    $("matrix").innerHTML = "";
    $("line-actions").innerHTML = "";
    renderLine();
    return;
  }
  const q = new URLSearchParams({ player: summary.player, history: summary.history });
  const res = await fetch("/api/preflop/node?" + q.toString());
  const node = await res.json();
  history = node.history;
  selectedHand = null;
  $("matrix-title").textContent = node.player;
  $("matrix-sub").textContent = node.history ? `Line ${node.history}` : "Unopened pot";
  renderLegend(node.actions);
  renderLine();
  renderActions(node);
  renderMatrix(node);
  document.querySelectorAll("#rfi-seats button").forEach((btn, i) => {
    const pos = POSITIONS.filter((p) => p !== "BB")[i];
    btn.classList.toggle("on", node.player === pos && node.history === "f".repeat(POSITIONS.indexOf(pos)));
  });
}

function renderLine() {
  const ol = $("line");
  ol.innerHTML = "";
  const root = document.createElement("li");
  const b = document.createElement("button");
  b.type = "button";
  b.textContent = "UTG to act";
  b.onclick = () => openNode(nodeForHistory(""));
  root.appendChild(b);
  ol.appendChild(root);
  for (let i = 0; i < history.length; i++) {
    const li = document.createElement("li");
    const btn = document.createElement("button");
    btn.type = "button";
    const prefix = history.slice(0, i + 1);
    btn.textContent = prefix;
    btn.onclick = () => {
      const next = nodeForHistory(prefix);
      if (next) openNode(next);
      else {
        history = prefix;
        openNode(null);
      }
    };
    li.appendChild(btn);
    ol.appendChild(li);
  }
}

function renderActions(node) {
  const box = $("line-actions");
  box.innerHTML = "";
  const chars = { fold: "f", check: "x", call: "c", open: "o", "3bet": "t", allin: "j" };
  node.actions.forEach((action) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = action;
    btn.onclick = () => {
      const nextHist = node.history + (chars[action] || "?");
      const next = nodeForHistory(nextHist);
      if (next) openNode(next);
      else {
        history = nextHist;
        openNode(null);
      }
    };
    box.appendChild(btn);
  });
}

function renderMatrix(node) {
  const grid = $("matrix");
  grid.innerHTML = "";
  const corner = document.createElement("div");
  grid.appendChild(corner);
  for (const r of RANKS) {
    const h = document.createElement("div");
    h.className = "h";
    h.textContent = r;
    grid.appendChild(h);
  }
  const handIndex = new Map(node.hands.map((h, i) => [h, i]));
  for (let row = 0; row < 13; row++) {
    const lab = document.createElement("div");
    lab.className = "lab";
    lab.textContent = RANKS[row];
    grid.appendChild(lab);
    for (let col = 0; col < 13; col++) {
      const label = classAt(row, col);
      const idx = handIndex.get(label);
      const cell = document.createElement("div");
      cell.className = "cell";
      const bars = document.createElement("div");
      bars.className = "bars";
      const probs = node.strategy[idx];
      node.actions.forEach((action, a) => {
        const span = document.createElement("span");
        span.style.width = (probs[a] * 100).toFixed(2) + "%";
        span.style.background = color(action);
        bars.appendChild(span);
      });
      const name = document.createElement("b");
      name.textContent = label;
      cell.appendChild(bars);
      cell.appendChild(name);
      cell.onclick = () => {
        selectedHand = label;
        document.querySelectorAll(".cell.on").forEach((c) => c.classList.remove("on"));
        cell.classList.add("on");
        const parts = node.actions.map((action, a) => `${action} ${(probs[a] * 100).toFixed(1)}%`);
        $("cell-detail").textContent = `${node.player} · ${label} · ${parts.join(" · ")}`;
      };
      grid.appendChild(cell);
    }
  }
}

function setTab(name) {
  $("view-preflop").hidden = name !== "preflop";
  $("view-postflop").hidden = name !== "postflop";
  $("tab-preflop").classList.toggle("on", name === "preflop");
  $("tab-postflop").classList.toggle("on", name === "postflop");
}

$("tab-preflop").onclick = () => setTab("preflop");
$("tab-postflop").onclick = () => setTab("postflop");

let playerCount = 0;
function addPlayer(position, stack, range) {
  const row = document.createElement("div");
  row.className = "player-row";
  const pos = document.createElement("select");
  POSITIONS.forEach((p) => {
    const o = document.createElement("option");
    o.value = p;
    o.textContent = p;
    if (p === position) o.selected = true;
    pos.appendChild(o);
  });
  const st = document.createElement("input");
  st.type = "number";
  st.min = "0";
  st.step = "0.5";
  st.value = stack;
  st.className = "stack";
  const rg = document.createElement("input");
  rg.value = range;
  rg.className = "range";
  rg.spellcheck = false;
  const rm = document.createElement("button");
  rm.type = "button";
  rm.textContent = "Remove";
  rm.onclick = () => row.remove();
  row.append(pos, st, rg, rm);
  $("players").appendChild(row);
  playerCount += 1;
}

function fillExample() {
  $("players").innerHTML = "";
  $("board").value = "Kh7d2c2s3d";
  $("pot").value = "3";
  $("iterations").value = "200";
  $("max-agg").value = "2";
  $("chance").value = "";
  addPlayer("SB", "10", "KsKd,AsKs");
  addPlayer("BB", "10", "Ah9d,QcJc");
  addPlayer("BTN", "10", "6h5h,7c6c");
}

$("add-player").onclick = () => addPlayer("CO", "100", "JJ,AQs");
$("example-3way").onclick = fillExample;
addPlayer("BTN", "100", "AA,KK,QQ,AKs");
addPlayer("BB", "100", "JJ,TT,AQs,AKo");

$("spot-form").onsubmit = async (event) => {
  event.preventDefault();
  const players = [...document.querySelectorAll(".player-row")].map((row) => ({
    position: row.querySelector("select").value,
    stack_bb: Number(row.querySelector(".stack").value),
    range: row.querySelector(".range").value,
  }));
  const chanceRaw = $("chance").value.trim();
  const body = {
    board: $("board").value.trim(),
    pot_bb: Number($("pot").value),
    iterations: Number($("iterations").value),
    max_agg: Number($("max-agg").value),
    bet_fractions: [0.33, 0.75, 1.0],
    include_all_in: true,
    players,
  };
  if (chanceRaw) body.chance_samples = Number(chanceRaw);
  $("solve").disabled = true;
  $("solve-status").textContent = "Solving…";
  try {
    const res = await fetch("/api/solve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok || data.error) {
      $("solve-status").textContent = data.error || "Solve failed";
      $("results").hidden = true;
      return;
    }
    $("solve-status").textContent =
      `${data.iterations} iterations · ${data.chance} · weighted EV sum ${data.ev_weighted_sum_bb.toFixed(3)} bb`;
    showResults(data);
  } catch (err) {
    $("solve-status").textContent = String(err);
  } finally {
    $("solve").disabled = false;
  }
};

function showResults(data) {
  $("results").hidden = false;
  const picker = $("node-picker");
  picker.innerHTML = "";
  data.nodes.forEach((node, i) => {
    const btn = document.createElement("button");
    btn.type = "button";
    const line = node.history.length ? node.history.join(" → ") : "to act";
    btn.textContent = `${node.player}: ${line}`;
    btn.onclick = () => {
      [...picker.children].forEach((c) => c.classList.remove("on"));
      btn.classList.add("on");
      renderTable(data, node);
    };
    if (i === 0) btn.classList.add("on");
    picker.appendChild(btn);
  });
  if (data.nodes[0]) renderTable(data, data.nodes[0]);
}

function renderTable(data, node) {
  const evOf = new Map();
  const seat = data.players.find((p) => p.position === node.player);
  if (seat) seat.combos.forEach((c) => evOf.set(c.combo, c.ev_bb));
  const head = $("result-head");
  head.innerHTML = `<tr><th>Combo</th><th>EV bb</th><th>Mix</th>${node.actions
    .map((a) => `<th>${a}</th>`)
    .join("")}</tr>`;
  const rows = node.combos
    .map((c) => ({ ...c, ev: evOf.get(c.combo) ?? 0 }))
    .sort((a, b) => b.ev - a.ev);
  $("result-body").innerHTML = rows
    .map((c) => {
      const bar = c.strategy
        .map((p, i) => `<span style="width:${(p * 100).toFixed(2)}%;background:${color(node.actions[i])}"></span>`)
        .join("");
      const nums = c.strategy.map((p) => `<td>${(p * 100).toFixed(1)}</td>`).join("");
      return `<tr><td>${c.combo}</td><td>${c.ev.toFixed(2)}</td><td><div class="bar">${bar}</div></td>${nums}</tr>`;
    })
    .join("");
}

loadMeta().catch((err) => {
  $("preflop-meta").textContent = String(err);
});
